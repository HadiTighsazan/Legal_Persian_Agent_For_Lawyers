"""
Celery tasks for the document processing pipeline.

Provides two Celery tasks:
- ``extract_text_from_pdf`` — opens a PDF with PyMuPDF, extracts text page-by-page,
  and inserts ``[PAGE N]`` markers.
- ``chunk_document`` — receives the extracted text, delegates to
  :class:`~documents.services.chunking_service.ChunkingService`, and persists the
  resulting chunks via bulk create.

The orchestration function ``process_document`` has been moved to
:mod:`documents.services.processing_service` — it is a **regular Python function**
(not a Celery task) called directly from the API view. It is re-exported from
:mod:`documents.tasks` for backward compatibility.
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
from documents.services.error_handler import (
    _has_pdf_magic_bytes,
    classify_pdf_error,
    fail_processing_task,
    log_milestone,
)
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
    log_milestone(logger, document_id, "Starting extraction")

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("extract_text_from_pdf: Document %s not found", document_id)
        return ""

    # Find the pending ProcessingTask created by process_document().
    # We use a targeted lookup (document + task_type + status="pending")
    # rather than a generic filter().first() to avoid picking up stale
    # tasks from previous processing attempts.
    processing_task = ProcessingTask.objects.filter(
        document=document,
        task_type="extract",
        status="pending",
    ).order_by("-created_at").first()

    if processing_task is None:
        # Fallback: create if not found (shouldn't happen in normal flow).
        processing_task = ProcessingTask.objects.create(
            document=document,
            task_type="extract",
            celery_task_id=self.request.id,
            status="running",
            started_at=timezone.now(),
        )
    else:
        # Update the existing task with runtime metadata.
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

        # Check PDF magic bytes before attempting to open.
        if not _has_pdf_magic_bytes(pdf_path):
            fail_processing_task(
                processing_task, document, "File is not a valid PDF", logger,
            )
            return ""

        pdf_document = fitz.open(pdf_path)
    except fitz.FileDataError as e:
        error_msg = classify_pdf_error(e, pdf_path)
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""
    except Exception as e:
        error_msg = classify_pdf_error(e, pdf_path)
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""

    num_pages = pdf_document.page_count
    if num_pages == 0:
        logger.info("extract_text_from_pdf: Document %s has 0 pages — returning empty string", document_id)
        pdf_document.close()
        document.extracted_text_length = 0
        # NOTE: processing_status is NOT set to "completed" here — the chunking
        # task (chunk_document) will handle the empty text and set the final
        # status. This avoids the premature-completion bug (Bug #2).
        document.save(update_fields=["extracted_text_length"])
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

    # Update document metadata (extraction-level fields only).
    # NOTE: processing_status is NOT set to "completed" here — the chunking
    # task (chunk_document) is responsible for setting the final status once
    # the full pipeline finishes. Setting it prematurely would leave the
    # document stuck at "completed" if the worker crashes between extraction
    # and chunking.
    document.extracted_text_length = len(extracted_text)
    document.total_pages = num_pages
    document.save(update_fields=["extracted_text_length", "total_pages"])

    # Mark the ProcessingTask as completed.
    processing_task.status = "completed"
    processing_task.completed_at = timezone.now()
    processing_task.save(update_fields=["status", "completed_at"])

    log_milestone(
        logger, document_id, "Extraction complete",
        pages=num_pages, chars=len(extracted_text),
    )

    return extracted_text


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
    log_milestone(logger, document_id, "Starting chunking")

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

        log_milestone(
            logger, document_id, "Chunking complete",
            chunks=len(chunks_to_create),
        )
        log_milestone(logger, document_id, "Pipeline complete")

    except Exception:
        error_message = traceback.format_exc()
        fail_processing_task(chunk_task, document, error_message, logger)


# ---------------------------------------------------------------------------
# Subtask 4c — Orchestration (Celery chain)
# ---------------------------------------------------------------------------
# NOTE: The process_document function has been moved to
# documents.services.processing_service to reflect that it is a regular
# Python function, not a Celery task. It is re-exported from
# documents.tasks for backward compatibility.


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
    log_milestone(
        logger, document_id,
        "Chain failed — marking %s task as failed" % task_type,
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


# ---------------------------------------------------------------------------
# Subtask 4d — Embed document chunks
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def embed_document(self, document_id: str, processing_task_id: str) -> None:
    """Generate embeddings for all un-embedded chunks of a document.

    This task is dispatched by :class:`~documents.views.DocumentEmbedView`
    and delegates to :func:`~documents.services.embedding_service.generate_embeddings_for_document`.

    Transient database/storage errors are automatically retried up to 3 times
    with exponential backoff.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to process.
        processing_task_id: The UUID (as a string) of the
            :class:`~tasks.models.ProcessingTask` tracking this embed operation.
    """
    log_milestone(logger, document_id, "Starting embedding")

    try:
        processing_task = ProcessingTask.objects.get(id=processing_task_id)
    except ProcessingTask.DoesNotExist:
        logger.error(
            "embed_document: ProcessingTask %s not found for document %s",
            processing_task_id,
            document_id,
        )
        return

    # Update the ProcessingTask with the Celery task ID and mark as running.
    processing_task.celery_task_id = self.request.id
    processing_task.status = "running"
    processing_task.started_at = timezone.now()
    processing_task.save(update_fields=["celery_task_id", "status", "started_at"])

    # Delegate to the embedding service.
    # generate_embeddings_for_document handles its own ProcessingTask management
    # internally via get_or_create. Since we already created the ProcessingTask
    # in the view, the service function will find it and use it.
    generate_embeddings_for_document(document_id)
