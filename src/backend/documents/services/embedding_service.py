"""
Embedding service for generating and managing vector embeddings.

Provides functions that wrap OpenAI's ``text-embedding-3-small`` model for
generating embeddings on individual texts, batches, and full documents.
Follows the existing service-layer pattern (standalone functions, not classes).

Functions
---------
- :func:`generate_embedding` — Embed a single text string.
- :func:`batch_generate_embeddings` — Embed a list of texts, handling sub-batching.
- :func:`generate_embeddings_for_document` — Embed all un-embedded chunks for a document.
- :func:`batch_embed_chunks` — Embed a specific set of chunks by ID.
- :func:`reembed_chunk` — Replace the embedding on a single chunk.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
from django.utils import timezone
import openai

from documents.models import Document, DocumentChunk
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL: str = "text-embedding-3-small"
"""The OpenAI embedding model identifier."""

EMBEDDING_DIMENSIONS: int = 1536
"""The number of dimensions returned by ``text-embedding-3-small``."""

SUB_BATCH_SIZE: int = 50
"""Maximum number of texts to send in a single OpenAI API call."""

_MAX_RETRIES: int = 3
"""Number of retry attempts for rate-limited API calls."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_openai_client() -> openai.OpenAI:
    """Return a new :class:`openai.OpenAI` client instance.

    The client is created per-call (not cached globally) to avoid issues
    with Django settings not being fully loaded at import time.
    """
    return openai.OpenAI(api_key=settings.OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for a single text string.

    Args:
        text: The text to embed.

    Returns:
        A list of 1536 floats, or ``None`` if the text is empty or an API
        error occurs.
    """
    if not text or not text.strip():
        return None

    client = _get_openai_client()

    for attempt in range(_MAX_RETRIES):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text,
            )
            embedding: list[float] = response.data[0].embedding
            logger.info(
                "generate_embedding: Generated embedding (dimensions=%d)",
                len(embedding),
            )
            return embedding

        except openai.RateLimitError:
            if attempt < _MAX_RETRIES - 1:
                sleep_time: float = 2.0 ** attempt
                logger.warning(
                    "generate_embedding: Rate limited, retrying in %.0fs "
                    "(attempt %d/%d)",
                    sleep_time,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(sleep_time)
            else:
                logger.error(
                    "generate_embedding: Rate limit exceeded after %d retries",
                    _MAX_RETRIES,
                )
                return None

        except (openai.APIError, openai.APIConnectionError, openai.AuthenticationError) as e:
            logger.error("generate_embedding: API error — %s", e)
            return None

    return None


def batch_generate_embeddings(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for a list of texts, handling sub-batching.

    Splits *texts* into sub-batches of :data:`SUB_BATCH_SIZE` (50) and calls
    the OpenAI API once per sub-batch.  Results are returned in the same order
    as the input list.  Items that fail (empty text, API error) get ``None``
    at the corresponding position.

    Args:
        texts: The list of texts to embed.

    Returns:
        A list of the same length as *texts*, where each element is either a
        list of 1536 floats or ``None``.
    """
    results: list[list[float] | None] = [None] * len(texts)

    client = _get_openai_client()

    for batch_start in range(0, len(texts), SUB_BATCH_SIZE):
        batch_end = min(batch_start + SUB_BATCH_SIZE, len(texts))
        sub_batch = texts[batch_start:batch_end]

        # Pre-fill None for empty texts in this sub-batch.
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(sub_batch):
            idx = batch_start + i
            if not t or not t.strip():
                logger.info(
                    "batch_generate_embeddings: Item %d failed — empty text",
                    idx,
                )
                results[idx] = None
            else:
                valid_indices.append(idx)
                valid_texts.append(t)

        if not valid_texts:
            continue

        # Send the sub-batch to OpenAI with retry logic.
        for attempt in range(_MAX_RETRIES):
            try:
                response = client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=valid_texts,
                )

                # Map results back by index within the sub-batch.
                for resp_idx, data_item in enumerate(response.data):
                    original_idx = valid_indices[resp_idx]
                    results[original_idx] = data_item.embedding

                logger.info(
                    "batch_generate_embeddings: Sub-batch %d–%d complete "
                    "(embeddings=%d)",
                    batch_start,
                    batch_end,
                    len(response.data),
                )
                break  # Success — exit retry loop.

            except openai.RateLimitError:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = 2.0 ** attempt
                    logger.warning(
                        "batch_generate_embeddings: Rate limited, retrying "
                        "in %.0fs (attempt %d/%d)",
                        sleep_time,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "batch_generate_embeddings: Rate limit exceeded "
                        "after %d retries for sub-batch %d–%d",
                        _MAX_RETRIES,
                        batch_start,
                        batch_end,
                    )
                    # All items in this sub-batch remain None.

            except (openai.APIError, openai.APIConnectionError, openai.AuthenticationError) as e:
                logger.error(
                    "batch_generate_embeddings: API error for sub-batch "
                    "%d–%d — %s",
                    batch_start,
                    batch_end,
                    e,
                )
                break  # No retry for non-rate-limit errors.

    return results


def generate_embeddings_for_document(document_id: str) -> None:
    """Generate embeddings for all un-embedded chunks of a document.

    Creates or finds a ``ProcessingTask`` with ``task_type='embed'`` and
    updates its progress as chunks are processed in batches of 50.

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
    # Evaluate into a list upfront so that slicing still works correctly
    # after embeddings are saved (avoiding queryset re-evaluation).
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
