"""
Embedding service for generating and managing vector embeddings.

Provides functions that delegate to the configured embedding provider
(via :func:`~providers.registry.get_embedding_provider`).
Follows the existing service-layer pattern (standalone functions, not classes).

Functions
---------
- :func:`generate_embedding` — Embed a single text string.
- :func:`embed_query` — Embed a search query string.
- :func:`batch_generate_embeddings` — Embed a list of texts, handling sub-batching.
- :func:`generate_embeddings_for_document` — Embed all un-embedded chunks for a document.
- :func:`batch_embed_chunks` — Embed a specific set of chunks by ID.
- :func:`reembed_chunk` — Replace the embedding on a single chunk.
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from documents.models import Document, DocumentChunk
from providers.registry import get_embedding_provider
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUB_BATCH_SIZE: int = 100
"""Maximum number of texts to send in a single provider API call."""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for a single text string.

    Delegates to the configured :class:`~providers.base.BaseEmbeddingProvider`.

    Args:
        text: The text to embed.

    Returns:
        A list of floats, or ``None`` if the text is empty or an API
        error occurs.
    """
    if not text or not text.strip():
        return None
    provider = get_embedding_provider()
    return provider.embed(text)


def embed_query(text: str) -> list[float]:
    """Convert a search query string into an embedding vector.

    Delegates to the configured :class:`~providers.base.BaseEmbeddingProvider`.

    Args:
        text: The search query text (must be non-empty).

    Returns:
        A list of floats representing the query embedding.

    Raises:
        ValueError: If *text* is empty or whitespace-only.
        EmbeddingError: If the provider API call fails.
    """
    if not text or not text.strip():
        raise ValueError("text must be non-empty")
    provider = get_embedding_provider()
    try:
        return provider.embed_query(text)
    except Exception as e:
        logger.exception("embed_query failed for text: %s...", text[:50])
        raise EmbeddingError(f"Failed to embed query: {e}") from e


def batch_generate_embeddings(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for a list of texts, handling sub-batching.

    Delegates to the configured :class:`~providers.base.BaseEmbeddingProvider`.
    Results are returned in the same order as the input list.  Items that fail
    (empty text, API error) get ``None`` at the corresponding position.

    Args:
        texts: The list of texts to embed.

    Returns:
        A list of the same length as *texts*, where each element is either a
        list of floats or ``None``.
    """
    provider = get_embedding_provider()
    return provider.embed_batch(texts)


def generate_embeddings_for_document(document_id: str) -> None:
    """Generate embeddings for all un-embedded chunks of a document.

    Creates or finds a ``ProcessingTask`` with ``task_type='embed'`` and
    updates its progress as chunks are processed in batches of 100.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to
            process.
    """
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error(
            "generate_embeddings_for_document: Document %s not found",
            document_id,
        )
        return

    # Find or create a ProcessingTask for this embed operation.
    processing_task, _created = ProcessingTask.objects.get_or_create(
        document=document,
        task_type="embed",
        defaults={"status": "pending"},
    )

    processing_task.status = "running"
    processing_task.started_at = timezone.now()
    processing_task.save(update_fields=["status", "started_at"])

    logger.info(
        "generate_embeddings_for_document: Starting embedding for document %s",
        document_id,
    )

    # Query un-embedded chunks, ordered by chunk_index.
    chunks = list(
        DocumentChunk.objects.filter(
            document=document,
            embedding__isnull=True,
        ).order_by("chunk_index")
    )

    total_count = len(chunks)

    if total_count == 0:
        logger.info(
            "generate_embeddings_for_document: No un-embedded chunks for "
            "document %s",
            document_id,
        )
        processing_task.status = "completed"
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save(
            update_fields=["status", "progress", "completed_at"],
        )
        return

    processed_count = 0
    batch_number = 0

    try:
        for batch_start in range(0, total_count, SUB_BATCH_SIZE):
            batch_number += 1
            batch = chunks[batch_start : batch_start + SUB_BATCH_SIZE]

            texts = [chunk.content for chunk in batch]
            embeddings = batch_generate_embeddings(texts)

            for chunk, embedding in zip(batch, embeddings):
                if embedding is not None:
                    chunk.embedding = embedding
                    chunk.save(update_fields=["embedding"])
                    processed_count += 1

            progress = int(processed_count / total_count * 100)
            processing_task.progress = progress
            processing_task.save(update_fields=["progress"])

            logger.info(
                "generate_embeddings_for_document: Batch %d/%d complete "
                "for document %s (progress=%d%%)",
                batch_number,
                (total_count + SUB_BATCH_SIZE - 1) // SUB_BATCH_SIZE,
                document_id,
                progress,
            )

        processing_task.status = "completed"
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save(
            update_fields=["status", "progress", "completed_at"],
        )

        logger.info(
            "generate_embeddings_for_document: Completed embedding for "
            "document %s (total_chunks=%d, embedded=%d)",
            document_id,
            total_count,
            processed_count,
        )

    except Exception as e:
        error_message = f"Embedding failed: {e}"
        logger.exception(
            "generate_embeddings_for_document: %s",
            error_message,
        )
        processing_task.status = "failed"
        processing_task.error_message = error_message
        processing_task.save(update_fields=["status", "error_message"])


def batch_embed_chunks(chunk_ids: list[str]) -> dict[str, Any]:
    """Generate embeddings for a specific set of chunks by their IDs.

    Chunks that already have an embedding are skipped.  Returns a summary
    dict with counts of processed, skipped, and failed chunks.

    Args:
        chunk_ids: A list of chunk UUIDs (as strings).

    Returns:
        A dict with keys ``processed``, ``skipped``, and ``failed``.
    """
    chunks = DocumentChunk.objects.filter(id__in=chunk_ids)

    needs_embedding: list[DocumentChunk] = []
    skipped = 0

    for chunk in chunks:
        if chunk.embedding is not None:
            skipped += 1
        else:
            needs_embedding.append(chunk)

    if not needs_embedding:
        return {"processed": 0, "skipped": skipped, "failed": 0}

    texts = [chunk.content for chunk in needs_embedding]
    embeddings = batch_generate_embeddings(texts)

    processed = 0
    failed = 0

    for chunk, embedding in zip(needs_embedding, embeddings):
        if embedding is not None:
            chunk.embedding = embedding
            chunk.save(update_fields=["embedding"])
            processed += 1
        else:
            failed += 1

    return {"processed": processed, "skipped": skipped, "failed": failed}


def reembed_chunk(chunk_id: str) -> dict[str, Any]:
    """Replace the embedding on a single chunk by generating a new one.

    Args:
        chunk_id: The UUID (as a string) of the :class:`DocumentChunk` to
            re-embed.

    Returns:
        A dict with ``chunk_id`` and ``embedding_updated``.  On failure an
        ``error`` key is also included.  If the chunk is not found, returns
        ``{"error": "not_found", "message": "Chunk not found"}``.
    """
    try:
        chunk = DocumentChunk.objects.get(id=chunk_id)
    except DocumentChunk.DoesNotExist:
        return {"error": "not_found", "message": "Chunk not found"}

    embedding = generate_embedding(chunk.content)

    if embedding is not None:
        chunk.embedding = embedding
        chunk.save(update_fields=["embedding"])
        return {"chunk_id": str(chunk.id), "embedding_updated": True}

    return {
        "chunk_id": str(chunk.id),
        "embedding_updated": False,
        "error": "Failed to generate embedding",
    }
