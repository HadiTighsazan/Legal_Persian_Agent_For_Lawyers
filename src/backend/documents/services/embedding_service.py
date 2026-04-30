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
- :func:`_process_chunk_batch` — Shared helper for batch-processing chunks.
- :func:`batch_embed_chunks` — Embed a specific set of chunks by ID.
- :func:`reembed_chunk` — Replace the embedding on a single chunk.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from documents.models import DocumentChunk
from providers.base import EMBEDDING_SUB_BATCH_SIZE as SUB_BATCH_SIZE
from providers.registry import get_embedding_provider

logger = logging.getLogger(__name__)


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


def _process_chunk_batch(
    chunks: list[DocumentChunk],
    progress_callback: Callable[[int], None] | None = None,
) -> int:
    """Shared helper: generate embeddings for a list of chunks and save them.

    Args:
        chunks: List of DocumentChunk instances (must have content).
        progress_callback: Optional callback receiving processed_count after
            each batch.

    Returns:
        Number of chunks successfully embedded.
    """
    total = len(chunks)
    processed = 0

    for batch_start in range(0, total, SUB_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + SUB_BATCH_SIZE]
        texts = [chunk.content for chunk in batch]
        embeddings = batch_generate_embeddings(texts)

        updated_chunks = []
        for chunk, embedding in zip(batch, embeddings):
            if embedding is not None:
                chunk.embedding = embedding
                updated_chunks.append(chunk)
                processed += 1

        if updated_chunks:
            DocumentChunk.objects.bulk_update(updated_chunks, ["embedding"])

        if progress_callback:
            progress_callback(processed)

    return processed


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
        A dict with ``chunk_id`` and ``embedding_updated``.

    Raises:
        EmbeddingError: If the chunk is not found or embedding generation
            fails.
    """
    try:
        chunk = DocumentChunk.objects.get(id=chunk_id)
    except DocumentChunk.DoesNotExist:
        raise EmbeddingError(f"Chunk {chunk_id} not found")

    embedding = generate_embedding(chunk.content)
    if embedding is None:
        raise EmbeddingError(f"Failed to generate embedding for chunk {chunk_id}")

    chunk.embedding = embedding
    chunk.save(update_fields=["embedding"])
    return {"chunk_id": str(chunk.id), "embedding_updated": True}
