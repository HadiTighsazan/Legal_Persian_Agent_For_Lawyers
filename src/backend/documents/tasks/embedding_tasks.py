"""
Celery task for generating document chunk embeddings.

Provides a single Celery task:
- ``embed_document`` — Generates embeddings for all un-embedded chunks of a
  document, managing the ``ProcessingTask`` lifecycle directly.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.utils import timezone

from documents.models import Document, DocumentChunk
from documents.services.embedding_service import (
    EmbeddingError,
    _process_chunk_batch,
)
from documents.services.error_handler import log_milestone
from providers.base import EmbeddingBatchError
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def embed_document(self, document_id: str, task_id: str) -> None:
    """Generate embeddings for all un-embedded chunks of a document.

    This task is dispatched by :class:`~documents.views.DocumentEmbedView`
    and manages the ``ProcessingTask`` lifecycle directly.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to process.
        task_id: The UUID (as a string) of the :class:`~tasks.models.ProcessingTask`
            tracking this embed operation.
    """
    log_milestone(logger, document_id, "Starting embedding")

    # ── Step 1: Fetch ProcessingTask ──────────────────────────────────
    try:
        processing_task = ProcessingTask.objects.get(id=task_id)
    except ProcessingTask.DoesNotExist:
        logger.error(
            "embed_document: ProcessingTask %s not found for document %s",
            task_id,
            document_id,
        )
        return

    # ── Step 2: Mark as running ───────────────────────────────────────
    processing_task.celery_task_id = self.request.id
    processing_task.status = "running"
    processing_task.started_at = timezone.now()
    processing_task.save(update_fields=["celery_task_id", "status", "started_at"])

    # ── Step 3: Fetch un-embedded chunks ──────────────────────────────
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("embed_document: Document %s not found", document_id)
        processing_task.status = "failed"
        processing_task.error_message = f"Document {document_id} not found"
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "error_message", "completed_at"])
        return

    chunks = list(
        DocumentChunk.objects.filter(
            document=document,
            embedding__isnull=True,
        ).order_by("chunk_index")
    )

    total_count = len(chunks)

    if total_count == 0:
        logger.info(
            "embed_document: No un-embedded chunks for document %s",
            document_id,
        )
        processing_task.status = "completed"
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "progress", "completed_at"])
        return

    # ── Step 4: Process chunks via shared helper ──────────────────────
    try:
        processed_count = _process_chunk_batch(
            chunks,
            progress_callback=lambda p: _update_progress(processing_task, p, total_count),
        )

        # ── Step 5: Mark as completed ─────────────────────────────────
        processing_task.status = "completed"
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "progress", "completed_at"])

        log_milestone(
            logger,
            document_id,
            "Embedding complete",
            task_id=task_id,
            total_chunks=total_count,
            embedded=processed_count,
        )

    except Exception as e:
        if isinstance(e, EmbeddingBatchError):
            error_message = f"Embedding failed after partial progress: {e}"
        else:
            error_message = f"Embedding failed: {e}"
        
        logger.exception(
            "embed_document: %s (document=%s, task=%s)",
            error_message,
            document_id,
            task_id,
        )
        processing_task.status = "failed"
        processing_task.error_message = error_message
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "error_message", "completed_at"])


def _update_progress(task: ProcessingTask, processed: int, total: int) -> None:
    """Update the ProcessingTask progress based on processed count."""
    progress = int(processed / total * 100) if total > 0 else 100
    task.progress = progress
    task.save(update_fields=["progress"])
