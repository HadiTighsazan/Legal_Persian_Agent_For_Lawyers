"""
Celery tasks for the document processing pipeline.

Provides two Celery tasks:
- ``extract_text_from_pdf`` — opens a PDF with PyMuPDF (RTL-aware), extracts text
  page-by-page with ``[PAGE N]`` markers, with automatic fallback to pdfplumber
  and Tesseract OCR for garbled Persian text. For scanned PDFs (no selectable
  text), routes to the EasyOCR pipeline with layout-aware assembly.
- ``chunk_document`` — receives the extracted text, delegates to
  :class:`~documents.services.anchor_chunking_service.AnchorChunkingService`,
  and persists the resulting chunks via bulk create.

The orchestration function ``process_document`` has been moved to
:mod:`documents.services.processing_service` — it is a **regular Python function**
(not a Celery task) called directly from the API view. It is re-exported from
:mod:`documents.tasks` for backward compatibility.

.. note::
   The ``embed_document`` task has been moved to
   :mod:`documents.tasks.embedding_tasks` to avoid dual ``ProcessingTask``
   management. See that module for the current implementation.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import traceback
from typing import Any, Optional

from celery import chain, shared_task
from django.conf import settings
from django.db import transaction, IntegrityError, OperationalError
from django.utils import timezone

import fitz  # PyMuPDF

from documents.models import Document, DocumentChunk
from documents.services.anchor_chunking_service import (
    AnchorChunkingService,
)
from documents.services.error_handler import (
    classify_pdf_error,
    fail_processing_task,
    log_milestone,
)
from documents.services.non_text_filter import NonTextChunkFilter
from documents.services.persian_normalizer import PersianNormalizer
from documents.storage import get_storage_backend
from documents.utils.scanned_pdf_detector import is_scanned_pdf
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quality heuristic for Persian text
# ---------------------------------------------------------------------------


def _compute_garbled_ratio(text: str) -> float:
    """Compute the garbled ratio for Persian text.

    Uses a heuristic: counts the proportion of Persian/Arabic characters that
    appear isolated (surrounded by non-Persian characters). In properly rendered
    Persian text, most characters should be adjacent to other Persian characters.

    The Arabic/Persian Unicode block is U+0600–U+06FF.

    Args:
        text: The extracted text to evaluate.

    Returns:
        A float ratio (0.0–1.0) representing the proportion of isolated
        Persian characters. Returns 0.0 if no Persian characters are found.
    """
    if not text or not text.strip():
        return 0.0

    persian_range = range(0x0600, 0x06FF + 1)
    isolated_count = 0
    total_persian = 0

    for i, ch in enumerate(text):
        if ord(ch) in persian_range:
            total_persian += 1
            # Check if surrounded by non-Persian characters
            prev_char = text[i - 1] if i > 0 else " "
            next_char = text[i + 1] if i + 1 < len(text) else " "

            prev_is_persian = ord(prev_char) in persian_range
            next_is_persian = ord(next_char) in persian_range

            # A character is "isolated" if neither neighbor is Persian
            if not prev_is_persian and not next_is_persian:
                isolated_count += 1

    if total_persian == 0:
        return 0.0

    return isolated_count / total_persian


def _is_persian_text_garbled(text: str, threshold: float | None = None) -> bool:
    """Check if extracted Persian text appears garbled (RTL reversal).

    Uses :func:`_compute_garbled_ratio` to get the ratio of isolated Persian
    characters, then compares it against the threshold.

    Args:
        text: The extracted text to evaluate.
        threshold: Ratio threshold (0.0–1.0). If the proportion of isolated
            Persian chars exceeds this, the text is considered garbled.
            Defaults to ``settings.EXTRACTION_GARBLED_THRESHOLD`` or 0.3.

    Returns:
        ``True`` if the text appears garbled, ``False`` otherwise.
    """
    if not text or not text.strip():
        return False

    if threshold is None:
        threshold = getattr(settings, "EXTRACTION_GARBLED_THRESHOLD", 0.3)

    ratio = _compute_garbled_ratio(text)
    logger.debug(
        "Persian garbled check: ratio=%.2f, threshold=%.2f",
        ratio,
        threshold,
    )
    return ratio > threshold


def _has_shattered_persian_words(text: str, threshold: float = 0.4) -> bool:
    """Detect if Persian text has shattered words (spaces between letters).

    In properly extracted Persian text, most space-delimited tokens contain
    multiple Persian characters (e.g., ``قانون``, ``مدنی``). When PyMuPDF
    mis-extracts RTL text, it inserts spaces between characters, turning
    ``قانون`` into ``ق ا ن و ن`` — each character becomes its own "word".

    This heuristic counts how many Persian "words" (space-delimited tokens)
    consist of a single Persian character. In normal Persian text, single-
    character words are rare (e.g., ``و`` meaning "and", ``به`` is two chars).
    In shattered text, almost every character becomes its own "word".

    Args:
        text: Extracted text to evaluate.
        threshold: If the ratio of single-Persian-char tokens to total
            Persian tokens exceeds this value, the text is considered
            shattered. Defaults to 0.4.

    Returns:
        ``True`` if text appears to have shattered Persian words.
    """
    tokens = text.split()
    if not tokens:
        return False

    persian_range = range(0x0600, 0x06FF + 1)
    single_char_count = 0
    persian_token_count = 0

    for token in tokens:
        # Count Persian chars in this token
        persian_chars = [c for c in token if ord(c) in persian_range]
        if not persian_chars:
            continue
        persian_token_count += 1
        # If the token is exactly one Persian character (possibly with
        # surrounding non-Persian), it's suspicious
        if len(persian_chars) == 1:
            single_char_count += 1

    if persian_token_count == 0:
        return False

    ratio = single_char_count / persian_token_count
    logger.debug(
        "Shattered Persian word check: %d/%d single-char tokens "
        "(ratio=%.2f, threshold=%.2f)",
        single_char_count,
        persian_token_count,
        ratio,
        threshold,
    )
    return ratio > threshold


# ---------------------------------------------------------------------------
# Extraction strategy helpers
# ---------------------------------------------------------------------------


def _extract_with_pymupdf_rtl(pdf_document: fitz.Document) -> str:
    """Extract text using PyMuPDF with RTL-aware flags.

    Uses ``TEXT_PRESERVE_LIGATURES`` and ``TEXT_PRESERVE_WHITESPACE`` flags
    to improve Persian/Arabic text extraction quality compared to bare
    ``page.get_text()``.

    Args:
        pdf_document: An open PyMuPDF document.

    Returns:
        Extracted text with ``[PAGE N]`` markers.
    """
    page_texts: list[str] = []
    for page_num in range(pdf_document.page_count):
        page = pdf_document.load_page(page_num)
        # RTL-aware flags for better Persian extraction.
        # TEXT_PRESERVE_LIGATURES: keeps Arabic/Persian ligatures intact.
        # TEXT_PRESERVE_WHITESPACE: preserves original whitespace layout.
        # TEXT_PRESERVE_IMAGES: includes image alt-text if present.
        # TEXT_DEHYPHENATE: re-joins hyphenated words broken across lines.
        text = page.get_text(
            "text",
            flags=(
                fitz.TEXT_PRESERVE_LIGATURES
                | fitz.TEXT_PRESERVE_WHITESPACE
                | fitz.TEXT_PRESERVE_IMAGES
                | fitz.TEXT_DEHYPHENATE
            ),
        )
        page_texts.append(f"[PAGE {page_num + 1}]\n{text}")
    return "\n".join(page_texts)


def _extract_with_pdfplumber(pdf_content: bytes) -> str:
    """Fallback extraction using pdfplumber with RTL reshaping.

    pdfplumber often preserves paragraph structure better for Persian PDFs
    than PyMuPDF, especially for documents with complex RTL layouts.

    Additionally uses ``arabic_reshaper`` and ``python-bidi`` to properly
    reconstruct Persian/Arabic text from pdfplumber's output, which handles
    RTL layout better than PyMuPDF for complex legal PDFs.

    Args:
        pdf_content: Raw PDF file bytes.

    Returns:
        Extracted text with ``[PAGE N]`` markers, with Persian/Arabic
        text reshaped for proper RTL rendering.
    """
    import pdfplumber  # noqa: PLC0415

    # Optional RTL reshaping — gracefully degrade if libraries not installed
    try:
        import arabic_reshaper  # noqa: PLC0415
        from bidi.algorithm import get_display  # noqa: PLC0415
        _reshaping_available = True
    except ImportError:
        _reshaping_available = False

    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        page_texts: list[str] = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            # Reshape Persian/Arabic text for proper RTL rendering
            if text.strip() and _reshaping_available:
                try:
                    reshaped = arabic_reshaper.reshape(text)
                    text = get_display(reshaped)
                except Exception:
                    pass  # Fall back to raw text if reshaping fails
            page_texts.append(f"[PAGE {i + 1}]\n{text}")
    return "\n".join(page_texts)


def _extract_with_tesseract(pdf_content: bytes) -> str:
    """Fallback OCR extraction using Tesseract with Persian language pack.

    Used as the last resort when both PyMuPDF and pdfplumber produce garbled
    text (e.g., scanned PDFs or image-based documents).

    Requires:
    - ``pytesseract`` package
    - Tesseract OCR installed on the system with Persian (fas) and Arabic (ara) language packs

    Args:
        pdf_content: Raw PDF file bytes.

    Returns:
        OCR-extracted text with ``[PAGE N]`` markers.
    """
    import pytesseract  # noqa: PLC0415
    from pdf2image import convert_from_bytes  # noqa: PLC0415

    images = convert_from_bytes(pdf_content)
    page_texts: list[str] = []
    for i, img in enumerate(images):
        # Use both Persian and Arabic language packs for better coverage
        text = pytesseract.image_to_string(img, lang="fas+ara")
        page_texts.append(f"[PAGE {i + 1}]\n{text}")
    return "\n".join(page_texts)


# ---------------------------------------------------------------------------
# Subtask 4a — Extract text from PDF
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def extract_text_from_pdf(self, document_id: str) -> str:
    """Open a PDF, extract text page-by-page, and return text with page markers.

    Uses a three-layer extraction strategy for Persian legal documents:

    1. **Primary: PyMuPDF with RTL flags** — Uses ``TEXT_PRESERVE_LIGATURES``
       and ``TEXT_PRESERVE_WHITESPACE`` flags for better RTL support.
    2. **Fallback 1: pdfplumber** — If PyMuPDF output has >30% isolated
       Persian characters (heuristic), re-extract with pdfplumber.
    3. **Fallback 2: Tesseract OCR** — If both PyMuPDF and pdfplumber fail,
       fall back to OCR with Persian language pack.

    After extraction, the text is passed through :class:`PersianNormalizer` to
    fix Tatweel, character variants, half-spaces, and control characters.

    The returned string uses ``[PAGE N]`` markers so that downstream tasks
    (chunking) can track which pages each chunk spans.

    Transient database/storage errors are automatically retried up to 3 times
    with exponential backoff. Permanent PDF errors (corrupted, password-protected)
    are caught and marked as failed without retry.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to process.

    Returns:
        The full extracted text with ``[PAGE N]`` markers inserted between pages.
        Returns an empty string for empty PDFs (0 pages).

    Raises:
        The task is marked as failed on error; exceptions are **not** re-raised
        so the Celery worker does not retry indefinitely.
    """
    log_milestone(logger, document_id, "Starting extraction")

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("extract_text_from_pdf: Document %s not found", document_id)
        return ""

    # Find the pending ProcessingTask created by process_document().
    processing_task = ProcessingTask.objects.filter(
        document=document,
        task_type="extract",
        status="pending",
    ).order_by("-created_at").first()

    if processing_task is None:
        processing_task = ProcessingTask.objects.create(
            document=document,
            task_type="extract",
            celery_task_id=self.request.id,
            status="running",
            started_at=timezone.now(),
        )
    else:
        processing_task.celery_task_id = self.request.id
        processing_task.status = "running"
        processing_task.started_at = timezone.now()
        processing_task.save(update_fields=["celery_task_id", "status", "started_at"])

    # Mark the document as processing.
    document.processing_status = "processing"
    document.status = "processing"
    document.save(update_fields=["processing_status", "status"])

    # Initialize auto_fallback before any conditional branches to prevent
    # NameError in exception fallback paths.
    auto_fallback = True

    try:
        # Resolve the PDF content using the storage backend.
        storage = get_storage_backend()
        logger.info(
            "extract_text_from_pdf: Opening file_path=%s for document %s",
            document.file_path,
            document_id,
        )
        pdf_content = storage.open(document.file_path)

        # Check PDF magic bytes before attempting to open.
        header = pdf_content.read(4)
        pdf_content.seek(0)
        if header != b"%PDF":
            fail_processing_task(
                processing_task, document, "File is not a valid PDF", logger,
            )
            return ""

        pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
    except fitz.FileDataError as e:
        error_msg = classify_pdf_error(e, document.file_path)
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""
    except Exception as e:
        error_msg = classify_pdf_error(e, document.file_path)
        logger.exception(
            "extract_text_from_pdf: Unhandled exception for document %s "
            "(file_path=%s, error_type=%s)",
            document_id,
            document.file_path,
            type(e).__name__,
        )
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""

    try:
        num_pages = pdf_document.page_count
        if num_pages == 0:
            logger.info(
                "extract_text_from_pdf: Document %s has 0 pages — returning empty string",
                document_id,
            )
            document.extracted_text_length = 0
            document.save(update_fields=["extracted_text_length"])
            processing_task.status = "completed"
            processing_task.completed_at = timezone.now()
            processing_task.save(update_fields=["status", "completed_at"])
            return ""

        # ------------------------------------------------------------------
        # Read PDF bytes early — before any conditional branches — to prevent
        # stream consumption issues. Once read, use the saved bytes consistently
        # throughout the function instead of calling pdf_content.read() again.
        # ------------------------------------------------------------------
        pdf_bytes = (
            pdf_content.read()
            if hasattr(pdf_content, "read")
            else pdf_content
        )

        # ------------------------------------------------------------------
        # Scanned PDF detection — route to EasyOCR pipeline
        # ------------------------------------------------------------------
        # Before attempting PyMuPDF extraction, check if the PDF is scanned
        # (image-based with no selectable text). If so, skip directly to the
        # EasyOCR pipeline with layout-aware assembly.
        easyocr_enabled = getattr(settings, "OCR_EASYOCR_ENABLED", True)

        if easyocr_enabled:
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False
                ) as tmp:
                    tmp.write(pdf_bytes)
                    tmp_path = tmp.name

                try:
                    scanned = is_scanned_pdf(tmp_path)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        logger.warning(
                            "Failed to clean up temp file %s", tmp_path,
                        )

                if scanned:
                    logger.info(
                        "Document %s is scanned — using EasyOCR pipeline",
                        document_id,
                    )
                    try:
                        from documents.services.ocr_service import (
                            OcrService,
                        )

                        ocr = OcrService()
                        extracted_text, _ = ocr.extract_text(
                            pdf_bytes
                        )
                        extraction_method = "easyocr"

                        # Skip directly to normalization (skip PyMuPDF chain)
                        auto_fallback = False  # No need for fallback chain

                        logger.info(
                            "EasyOCR extraction complete for document %s "
                            "(%d chars)",
                            document_id,
                            len(extracted_text),
                        )
                    except Exception as e:
                        logger.error(
                            "EasyOCR failed for document %s: %s — "
                            "falling back to standard extraction chain",
                            document_id,
                            e,
                        )
                        # Fall through to standard extraction chain
                        pdf_document_for_extraction = fitz.open(
                            stream=pdf_bytes, filetype="pdf"
                        )
                        extracted_text = _extract_with_pymupdf_rtl(
                            pdf_document_for_extraction
                        )
                        pdf_document_for_extraction.close()
                        extraction_method = "pymupdf"
                else:
                    # Not scanned — use standard PyMuPDF extraction
                    pdf_document_for_extraction = fitz.open(
                        stream=pdf_bytes, filetype="pdf"
                    )
                    extracted_text = _extract_with_pymupdf_rtl(
                        pdf_document_for_extraction
                    )
                    pdf_document_for_extraction.close()
                    extraction_method = "pymupdf"
            except Exception as e:
                logger.warning(
                    "Scanned PDF detection failed for document %s: %s — "
                    "falling back to standard extraction",
                    document_id,
                    e,
                )
                # Fall through to standard extraction
                pdf_document_for_extraction = fitz.open(
                    stream=pdf_bytes, filetype="pdf"
                )
                extracted_text = _extract_with_pymupdf_rtl(
                    pdf_document_for_extraction
                )
                pdf_document_for_extraction.close()
                extraction_method = "pymupdf"
        else:
            # EasyOCR disabled — use standard extraction chain
            pdf_document_for_extraction = fitz.open(
                stream=pdf_bytes, filetype="pdf"
            )

            # Stage 1: Primary extraction with PyMuPDF + RTL flags
            extracted_text = _extract_with_pymupdf_rtl(
                pdf_document_for_extraction
            )
            pdf_document_for_extraction.close()

            auto_fallback = getattr(settings, "EXTRACTION_AUTO_FALLBACK", True)
            extraction_method = "pymupdf"

        # ------------------------------------------------------------------
        # Extraction strategy with auto-fallback (for typed PDFs)
        # ------------------------------------------------------------------
        # auto_fallback is already initialized at function start, so it's
        # always defined even in exception fallback paths.

        # Helper: check both garbled-text heuristics (isolated chars + shattered words)
        def _is_garbled(t: str) -> bool:
            return _is_persian_text_garbled(t) or _has_shattered_persian_words(t)

        # Stage 2: Check quality and fall back to pdfplumber if garbled
        if auto_fallback and _is_garbled(extracted_text):
            logger.warning(
                "extract_text_from_pdf: PyMuPDF output garbled for Persian text "
                "(document %s) — trying pdfplumber...",
                document_id,
            )
            try:
                extracted_text = _extract_with_pdfplumber(pdf_bytes)
                extraction_method = "pdfplumber"
            except Exception as e:
                logger.warning(
                    "extract_text_from_pdf: pdfplumber extraction failed for "
                    "document %s: %s",
                    document_id,
                    e,
                )

            # Stage 3: Check again and fall back to Tesseract OCR
            if _is_garbled(extracted_text):
                logger.warning(
                    "extract_text_from_pdf: pdfplumber also garbled for document "
                    "%s — falling back to Tesseract OCR...",
                    document_id,
                )
                try:
                    extracted_text = _extract_with_tesseract(pdf_bytes)
                    extraction_method = "tesseract"
                except Exception as e:
                    logger.warning(
                        "extract_text_from_pdf: Tesseract OCR also failed for "
                        "document %s: %s",
                        document_id,
                        e,
                    )

        # ------------------------------------------------------------------
        # Apply Persian normalization
        # ------------------------------------------------------------------
        persian_normalization_enabled = getattr(
            settings, "PERSIAN_NORMALIZATION_ENABLED", True
        )
        if persian_normalization_enabled:
            try:
                normalizer = PersianNormalizer()
                extracted_text = normalizer.normalize(extracted_text)
            except Exception as e:
                logger.warning(
                    "extract_text_from_pdf: Persian normalization failed for "
                    "document %s: %s — continuing with unnormalized text",
                    document_id,
                    e,
                )

        # Compute garbled score on the final extracted text.
        garbled_score = _compute_garbled_ratio(extracted_text)

        # Update document metadata including extraction monitoring fields.
        document.extracted_text = extracted_text
        document.extraction_method = extraction_method
        document.garbled_score = garbled_score
        document.extracted_text_length = len(extracted_text)
        document.total_pages = num_pages
        document.save(
            update_fields=[
                "extracted_text",
                "extraction_method",
                "garbled_score",
                "extracted_text_length",
                "total_pages",
            ]
        )

        # Mark the ProcessingTask as completed.
        processing_task.status = "completed"
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "completed_at"])

        log_milestone(
            logger, document_id, "Extraction complete",
            pages=num_pages, chars=len(extracted_text),
        )

        return extracted_text
    finally:
        # Ensure pdf_document is always closed, even if an exception occurs
        # in any of the extraction branches above. This prevents resource leaks.
        pdf_document.close()


# ---------------------------------------------------------------------------
# Subtask 4b — Chunk extracted text
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def chunk_document(self, extracted_text: str, document_id: str) -> None:
    """Split ``extracted_text`` into chunks and persist them to the database.

    Uses the :class:`~documents.services.anchor_chunking_service.AnchorChunkingService`
    which applies text anchor (لنگر متنی) segmentation for Persian legal documents,
    with token-based overlap splitting for long segments. Metadata is stored
    separately from chunk content to avoid embedding pollution.

    This task is designed to be the second link in a Celery chain, receiving
    ``extracted_text`` from :func:`extract_text_from_pdf`.

    Transient database/storage errors are automatically retried up to 3 times
    with exponential backoff.

    Args:
        extracted_text: The full extracted text (with page markers) returned by
            the extraction task.
        document_id: The UUID (as a string) of the :class:`Document`.
    """
    log_milestone(logger, document_id, "Starting chunking")

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("chunk_document: Document %s not found", document_id)
        return

    # If the document is already in a terminal failed state, skip entirely.
    if document.processing_status == "failed":
        logger.info(
            "chunk_document: Document %s is already failed — skipping chunking",
            document_id,
        )
        return

    # Create a new ProcessingTask for the chunk step.
    chunk_task = ProcessingTask.objects.create(
        document=document,
        task_type="chunk",
        celery_task_id=self.request.id,
        status="running",
        started_at=timezone.now(),
    )

    # Handle empty text — mark as failed.
    if not extracted_text or not extracted_text.strip():
        logger.warning(
            "chunk_document: Document %s has no extracted text — marking as failed",
            document_id,
        )
        fail_processing_task(
            chunk_task,
            document,
            "Text extraction produced no content. The PDF may be image-based, "
            "scanned, or contain unsupported characters.",
            logger,
        )
        return

    try:
        # Use AnchorChunkingService with settings-based configuration
        anchor_chunking_enabled = getattr(
            settings, "ANCHOR_CHUNKING_ENABLED", True
        )
        chunk_tokens = getattr(settings, "ANCHOR_CHUNK_TOKENS", 400)
        overlap_tokens = getattr(settings, "ANCHOR_OVERLAP_TOKENS", 50)

        chunker = AnchorChunkingService()
        chunk_results = chunker.chunk_text(
            extracted_text,
            chunk_tokens=chunk_tokens,
            overlap_tokens=overlap_tokens,
        )

        # Filter out non-text chunks (e.g., table of contents) before
        # persisting to the database. This prevents structural artifacts from
        # polluting the vector store.
        if getattr(settings, "NON_TEXT_CHUNK_FILTERING_ENABLED", True):
            pre_filter_count = len(chunk_results)
            non_text_filter = NonTextChunkFilter()
            chunk_results = non_text_filter.filter_chunks(chunk_results)
            filtered_count = pre_filter_count - len(chunk_results)
            if filtered_count > 0:
                logger.info(
                    "Non-text chunk filter removed %d chunk(s) "
                    "(kept %d) for document %s",
                    filtered_count,
                    len(chunk_results),
                    document_id,
                )

        # Build DocumentChunk instances with metadata.
        # The AnchorChunk stores metadata SEPARATELY from content (no
        # embedding pollution). Denormalized fields (law_name, legal_status,
        # approval_date, legal_type) are populated from chunk.metadata for
        # efficient SQL-level filtering.
        #
        # IMPORTANT: Normalize chunk content for FTS before saving. The DB
        # trigger ``trg_chunk_search_vector`` builds the ``search_vector``
        # using ``to_tsvector('simple', ...)``, which does NOT convert Persian
        # digits (۰۱۲۳۴۵۶۷۸۹) to English digits (0123456789). By normalizing
        # here, we ensure the stored content (and thus the ``search_vector``)
        # uses English digits, so FTS queries with English digits match correctly.
        #
        # AnchorChunk uses ``pages: List[int]`` — we map min(pages) to
        # page_start and max(pages) to page_end for backward compatibility
        # with the DocumentChunk model.
        chunks_to_create = [
            DocumentChunk(
                document=document,
                chunk_index=i,
                page_start=min(chunk.pages) if chunk.pages else 1,
                page_end=max(chunk.pages) if chunk.pages else 1,
                content=PersianNormalizer.normalize_for_fts(chunk.content),
                token_count=chunk.token_count,
                metadata=chunk.metadata,
                law_name=chunk.metadata.get("law_name"),
                legal_status=chunk.metadata.get("legal_status"),
                approval_date=chunk.metadata.get("approval_date"),
                legal_type=chunk.metadata.get("legal_type"),
            )
            for i, chunk in enumerate(chunk_results)
        ]

        try:
            with transaction.atomic():
                DocumentChunk.objects.bulk_create(chunks_to_create)
        except (IntegrityError, OperationalError) as e:
            fail_processing_task(
                chunk_task, document,
                "Database error during chunking",
                logger,
            )
            return

        # Update document metadata.
        document.total_chunks = len(chunks_to_create)
        document.save(update_fields=["total_chunks"])

        # Mark the chunk ProcessingTask as completed.
        chunk_task.status = "completed"
        chunk_task.completed_at = timezone.now()
        chunk_task.save(update_fields=["status", "completed_at"])

        log_milestone(
            logger, document_id, "Chunking complete",
            chunks=len(chunks_to_create),
        )

    except Exception:
        error_message = traceback.format_exc()
        fail_processing_task(chunk_task, document, error_message, logger)


# ---------------------------------------------------------------------------
# Subtask 4c — Orchestration (Celery chain)
# ---------------------------------------------------------------------------


@shared_task(bind=True)
def _handle_chain_error(
    self,
    request: Any,
    exc: Exception,
    traceback_obj: Any,
    document_id: str,
    task_type: str = "extract",
) -> None:
    """Error callback for the Celery chain.

    When the chain fails (e.g., worker crash, unhandled exception), this task
    is triggered via ``link_error`` to update the ``ProcessingTask`` status
    to ``"failed"`` so it doesn't remain stuck at ``"pending"`` forever.

    Celery's ``link_error`` passes ``(request, exc, traceback)`` as positional
    args **before** the signature args (``document_id``, ``task_type``).
    """
    log_milestone(
        logger, document_id,
        "Chain failed — marking %s task as failed" % task_type,
    )

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("_handle_chain_error: Document %s not found", document_id)
        return

    processing_task = ProcessingTask.objects.filter(
        document=document,
        task_type=task_type,
        status__in=("pending", "running"),
    ).order_by("-created_at").first()

    if processing_task:
        processing_task.status = "failed"
        processing_task.error_message = (
            processing_task.error_message
            or "Chain-level failure: the Celery pipeline encountered an unrecoverable error"
        )
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "error_message", "completed_at"])

    if document.processing_status not in ("completed", "failed"):
        document.processing_status = "failed"
        document.status = "failed"
        document.processing_error = (
            document.processing_error
            or "Chain-level failure: the Celery pipeline encountered an unrecoverable error"
        )
        document.save(update_fields=["processing_status", "status", "processing_error"])
