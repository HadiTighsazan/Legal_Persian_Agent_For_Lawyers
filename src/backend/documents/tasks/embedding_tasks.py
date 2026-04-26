"""
Celery task for generating document chunk embeddings.

Provides a single Celery task:
- ``embed_document`` — Generates embeddings for all un-embedded chunks of a
  document, managing the ``ProcessingTask`` lifecycle directly.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from celery import shared_task
from django.db import IntegrityError, OperationalError
from django.utils import timezone

from documents.models import Document, DocumentChunk
from documents.services.embedding_service import (
    SUB_BATCH_SIZE,
    batch_generate_embeddings,
)
from documents.services.error_handler import log_milestone
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def embed_document(self, document_id: str, task_id: str) -> None:
    """Generate embeddings for all un-embedded chunks of a document.

    This task is dispatched by :class:`~documents.views.DocumentEmbedView`
    and manages the ``ProcessingTask`` lifecycle directly (no delegation to
    :func:`~documents.services.embedding_service.generate_embeddings_for_document`).

    Transient database/network errors are automatically retried up to 3 times
    with exponential backoff.

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
    # Evaluate into a list upfront so slicing works correctly after saves.
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

    # ── Step 4: Process in batches of 50 ──────────────────────────────
    total_batches = (total_count + SUB_BATCH_SIZE - 1) // SUB_BATCH_SIZE
    processed_count = 0

    try:
        for batch_index in range(total_batches):
            batch_start = batch_index * SUB_BATCH_SIZE
            batch_end = min(batch_start + SUB_BATCH_SIZE, total_count)
            batch = chunks[batch_start:batch_end]

            texts = [chunk.content for chunk in batch]

            # Time the API call
            batch_start_time = time.monotonic()
            embeddings = batch_generate_embeddings(texts)
            batch_elapsed = time.monotonic() - batch_start_time

            # Save embeddings
            batch_processed = 0
            for chunk, embedding in zip(batch, embeddings):
                if embedding is not None:
                    chunk.embedding = embedding
                    chunk.save(update_fields=["embedding"])
                    processed_count += 1
                    batch_processed += 1

            # Update progress
            progress = int((batch_index + 1) / total_batches * 100)
            processing_task.progress = progress
            processing_task.save(update_fields=["progress"])

            logger.info(
                "embed_document: Batch %d/%d complete for document %s "
                "(batch_size=%d, processed=%d, elapsed=%.2fs, progress=%d%%)",
                batch_index + 1,
                total_batches,
                document_id,
                len(batch),
                batch_processed,
                batch_elapsed,
                progress,
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
