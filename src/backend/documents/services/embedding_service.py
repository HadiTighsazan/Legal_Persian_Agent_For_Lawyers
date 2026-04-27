"""
Embedding service for generating and managing vector embeddings.

Provides functions that wrap the Ollama ``nomic-embed-text`` model for
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

import requests
from django.conf import settings
from django.utils import timezone

from documents.models import Document, DocumentChunk
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_MODEL: str = "nomic-embed-text"
"""The Ollama embedding model identifier."""

EMBEDDING_DIMENSIONS: int = 768
"""The number of dimensions returned by ``nomic-embed-text``."""

SUB_BATCH_SIZE: int = 50
"""Maximum number of texts to send in a single Ollama API call."""

_MAX_RETRIES: int = 3
"""Number of retry attempts for failed API calls."""

_TIMEOUT_SECONDS: int = 60
"""HTTP request timeout for Ollama API calls."""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ollama_base_url() -> str:
    """Return the Ollama base URL from Django settings."""
    return settings.OLLAMA_BASE_URL.rstrip("/")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for a single text string.

    Calls ``POST /api/embeddings`` on the Ollama server.

    Args:
        text: The text to embed.

    Returns:
        A list of 768 floats, or ``None`` if the text is empty or an API
        error occurs.
    """
    if not text or not text.strip():
        return None

    base_url = _get_ollama_base_url()
    url = f"{base_url}/api/embeddings"

    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.post(
                url,
                json={"model": EMBEDDING_MODEL, "prompt": text},
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            embedding: list[float] = response.json()["embedding"]
            logger.info(
                "generate_embedding: Generated embedding (dimensions=%d)",
                len(embedding),
            )
            return embedding

        except requests.exceptions.Timeout:
            if attempt < _MAX_RETRIES - 1:
                sleep_time: float = 2.0 ** attempt
                logger.warning(
                    "generate_embedding: Timeout, retrying in %.0fs "
                    "(attempt %d/%d)",
                    sleep_time,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(sleep_time)
            else:
                logger.error(
                    "generate_embedding: Timeout after %d retries",
                    _MAX_RETRIES,
                )
                return None

        except requests.exceptions.RequestException as e:
            if attempt < _MAX_RETRIES - 1:
                sleep_time = 2.0 ** attempt
                logger.warning(
                    "generate_embedding: Request failed (%s), retrying in "
                    "%.0fs (attempt %d/%d)",
                    e,
                    sleep_time,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(sleep_time)
            else:
                logger.error(
                    "generate_embedding: Request failed after %d retries — %s",
                    _MAX_RETRIES,
                    e,
                )
                return None

    return None


def embed_query(text: str) -> list[float]:
    """Convert a search query string into a 768-dim embedding vector.

    Calls ``POST /api/embeddings`` on the Ollama server.  Unlike
    :func:`generate_embedding`, this function **raises** on failure so the
    view layer can return proper error responses.

    Args:
        text: The search query text (must be non-empty).

    Returns:
        A list of 768 floats representing the query embedding.

    Raises:
        EmbeddingError: If the Ollama API call fails or returns invalid data.
        ValueError: If *text* is empty or whitespace-only.
    """
    if not text or not text.strip():
        raise ValueError("text must be non-empty")

    base_url = _get_ollama_base_url()
    url = f"{base_url}/api/embeddings"

    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.post(
                url,
                json={"model": EMBEDDING_MODEL, "prompt": text},
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            embedding: list[float] = response.json()["embedding"]
            logger.info(
                "embed_query: Generated embedding (dimensions=%d)",
                len(embedding),
            )
            return embedding

        except requests.exceptions.Timeout:
            if attempt < _MAX_RETRIES - 1:
                sleep_time: float = 2.0 ** attempt
                logger.warning(
                    "embed_query: Timeout, retrying in %.0fs "
                    "(attempt %d/%d)",
                    sleep_time,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(sleep_time)
            else:
                logger.error(
                    "embed_query: Timeout after %d retries",
                    _MAX_RETRIES,
                )
                raise EmbeddingError("Ollama embedding request timed out after retries")

        except requests.exceptions.RequestException as e:
            if attempt < _MAX_RETRIES - 1:
                sleep_time = 2.0 ** attempt
                logger.warning(
                    "embed_query: Request failed (%s), retrying in "
                    "%.0fs (attempt %d/%d)",
                    e,
                    sleep_time,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(sleep_time)
            else:
                logger.error(
                    "embed_query: Request failed after %d retries — %s",
                    _MAX_RETRIES,
                    e,
                )
                raise EmbeddingError(f"Ollama embedding request failed: {e}")

    raise EmbeddingError("Unexpected error in embed_query")


def batch_generate_embeddings(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for a list of texts, handling sub-batching.

    Uses Ollama's ``/api/embed`` endpoint which accepts multiple inputs in a
    single call.  Splits *texts* into sub-batches of :data:`SUB_BATCH_SIZE`
    (50).  Results are returned in the same order as the input list.  Items
    that fail (empty text, API error) get ``None`` at the corresponding
    position.

    Args:
        texts: The list of texts to embed.

    Returns:
        A list of the same length as *texts*, where each element is either a
        list of 768 floats or ``None``.
    """
    results: list[list[float] | None] = [None] * len(texts)

    base_url = _get_ollama_base_url()
    url = f"{base_url}/api/embed"

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

        # Send the sub-batch to Ollama with retry logic.
        for attempt in range(_MAX_RETRIES):
            try:
                response = requests.post(
                    url,
                    json={"model": EMBEDDING_MODEL, "input": valid_texts},
                    timeout=_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                embeddings: list[list[float]] = data["embeddings"]

                # Map results back by index within the sub-batch.
                for resp_idx, embedding in enumerate(embeddings):
                    original_idx = valid_indices[resp_idx]
                    results[original_idx] = embedding

                logger.info(
                    "batch_generate_embeddings: Sub-batch %d–%d complete "
                    "(embeddings=%d)",
                    batch_start,
                    batch_end,
                    len(embeddings),
                )
                break  # Success — exit retry loop.

            except requests.exceptions.Timeout:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = 2.0 ** attempt
                    logger.warning(
                        "batch_generate_embeddings: Timeout, retrying "
                        "in %.0fs (attempt %d/%d)",
                        sleep_time,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "batch_generate_embeddings: Timeout after %d retries "
                        "for sub-batch %d–%d",
                        _MAX_RETRIES,
                        batch_start,
                        batch_end,
                    )

            except requests.exceptions.RequestException as e:
                if attempt < _MAX_RETRIES - 1:
                    sleep_time = 2.0 ** attempt
                    logger.warning(
                        "batch_generate_embeddings: Request failed (%s), "
                        "retrying in %.0fs (attempt %d/%d)",
                        e,
                        sleep_time,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "batch_generate_embeddings: Request failed after "
                        "%d retries for sub-batch %d–%d — %s",
                        _MAX_RETRIES,
                        batch_start,
                        batch_end,
                        e,
                    )

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
