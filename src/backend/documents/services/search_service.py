"""
Search service for hybrid (vector + keyword) search over document chunks.

Provides three search modes:

1. **Vector search** (``search_mode="vector"``) — Cosine similarity via
   pgvector's ``CosineDistance``.  This is the original behavior, preserved
   for backward compatibility.

2. **Keyword search** (``search_mode="keyword"``) — PostgreSQL Full-Text Search
   using the ``simple`` configuration on the ``search_vector`` column, which
   is auto-populated by a DB trigger on INSERT/UPDATE of ``content``.

3. **Hybrid search** (``search_mode="hybrid"``) — Runs both vector and keyword
   searches independently, then fuses the results using **Reciprocal Rank
   Fusion (RRF)**.

All modes support optional **metadata filtering** via the ``filters`` parameter,
which applies WHERE clauses on denormalized columns (``law_name``,
``legal_status``, ``approval_date``, ``legal_type``).

Functions
---------
- :func:`search_chunks` — Original vector-only search (backward compatible).
- :func:`hybrid_search` — Full hybrid search with RRF fusion.
- :func:`keyword_search` — PostgreSQL FTS keyword search.
- :func:`_vector_search` — Internal vector search (shared by ``search_chunks``
  and ``hybrid_search``).
- :func:`_rrf_fusion` — Reciprocal Rank Fusion algorithm.
- :func:`_apply_metadata_filters` — Apply metadata filter conditions.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import connection
from django.db.models import F, Q, Value
from django.db.models.query import QuerySet
from pgvector.django import CosineDistance

from documents.models import DocumentChunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# RRF constant (k) — prevents division by zero and controls score inflation.
# Standard value of 60 is used per the RRF literature.
_RRF_K: int = 60

# Default RRF depth: each retrieval method fetches max(top_k * 3, 60) results
# to ensure sufficient candidates for fusion.
_RRF_DEPTH_MULTIPLIER: int = 3
_RRF_MIN_DEPTH: int = 60

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _set_probes(probes: int | None = None) -> None:
    """Set ivfflat.probes for the current database session.

    This controls how many inverted lists are searched during an ivfflat
    index scan.  Higher values improve recall at the cost of speed.
    Failures are logged as warnings since this is a performance optimization.

    Args:
        probes: Number of probes (1-100).  Falls back to
            ``settings.VECTOR_SEARCH_PROBES`` if ``None``.
    """
    probes = probes if probes is not None else settings.VECTOR_SEARCH_PROBES
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET ivfflat.probes = %s", [probes])
    except Exception as e:
        logger.warning(
            "Failed to set ivfflat.probes=%d: %s. "
            "Search performance may be affected.",
            probes,
            e,
        )


# ---------------------------------------------------------------------------
# Metadata filtering
# ---------------------------------------------------------------------------


def _apply_metadata_filters(
    queryset: QuerySet,
    filters: dict[str, Any] | None,
) -> QuerySet:
    """Apply metadata filter conditions to a queryset.

    Supports filtering on denormalized columns:
    - ``law_name`` (exact match, case-insensitive)
    - ``legal_status`` (exact match)
    - ``approval_date`` (exact date or ``__gte``/``__lte`` suffixes)
    - ``legal_type`` (exact match)

    Args:
        queryset: The base queryset to filter.
        filters: A dict of filter conditions.  Keys are column names with
            optional Django field lookup suffixes (e.g., ``approval_date__gte``).
            Values are the filter values.

    Returns:
        The filtered queryset.
    """
    if not filters:
        return queryset

    valid_fields = {"law_name", "legal_status", "approval_date", "legal_type"}
    filter_kwargs: dict[str, Any] = {}

    for key, value in filters.items():
        # Extract the base field name (strip Django lookup suffixes like __gte)
        base_field = key.split("__")[0]
        if base_field in valid_fields:
            filter_kwargs[key] = value
        else:
            logger.warning(
                "Ignoring unknown filter field '%s'. "
                "Valid fields: %s",
                key,
                sorted(valid_fields),
            )

    if filter_kwargs:
        queryset = queryset.filter(**filter_kwargs)

    return queryset


# ---------------------------------------------------------------------------
# Result builders
# ---------------------------------------------------------------------------


def _build_result_dict(chunk: DocumentChunk, score: float) -> dict[str, Any]:
    """Build a standardised result dict from a chunk and a score.

    Args:
        chunk: A ``DocumentChunk`` instance (may have annotations).
        score: The relevance score for this result.

    Returns:
        A dict with the standard result schema.
    """
    return {
        "chunk_id": str(chunk.id),
        "chunk_index": chunk.chunk_index,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "content": chunk.content,
        "relevance_score": score,
        "token_count": chunk.token_count,
        "metadata": chunk.metadata,
        "legal_context": chunk.legal_context,
    }


# ---------------------------------------------------------------------------
# RRF Fusion
# ---------------------------------------------------------------------------


def _rrf_fusion(
    vector_results: list[dict[str, Any]],
    keyword_results: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Fuse two ranked result lists using Reciprocal Rank Fusion (RRF).

    RRF computes a combined score for each chunk as::

        score(chunk) = Σ 1 / (k + rank(chunk))

    where *rank* is the 1-based position in each result list, and *k* is the
    RRF constant (default 60).  Chunks appearing in only one list receive a
    contribution of ``1 / (k + rank)`` from that list and 0 from the other.

    Args:
        vector_results: Ranked results from vector search (highest score first).
        keyword_results: Ranked results from keyword search (highest score first).
        top_k: Maximum number of fused results to return.

    Returns:
        A list of up to *top_k* result dicts, fused and re-ranked by RRF score
        descending.  Each dict includes the additional keys:

        - **vector_score** (*float*) — Original vector relevance score.
        - **keyword_score** (*float*) — Original keyword search rank score.
        - **rrf_score** (*float*) — The fused RRF score.
    """
    # Build lookup: chunk_id -> (rank, result_dict)
    rrf_scores: dict[str, float] = {}
    result_map: dict[str, dict[str, Any]] = {}

    for rank, result in enumerate(vector_results, start=1):
        cid = result["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
        result_map[cid] = result
        result_map[cid]["vector_score"] = result["relevance_score"]
        result_map[cid]["keyword_score"] = 0.0

    for rank, result in enumerate(keyword_results, start=1):
        cid = result["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
        if cid in result_map:
            result_map[cid]["keyword_score"] = result["relevance_score"]
        else:
            result_map[cid] = result
            result_map[cid]["vector_score"] = 0.0
            result_map[cid]["keyword_score"] = result["relevance_score"]

    # Sort by RRF score descending and limit to top_k.
    sorted_chunk_ids = sorted(
        rrf_scores.keys(),
        key=lambda cid: rrf_scores[cid],
        reverse=True,
    )[:top_k]

    fused_results: list[dict[str, Any]] = []
    for cid in sorted_chunk_ids:
        result = result_map[cid]
        result["rrf_score"] = round(rrf_scores[cid], 6)
        # Overwrite relevance_score with the RRF score for the final output.
        result["relevance_score"] = round(rrf_scores[cid], 6)
        fused_results.append(result)

    return fused_results


# ---------------------------------------------------------------------------
# Vector search (internal)
# ---------------------------------------------------------------------------


def _vector_search(
    document_id: str,
    query_vector: list[float],
    top_k: int,
    min_score: float = 0.0,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Internal vector search — shared by :func:`search_chunks` and
    :func:`hybrid_search`.

    Args:
        document_id: UUID of the document to search within.
        query_vector: 768-dim embedding vector for the query.
        top_k: Maximum number of results to return.
        min_score: Minimum relevance score threshold.
        filters: Optional metadata filter conditions.

    Returns:
        A list of result dicts ordered by relevance descending.
    """
    _set_probes()

    # Validate query vector dimension.
    expected_dim = settings.EMBEDDING_DIMENSION
    if len(query_vector) != expected_dim:
        raise ValueError(
            f"query_vector dimension {len(query_vector)} does not match "
            f"expected dimension {expected_dim}. "
            f"Check EMBEDDING_DIMENSION setting."
        )

    # Build the base queryset: only chunks with embeddings.
    queryset = DocumentChunk.objects.filter(
        document_id=document_id,
        embedding__isnull=False,
    )

    # Apply metadata filters.
    queryset = _apply_metadata_filters(queryset, filters)

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
            _build_result_dict(chunk, float(chunk.relevance_score))
        )

    logger.info(
        "_vector_search: document=%s top_k=%d min_score=%.2f filters=%s → %d results",
        document_id,
        top_k,
        min_score,
        filters,
        len(results),
    )

    return results


# ---------------------------------------------------------------------------
# Keyword search (PostgreSQL Full-Text Search)
# ---------------------------------------------------------------------------


def keyword_search(
    document_id: str,
    query_text: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search document chunks by keyword using PostgreSQL Full-Text Search.

    Uses the ``search_vector`` column (auto-populated by DB trigger) with
    the ``simple`` text search configuration.  The query is parsed as a
    ``websearch`` query, which supports:

    - Plain words: ``"ماده"``
    - Phrase search: ``"ماده ۲۲"``
    - Exclusion: ``"ماده -منسوخ"``

    .. note::

        Persian/Arabic digits in the query should be converted to English
        digits via :meth:`PersianNormalizer.normalize_for_fts` **before**
        calling this function, since the ``search_vector`` was built from
        digit-normalized content.

    Args:
        document_id: UUID of the document to search within.
        query_text: The keyword query string (raw text, will be parsed as
            ``websearch`` query).
        top_k: Maximum number of results to return (default 10).
        filters: Optional metadata filter conditions.

    Returns:
        A list of result dicts ordered by ``relevance_score`` (search rank)
        descending.  Each dict follows the same schema as :func:`search_chunks`.
    """
    if not query_text or not query_text.strip():
        logger.warning(
            "keyword_search: empty query for document %s — returning empty results",
            document_id,
        )
        return []

    # Build the search query using websearch syntax.
    search_query = SearchQuery(query_text, config="simple", search_type="websearch")

    # Build the base queryset: only chunks with a search_vector.
    queryset = DocumentChunk.objects.filter(
        document_id=document_id,
        search_vector__isnull=False,
    )

    # Apply metadata filters.
    queryset = _apply_metadata_filters(queryset, filters)

    # Annotate with search rank.
    queryset = queryset.annotate(
        relevance_score=SearchRank(
            F("search_vector"),
            search_query,
        ),
    )

    # Filter to only chunks that actually matched.
    queryset = queryset.filter(search_vector=search_query)

    # Order by rank descending (most relevant first).
    queryset = queryset.order_by("-relevance_score")

    # Limit to top_k.
    chunks = queryset[:top_k]

    # Build the result list.
    results: list[dict[str, Any]] = []
    for chunk in chunks:
        results.append(
            _build_result_dict(chunk, float(chunk.relevance_score))
        )

    logger.info(
        "keyword_search: document=%s top_k=%d filters=%s → %d results",
        document_id,
        top_k,
        filters,
        len(results),
    )

    return results


# ---------------------------------------------------------------------------
# Hybrid search (vector + keyword with RRF fusion)
# ---------------------------------------------------------------------------


def hybrid_search(
    document_id: str,
    query_vector: list[float],
    query_text: str,
    top_k: int = 10,
    min_score: float = 0.0,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search combining vector similarity and keyword FTS via RRF.

    Runs both :func:`_vector_search` and :func:`keyword_search` independently,
    then fuses the results using :func:`_rrf_fusion`.

    Each retrieval method fetches ``max(top_k * 3, 60)`` candidates (RRF depth)
    to ensure sufficient overlap for meaningful fusion.

    Args:
        document_id: UUID of the document to search within.
        query_vector: 768-dim embedding vector for the query.
        query_text: Raw keyword query text (will be parsed as ``websearch``).
        top_k: Maximum number of fused results to return (default 10).
        min_score: Minimum relevance score threshold for vector search.
        filters: Optional metadata filter conditions.

    Returns:
        A list of up to *top_k* result dicts, fused and re-ranked by RRF score
        descending.  Each dict includes the additional keys:

        - **vector_score** (*float*) — Original vector relevance score.
        - **keyword_score** (*float*) — Original keyword search rank score.
        - **rrf_score** (*float*) — The fused RRF score.
    """
    # Compute RRF depth: each method fetches more candidates than top_k.
    rrf_depth = max(top_k * _RRF_DEPTH_MULTIPLIER, _RRF_MIN_DEPTH)

    # Run vector search.
    vector_results = _vector_search(
        document_id=document_id,
        query_vector=query_vector,
        top_k=rrf_depth,
        min_score=min_score,
        filters=filters,
    )

    # Run keyword search.
    keyword_results = keyword_search(
        document_id=document_id,
        query_text=query_text,
        top_k=rrf_depth,
        filters=filters,
    )

    # Fuse using RRF.
    fused = _rrf_fusion(vector_results, keyword_results, top_k)

    logger.info(
        "hybrid_search: document=%s top_k=%d min_score=%.2f filters=%s "
        "→ vector=%d keyword=%d fused=%d",
        document_id,
        top_k,
        min_score,
        filters,
        len(vector_results),
        len(keyword_results),
        len(fused),
    )

    return fused


# ---------------------------------------------------------------------------
# Original search_chunks (backward compatible)
# ---------------------------------------------------------------------------


def search_chunks(
    document_id: str,
    query_vector: list[float],
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Search document chunks by cosine similarity to a query vector.

    This is the **original** vector-only search function, preserved for
    backward compatibility.  New code should prefer :func:`hybrid_search`.

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
    return _vector_search(
        document_id=document_id,
        query_vector=query_vector,
        top_k=top_k,
        min_score=min_score,
        filters=None,
    )
