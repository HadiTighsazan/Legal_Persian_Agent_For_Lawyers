"""
Search service for semantic similarity search over document chunks.

Provides a pure service function :func:`search_chunks` that performs cosine
similarity search against :class:`~documents.models.DocumentChunk` embeddings
using pgvector's ``CosineDistance`` annotation.  This function has **no HTTP
dependency** — it accepts a ``document_id``, ``query_vector``, ``top_k``, and
``min_score``, and returns a ``list[dict]`` of ranked results.

Functions
---------
- :func:`search_chunks` — Search document chunks by cosine similarity.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models import F, Value
from pgvector.django import CosineDistance

from documents.models import DocumentChunk

logger = logging.getLogger(__name__)


def search_chunks(
    document_id: str,
    query_vector: list[float],
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Search document chunks by cosine similarity to a query vector.

    Uses pgvector's ``CosineDistance`` to compute the cosine distance between
    each chunk's embedding and the *query_vector*, then converts it to a
    relevance score (``1 - distance``).  Results are filtered by
    *min_score*, ordered by relevance descending, and limited to *top_k*.

    Args:
        document_id:
            UUID of the :class:`~documents.models.Document` to search within.
        query_vector:
            768-dim embedding vector for the query.
        top_k:
            Maximum number of results to return (default 10).
        min_score:
            Minimum relevance score threshold (default 0.0).  Only chunks
            with ``relevance_score >= min_score`` are returned.

    Returns:
        A list of dicts ordered by ``relevance_score`` descending.
        Each dict has the following keys:

        - **chunk_id** (*str*) — Stringified UUID of the chunk.
        - **chunk_index** (*int*) — Index of the chunk within the document.
        - **page_start** (*int*) — Starting page number.
        - **page_end** (*int*) — Ending page number.
        - **content** (*str*) — Text content of the chunk.
        - **relevance_score** (*float*) — Cosine similarity (``1 - distance``).
        - **token_count** (*int* or *None*) — Token count of the chunk.
        - **metadata** (*dict*) — Arbitrary metadata stored on the chunk.
    """
    # Build the base queryset: only chunks with embeddings.
    queryset = DocumentChunk.objects.filter(
        document_id=document_id,
        embedding__isnull=False,
    )

    # Annotate with cosine distance from pgvector.
    queryset = queryset.annotate(
        distance=CosineDistance("embedding", query_vector),
    )

    # Compute relevance score: 1 - distance (cosine distance → similarity).
    queryset = queryset.annotate(
        relevance_score=Value(1.0) - F("distance"),
    )

    # Filter by minimum relevance score.
    queryset = queryset.filter(relevance_score__gte=min_score)

    # Order by distance ascending (most similar first).
    queryset = queryset.order_by("distance")

    # Limit to top_k.
    chunks = queryset[:top_k]

    # Build the result list.
    results: list[dict[str, Any]] = []
    for chunk in chunks:
        results.append(
            {
                "chunk_id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "content": chunk.content,
                "relevance_score": float(chunk.relevance_score),
                "token_count": chunk.token_count,
                "metadata": chunk.metadata,
            }
        )

    logger.info(
        "search_chunks: document=%s top_k=%d min_score=%.2f → %d results",
        document_id,
        top_k,
        min_score,
        len(results),
    )

    return results
