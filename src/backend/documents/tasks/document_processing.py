"""
Celery tasks for the document processing pipeline.

Provides three tasks:
- ``extract_text_from_pdf`` — opens a PDF with PyMuPDF, extracts text page-by-page,
  and inserts ``[PAGE N]`` markers.
- ``chunk_document`` — receives the extracted text, delegates to
  :class:`~documents.services.chunking_service.ChunkingService`, and persists the
  resulting chunks via bulk create.
- ``process_document`` — orchestrates the full pipeline as a Celery chain.
  This is a **regular Python function** (not a Celery task) called directly from
  the API view to avoid deadlock risks.
"""

from __future__ import annotations

import logging
import traceback
import os

from celery import chain, shared_task
from django.db import transaction, IntegrityError, OperationalError
from django.utils import timezone

import fitz  # PyMuPDF

from documents.models import Document, DocumentChunk
from documents.services.chunking_service import ChunkingService
from documents.storage import get_storage_backend
from tasks.models import ProcessingTask
from django.conf import settings

logger = logging.getLogger(__name__)


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
    logger.info("extract_text_from_pdf: Starting extraction for document %s", document_id)

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("extract_text_from_pdf: Document %s not found", document_id)
        return ""

    # Get the existing ProcessingTask created by process_document.
    processing_task = ProcessingTask.objects.filter(
        document=document,
        task_type="extract",
    ).order_by('-created_at').first()

    if not processing_task:
        # Fallback: create if not found (shouldn't happen in normal flow).
        processing_task = ProcessingTask.objects.create(
            document=document,
            task_type="extract",
            celery_task_id=self.request.id,
            status="running",
            started_at=timezone.now(),
        )
    else:
        # Update the existing task.
        processing_task.celery_task_id = self.request.id
        processing_task.status = "running"
        processing_task.started_at = timezone.now()
        processing_task.save(update_fields=["celery_task_id", "status", "started_at"])

    # Mark the document as processing.
    document.processing_status = "processing"
    document.save(update_fields=["processing_status"])

    try:
        # Resolve the PDF path using the storage backend.
        # For local storage, file_path is already an absolute path.
        # For S3 storage, we'd need to download the file first.
        if os.path.isabs(document.file_path):
            pdf_path = document.file_path
        else:
            pdf_path = os.path.join(settings.MEDIA_ROOT, document.file_path)
        pdf_document = fitz.open(pdf_path)
    except fitz.FileDataError:
        logger.exception("extract_text_from_pdf: Corrupted PDF for document %s", document_id)
        _fail_extract(processing_task, document, "PDF file is corrupted or unreadable")
        return ""
    except Exception:
        logger.exception("extract_text_from_pdf: Failed to open PDF for document %s", document_id)
        error_msg = str(traceback.format_exc())
        if "password" in error_msg.lower():
            _fail_extract(processing_task, document, "PDF is password-protected")
        else:
            _fail_extract(processing_task, document, error_msg)
        return ""

    num_pages = pdf_document.page_count
    if num_pages == 0:
        logger.info("extract_text_from_pdf: Document %s has 0 pages — returning empty string", document_id)
        pdf_document.close()
        document.extracted_text_length = 0
        document.processing_status = "completed"
        document.save(update_fields=["extracted_text_length", "processing_status"])
        processing_task.status = "completed"
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "completed_at"])
        return ""

    # Extract text page-by-page with markers.
    page_texts: list[str] = []
    for page_num in range(num_pages):
        page = pdf_document.load_page(page_num)
        page_text = page.get_text()
        page_texts.append(f"[PAGE {page_num + 1}]\n{page_text}")

    pdf_document.close()

    extracted_text = "\n".join(page_texts)

    # Update document metadata and mark as completed at the extraction level.
    document.extracted_text_length = len(extracted_text)
    document.total_pages = num_pages
    document.processing_status = "completed"
    document.save(update_fields=["extracted_text_length", "total_pages", "processing_status"])

    # Mark the ProcessingTask as completed.
    processing_task.status = "completed"
    processing_task.completed_at = timezone.now()
    processing_task.save(update_fields=["status", "completed_at"])

    logger.info(
        "extract_text_from_pdf: Completed extraction for document %s (%d pages, %d chars)",
        document_id,
        num_pages,
        len(extracted_text),
    )

    return extracted_text


def _fail_extract(processing_task: ProcessingTask, document: Document, error_message: str) -> None:
    """Mark both the ProcessingTask and Document as failed."""
    processing_task.status = "failed"
    processing_task.error_message = error_message
    processing_task.completed_at = timezone.now()
    processing_task.save(update_fields=["status", "error_message", "completed_at"])

    document.processing_status = "failed"
    document.processing_error = error_message
    document.save(update_fields=["processing_status", "processing_error"])


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

    This task is designed to be the second link in a Celery chain, receiving
    ``extracted_text`` from :func:`extract_text_from_pdf`.

    Transient database/storage errors are automatically retried up to 3 times
    with exponential backoff.

    Args:
        extracted_text: The full extracted text (with page markers) returned by
            the extraction task.
        document_id: The UUID (as a string) of the :class:`Document`.
    """
    logger.info("chunk_document: Starting chunking for document %s", document_id)

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("chunk_document: Document %s not found", document_id)
        return

    # Create a new ProcessingTask for the chunk step.
    chunk_task = ProcessingTask.objects.create(
        document=document,
        task_type="chunk",
        celery_task_id=self.request.id,
        status="running",
        started_at=timezone.now(),
    )

    # Handle empty text.
    if not extracted_text or not extracted_text.strip():
        logger.info("chunk_document: Document %s has no extracted text — skipping chunking", document_id)
        document.total_chunks = 0

        # Bug #2 fix: Don't overwrite processing_status if extraction already failed.
        # If the document is already in a "failed" state (e.g., corrupted PDF),
        # preserve that status rather than overwriting it to "completed".
        if document.processing_status != "failed":
            document.processing_status = "completed"
            document.save(update_fields=["total_chunks", "processing_status"])
        else:
            document.save(update_fields=["total_chunks"])

        chunk_task.status = "completed"
        chunk_task.completed_at = timezone.now()
        chunk_task.save(update_fields=["status", "completed_at"])
        return

    try:
        chunking_service = ChunkingService()
        chunk_results = chunking_service.chunk_text(
            extracted_text,
            chunk_size=1000,
            overlap=200,
        )

        # Build DocumentChunk instances.
        chunks_to_create = [
            DocumentChunk(
                document=document,
                chunk_index=i,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                content=chunk.content,
                token_count=chunk.token_count,
                metadata=chunk.metadata,
            )
            for i, chunk in enumerate(chunk_results)
        ]

        with transaction.atomic():
            DocumentChunk.objects.bulk_create(chunks_to_create)

        # Update document metadata.
        document.total_chunks = len(chunks_to_create)

        # Bug #2 fix: Don't overwrite processing_status if extraction already failed.
        if document.processing_status != "failed":
            document.processing_status = "completed"
            document.save(update_fields=["total_chunks", "processing_status"])
        else:
            document.save(update_fields=["total_chunks"])

        # Mark the chunk ProcessingTask as completed.
        chunk_task.status = "completed"
        chunk_task.completed_at = timezone.now()
        chunk_task.save(update_fields=["status", "completed_at"])

        logger.info(
            "chunk_document: Completed chunking for document %s (%d chunks created)",
            document_id,
            len(chunks_to_create),
        )

    except Exception:
        logger.exception("chunk_document: Failed to chunk document %s", document_id)
        error_message = traceback.format_exc()

        # Update the chunk task as failed.
        chunk_task.status = "failed"
        chunk_task.error_message = error_message
        chunk_task.completed_at = timezone.now()
        chunk_task.save(update_fields=["status", "error_message", "completed_at"])

        document.processing_status = "failed"
        document.processing_error = error_message
        document.save(update_fields=["processing_status", "processing_error"])


# ---------------------------------------------------------------------------
# Subtask 4c — Orchestration (Celery chain)
# ---------------------------------------------------------------------------
# NOTE: This is a regular Python function, NOT a Celery task.
# It is called directly from the API view to avoid the deadlock risk of
# a Celery task submitting more Celery tasks via apply_async().


@shared_task(bind=True)
def _handle_chain_error(self, document_id: str, task_type: str = "extract") -> None:
    """Error callback for the Celery chain.

    When the chain fails (e.g., worker crash, unhandled exception), this task
    is triggered via ``link_error`` to update the ``ProcessingTask`` status
    to ``"failed"`` so it doesn't remain stuck at ``"pending"`` forever.

    Args:
        document_id: The UUID (as a string) of the :class:`Document`.
        task_type: The ``ProcessingTask.task_type`` to mark as failed
            (default ``"extract"``).
    """
    logger.info(
        "_handle_chain_error: Chain failed for document %s — marking %s task as failed",
        document_id,
        task_type,
    )
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("_handle_chain_error: Document %s not found", document_id)
        return

    # Find the most recent pending/running ProcessingTask of the given type.
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

    # Also mark the document as failed if it's not already in a terminal state.
    if document.processing_status not in ("completed", "failed"):
        document.processing_status = "failed"
        document.processing_error = (
            document.processing_error
            or "Chain-level failure: the Celery pipeline encountered an unrecoverable error"
        )
        document.save(update_fields=["processing_status", "processing_error"])


def process_document(document_id: str) -> str | None:
    """Orchestrate the full document processing pipeline via a Celery chain.

    Creates a ``ProcessingTask`` record with ``task_type='extract'`` and
    ``status='pending'``, then builds and executes the chain::

        extract_text_from_pdf → chunk_document

    A ``link_error`` callback is attached to the chain so that chain-level
    failures (e.g. worker crash) are caught and the ``ProcessingTask`` status
    is updated to ``"failed"`` rather than remaining stuck at ``"pending"``.

    This is a **regular Python function** (not a Celery task). It is called
    directly from the API view.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to process.

    Returns:
        The Celery task ID of the chain, or ``None`` if the document is already
        being processed or does not exist.
    """
    logger.info("process_document: Starting orchestration for document %s", document_id)

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("process_document: Document %s not found", document_id)
        return None

    # Prevent duplicate processing.
    if document.processing_status in ("processing", "completed"):
        logger.warning(
            "process_document: Document %s is already being processed or completed — skipping",
            document_id,
        )
        return None

    # Create the initial ProcessingTask record.
    processing_task = ProcessingTask.objects.create(
        document=document,
        task_type="extract",
        status="pending",
    )

    # Build the Celery chain with a link_error callback.
    # The chain passes the return value of extract_text_from_pdf (extracted text)
    # as the first positional argument to chunk_document.
    chain_obj = chain(
        extract_text_from_pdf.s(document_id),
        chunk_document.s(document_id),
    )

    # Attach a link_error callback so chain-level failures are caught.
    error_callback = _handle_chain_error.s(document_id, task_type="extract")

    # Execute the chain with the error callback.
    result = chain_obj.apply_async(link_error=[error_callback])

    # Update the ProcessingTask with the Celery task ID.
    processing_task.celery_task_id = result.id
    processing_task.save(update_fields=["celery_task_id"])

    logger.info(
        "process_document: Chain submitted for document %s (celery_task_id=%s)",
        document_id,
        result.id,
    )

    return result.id
