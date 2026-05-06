"""
Search service for hybrid (vector + keyword + trigram) search over document
chunks.

Provides four search modes:

1. **Vector search** (``search_mode="vector"``) — Cosine similarity via
   pgvector's ``CosineDistance``.  This is the original behavior, preserved
   for backward compatibility.

2. **Keyword search** (``search_mode="keyword"``) — PostgreSQL Full-Text Search
   using the ``simple`` configuration on the ``search_vector`` column, which
   is auto-populated by a DB trigger on INSERT/UPDATE of ``content``.

3. **Trigram search** (``search_mode="trigram"``) — PostgreSQL ``pg_trgm``
   trigram similarity search for fuzzy matching.  Catches OCR errors, spelling
   variations, and partial matches that both vector and FTS miss.

4. **Hybrid search** (``search_mode="hybrid"``) — Runs vector, keyword, and
   optionally trigram searches independently, then fuses the results using
   **Reciprocal Rank Fusion (RRF)**.

All modes support optional **metadata filtering** via the ``filters`` parameter,
which applies WHERE clauses on denormalized columns (``law_name``,
``legal_status``, ``approval_date``, ``legal_type``).

Functions
---------
- :func:`search_chunks` — Original vector-only search (backward compatible).
- :func:`hybrid_search` — Full hybrid search with RRF fusion.
- :func:`keyword_search` — PostgreSQL FTS keyword search.
- :func:`trigram_search` — PostgreSQL pg_trgm trigram similarity search.
- :func:`_vector_search` — Internal vector search (shared by ``search_chunks``
  and ``hybrid_search``).
- :func:`_rrf_fusion` — Reciprocal Rank Fusion algorithm (two lists).
- :func:`_rrf_fusion_multi` — Multi-list Reciprocal Rank Fusion (N lists).
- :func:`_apply_metadata_filters` — Apply metadata filter conditions.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import connection
from django.db.models import F, FloatField, Func, Q, Value
from django.db.models.query import QuerySet
from pgvector.django import CosineDistance

from documents.models import DocumentChunk
from documents.services.persian_normalizer import PersianNormalizer

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

# Default minimum trigram similarity threshold (0.0–1.0).
# 0.2 is a good balance for Persian legal text — catches OCR errors and
# spelling variations without too much noise.
_TRIGRAM_MIN_SIMILARITY: float = 0.2

# ---------------------------------------------------------------------------
# Persian stop words — words that should be removed from FTS queries to
# prevent AND-matching failures.  PostgreSQL's ``simple`` FTS config does
# NOT have a Persian stop word dictionary, so common Persian function words
# cause FTS to require ALL tokens to exist in a chunk, which often fails.
# ---------------------------------------------------------------------------

PERSIAN_STOP_WORDS: frozenset[str] = frozenset({
    # Common Persian function words
    "و", "در", "به", "از", "که", "با", "برای", "این", "آن", "را",
    "ها", "های", "می", "هم", "نیز", "اگر", "اما", "ولی", "یا",
    "باید", "شاید", "ممکن", "خواهد", "باشند", "است", "هست", "شد",
    "شود", "شده", "کرد", "کند", "گفت", "دهد", "دارد", "داشت",
    "باشه", "باشید", "باشیم", "باشم", "باشی", "باشند",
    "بود", "بودن", "بوده", "باشد", "هستند", "هستم", "هستی",
    "نمی", "نباید", "نخواهد", "نکرد", "نکند", "نگفت",
    "هر", "چند", "چگونه", "چیست", "چه", "چرا", "کجا", "کی",
    "اینکه", "آنکه", "آنچه", "هرچه", "هرکس", "هرکه",
    "تحت", "طی", "درباره", "دربارۀ", "پیرامون", "مربوط",
    "قبل", "بعد", "بالا", "پایین", "داخل", "خارج", "جلوی",
    "علیه", "ضد", "جز", "غیر", "به جز", "به غیر",
    "خیلی", "بسیار", "کم", "اندکی", "تقریبا", "حدود",
    "البته", "البته که", "قطعا", "مسلما", "حتما",
    "پس", "پس از", "پیش", "پیش از", "کنون", "اکنون",
    "هنوز", "هنوز هم", "همچنان", "همچنین", "همیشه",
    "گاهی", "گاه", "گاهی اوقات", "برخی", "بعضی", "بعضا",
    "سراسر", "تمام", "تمامی", "همه", "همگی",
    "بدون", "بی", "باوجود", "علیرغم",
    "طبق", "براساس", "برپایه", "برمبنای", "برطبق",
    "ضمن", "هنگام", "زمان", "وقتی", "موقع",
    "نظیر", "مانند", "مثل", "همچو", "چو",
    "جز", "جزیی", "جزئی", "به جز",
    "لذا", "بنابراین", "ازاین رو", "ازاینرو",
    "ولی", "اما", "مع هذا", "معذلک",
    "الا", "الا اینکه", "مگر", "مگر اینکه",
    "زیرا", "چون", "چرا که", "به دلیل", "به علت",
    "اگرچه", "هرچند", "با اینکه", "با آنکه",
})
"""Frozen set of Persian stop words removed from FTS queries.

These are common Persian function words (prepositions, conjunctions, pronouns,
auxiliary verbs, adverbs) that carry little semantic meaning but cause
PostgreSQL FTS AND-matching failures when included in ``websearch`` queries.
"""

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
# Stop word removal
# ---------------------------------------------------------------------------


def _remove_stop_words(query: str) -> str:
    """Remove Persian stop words from a query string.

    PostgreSQL's ``simple`` FTS config does **not** have a Persian stop word
    dictionary.  When a ``websearch`` query contains common Persian function
    words (e.g., ``"مجازات در قانون"``), FTS requires ALL tokens to exist in
    a chunk, which often fails because ``"در"`` is a stop word that appears
    in nearly every chunk but is not indexed meaningfully.

    This function removes known Persian stop words from the query before it
    is passed to FTS, preventing AND-matching failures.

    Args:
        query: The raw query string (may contain Persian stop words).

    Returns:
        The query string with stop words removed.  If all words are stop
        words, returns an empty string.
    """
    if not query or not query.strip():
        return query

    tokens = query.split()
    filtered = [t for t in tokens if t not in PERSIAN_STOP_WORDS]
    return " ".join(filtered)


# ---------------------------------------------------------------------------
# Keyword search (PostgreSQL Full-Text Search)
# ---------------------------------------------------------------------------


def keyword_search(
    document_id: str,
    query_text: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
    enable_trigram_fallback: bool = True,
) -> list[dict[str, Any]]:
    """Search document chunks by keyword using PostgreSQL Full-Text Search.

    Uses the ``search_vector`` column (auto-populated by DB trigger) with
    the ``simple`` text search configuration.  The query is parsed as a
    ``websearch`` query, which supports:

    - Plain words: ``"ماده"``
    - Phrase search: ``"ماده ۲۲"``
    - Exclusion: ``"ماده -منسوخ"``

    **Safety net:** Before building the ``SearchQuery``, this function
    applies two normalisation steps:

    1. :meth:`PersianNormalizer.normalize_for_fts` — converts Arabic→Persian
       chars, Persian/Arabic digits→English digits, and ZWNJ→space.  This
       ensures that even if the caller (e.g., LLM query formulation) fails
       to normalise digits, FTS will still match.
    2. :meth:`_remove_stop_words` — removes common Persian stop words that
       cause AND-matching failures in PostgreSQL's ``simple`` FTS config.

    **Trigram fallback:** When ``enable_trigram_fallback=True`` (default) and
    FTS returns zero results, this function automatically falls back to
    :func:`trigram_search` with a lower similarity threshold (0.1).  This
    catches cases where character encoding issues (Arabic Presentation Forms
    in PDF-extracted text) prevent exact FTS matching, even after NFKC
    normalization.

    Args:
        document_id: UUID of the document to search within.
        query_text: The keyword query string (raw text, will be parsed as
            ``websearch`` query).
        top_k: Maximum number of results to return (default 10).
        filters: Optional metadata filter conditions.
        enable_trigram_fallback: Whether to fall back to trigram search when
            FTS returns zero results (default ``True``).

    Returns:
        A list of result dicts ordered by ``relevance_score`` (search rank
        or trigram similarity) descending.  Each dict follows the same schema
        as :func:`search_chunks`.
    """
    if not query_text or not query_text.strip():
        logger.warning(
            "keyword_search: empty query for document %s — returning empty results",
            document_id,
        )
        return []

    # ---- Safety net: normalise query text for FTS ----
    # Step 1: Normalise Persian chars, digits, and ZWNJ for FTS compatibility.
    # This is idempotent — safe to apply even if already normalised.
    _original_query = query_text
    query_text = PersianNormalizer.normalize_for_fts(query_text)

    # Step 2: Remove Persian stop words that cause FTS AND-matching failures.
    query_text = _remove_stop_words(query_text)

    logger.info(
        "keyword_search: document=%s original_query=%.300s "
        "after_normalize_for_fts=%.300s after_stop_word_removal=%.300s",
        document_id,
        _original_query,
        PersianNormalizer.normalize_for_fts(_original_query),
        query_text,
    )

    # If after stop word removal the query is empty, return empty results.
    if not query_text or not query_text.strip():
        logger.warning(
            "keyword_search: query reduced to empty after stop word removal "
            "for document %s — returning empty results",
            document_id,
        )
        return []

    # ---- FTS query building with progressive fallback ----
    # Use websearch syntax for the initial attempt. websearch ANDs all terms,
    # which is precise but can return zero results when the LLM-generated
    # FTS query contains terms not present in the chunk's search_vector
    # (e.g., "حقوق", "ایران", "قانون" in a HyDE query for a legal text).
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

    # ---- Progressive fallback chain ----
    # If websearch returned zero results, try plainto_tsquery which also ANDs
    # but handles stop words natively (though we already remove them).
    if not results:
        logger.info(
            "keyword_search: websearch returned zero results for '%s' on "
            "document %s — trying plainto_tsquery fallback",
            query_text,
            document_id,
        )
        fallback_query = SearchQuery(
            query_text, config="simple", search_type="plain",
        )
        fallback_qs = DocumentChunk.objects.filter(
            document_id=document_id,
            search_vector__isnull=False,
        )
        fallback_qs = _apply_metadata_filters(fallback_qs, filters)
        fallback_qs = fallback_qs.annotate(
            relevance_score=SearchRank(
                F("search_vector"),
                fallback_query,
            ),
        )
        fallback_qs = fallback_qs.filter(
            search_vector=fallback_query,
        ).order_by("-relevance_score")[:top_k]

        for chunk in fallback_qs:
            results.append(
                _build_result_dict(chunk, float(chunk.relevance_score))
            )

        logger.info(
            "keyword_search: plainto_tsquery fallback for document %s → %d results",
            document_id,
            len(results),
        )

    # ---- Trigram fallback: if FTS still returned zero results, try trigram ----
    if not results and enable_trigram_fallback:
        logger.info(
            "keyword_search: FTS returned zero results for '%s' on document %s "
            "— falling back to trigram search (min_similarity=0.1)",
            query_text,
            document_id,
        )
        results = trigram_search(
            document_id=document_id,
            query_text=query_text,
            top_k=top_k,
            min_similarity=0.1,  # Lower threshold for fallback
            filters=filters,
        )

    return results


# ---------------------------------------------------------------------------
# Trigram search (pg_trgm similarity)
# ---------------------------------------------------------------------------


def trigram_search(
    document_id: str,
    query_text: str,
    top_k: int = 10,
    min_similarity: float = _TRIGRAM_MIN_SIMILARITY,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search document chunks by trigram similarity using PostgreSQL ``pg_trgm``.

    Trigram similarity breaks text into 3-character sliding windows and
    compares them.  This is particularly useful for Persian legal text
    because:

    - **OCR errors**: Persian PDFs often have OCR artifacts like ``مقـاله``
      instead of ``ماده`` — trigrams handle partial matches gracefully.
    - **Spelling variations**: Persian has multiple acceptable spellings
      (e.g., ``آزادی`` vs ``ازادی``).
    - **Tatweel remnants**: Even after normalisation, some Tatweel artifacts
      may remain — trigrams bridge these gaps.
    - **Compound word variations**: ``می‌شود`` vs ``میشود`` vs ``می شود``.

    Requires the ``pg_trgm`` extension and a GIN index on ``content``
    (created by migration ``0010_add_pg_trgm``).

    Args:
        document_id: UUID of the document to search within.
        query_text: The query string to compare via trigram similarity.
        top_k: Maximum number of results to return (default 10).
        min_similarity: Minimum trigram similarity threshold (0.0–1.0).
            Default is ``_TRIGRAM_MIN_SIMILARITY`` (0.2).
        filters: Optional metadata filter conditions.

    Returns:
        A list of result dicts ordered by ``relevance_score`` (trigram
        similarity) descending.  Each dict follows the same schema as
        :func:`search_chunks`.
    """
    if not query_text or not query_text.strip():
        logger.warning(
            "trigram_search: empty query for document %s — returning empty results",
            document_id,
        )
        return []

    logger.info(
        "trigram_search: document=%s query_text=%.300s query_text_repr=%r "
        "top_k=%d min_similarity=%.2f filters=%s",
        document_id,
        query_text,
        query_text,
        top_k,
        min_similarity,
        filters,
    )

    # Build the base queryset.
    queryset = DocumentChunk.objects.filter(
        document_id=document_id,
    )

    # Apply metadata filters.
    queryset = _apply_metadata_filters(queryset, filters)

    # Annotate with trigram similarity.
    queryset = queryset.annotate(
        trgm_score=Func(
            F("content"),
            Value(query_text),
            function="similarity",
            output_field=FloatField(),
        ),
    )

    # Filter by minimum similarity.
    queryset = queryset.filter(trgm_score__gte=min_similarity)

    # Order by similarity descending.
    queryset = queryset.order_by("-trgm_score")[:top_k]

    # Build the result list.
    results: list[dict[str, Any]] = []
    for chunk in queryset:
        results.append(
            _build_result_dict(chunk, float(chunk.trgm_score))
        )

    logger.info(
        "trigram_search: document=%s top_k=%d min_similarity=%.2f "
        "filters=%s → %d results",
        document_id,
        top_k,
        min_similarity,
        filters,
        len(results),
    )

    return results


# ---------------------------------------------------------------------------
# Multi-list RRF Fusion
# ---------------------------------------------------------------------------


def _rrf_fusion_multi(
    result_lists: list[list[dict[str, Any]]],
    top_k: int,
    score_keys: list[str] | None = None,
    weights: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Fuse N ranked result lists using Reciprocal Rank Fusion (RRF).

    Generalises :func:`_rrf_fusion` to handle any number of result lists.
    Each list contributes ``weight * 1 / (k + rank)`` to each chunk's RRF
    score, where *weight* defaults to 1.0 for all lists.

    Args:
        result_lists: A list of ranked result lists (each ordered by
            ``relevance_score`` descending).
        top_k: Maximum number of fused results to return.
        score_keys: Optional list of keys to use for storing original scores
            from each list.  If provided, must have the same length as
            *result_lists*.  Each chunk dict will have ``score_keys[i]`` set
            to the original score from list *i* (or 0.0 if not present).
        weights: Optional list of alpha weights, one per result list.  Each
            weight multiplies the RRF contribution of that list.  If provided,
            must have the same length as *result_lists*.  Defaults to 1.0
            for all lists (standard RRF).

    Returns:
        A list of up to *top_k* result dicts, fused and re-ranked by RRF
        score descending.  Each dict includes the additional keys:

        - **rrf_score** (*float*) — The fused RRF score.
        - Original score keys (if *score_keys* provided).
    """
    if not result_lists:
        return []

    rrf_scores: dict[str, float] = {}
    result_map: dict[str, dict[str, Any]] = {}

    for list_idx, results in enumerate(result_lists):
        score_key = (
            score_keys[list_idx]
            if score_keys and list_idx < len(score_keys)
            else f"source_{list_idx}_score"
        )
        # Determine weight for this list (default 1.0 = standard RRF).
        weight = weights[list_idx] if weights and list_idx < len(weights) else 1.0

        for rank, result in enumerate(results, start=1):
            cid = result["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + weight * 1.0 / (_RRF_K + rank)
            if cid not in result_map:
                result_map[cid] = result
                # Initialise all score keys to 0.0
                if score_keys:
                    for sk in score_keys:
                        result_map[cid][sk] = 0.0
            result_map[cid][score_key] = result["relevance_score"]

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
# Hybrid search (vector + keyword + trigram with RRF fusion)
# ---------------------------------------------------------------------------


def hybrid_search(
    document_id: str,
    query_vector: list[float],
    query_text: str,
    top_k: int = 10,
    min_score: float = 0.0,
    filters: dict[str, Any] | None = None,
    enable_trigram: bool = True,
    rrf_weights: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search combining vector, keyword, and optionally trigram search
    via multi-list RRF fusion.

    Runs :func:`_vector_search` and :func:`keyword_search` independently, and
    optionally :func:`trigram_search`, then fuses all results using
    :func:`_rrf_fusion_multi`.

    Each retrieval method fetches ``max(top_k * 3, 60)`` candidates (RRF depth)
    to ensure sufficient overlap for meaningful fusion.

    **Alpha-weighted RRF:** When *rrf_weights* is provided, each retrieval
    method's contribution to the fused score is multiplied by its weight.
    This allows prioritising more reliable methods (e.g., vector search with
    HyDE) over less reliable ones (e.g., FTS keyword search for Persian text).
    Default weights (when ``None``) are ``[3.0, 1.0, 1.0]`` for
    vector/keyword/trigram respectively, giving vector search 3× the influence
    of keyword or trigram search.

    Args:
        document_id: UUID of the document to search within.
        query_vector: 768-dim embedding vector for the query.
        query_text: Raw keyword query text (will be parsed as ``websearch``).
        top_k: Maximum number of fused results to return (default 10).
        min_score: Minimum relevance score threshold for vector search.
        filters: Optional metadata filter conditions.
        enable_trigram: Whether to include trigram search as a third retrieval
            method (default ``True``).
        rrf_weights: Optional alpha weights for RRF fusion, one per retrieval
            method.  Order: ``[vector_weight, keyword_weight, trigram_weight]``.
            Defaults to ``[3.0, 1.0, 1.0]`` when ``None``.

    Returns:
        A list of up to *top_k* result dicts, fused and re-ranked by RRF score
        descending.  Each dict includes the additional keys:

        - **vector_score** (*float*) — Original vector relevance score.
        - **keyword_score** (*float*) — Original keyword search rank score.
        - **trigram_score** (*float*) — Original trigram similarity score
          (0.0 if trigram search was disabled).
        - **rrf_score** (*float*) — The fused RRF score.
    """
    # Compute RRF depth: each method fetches more candidates than top_k.
    rrf_depth = max(top_k * _RRF_DEPTH_MULTIPLIER, _RRF_MIN_DEPTH)

    # ---- DIAGNOSTIC: log the raw query_text received ----
    logger.info(
        "HYBRID_SEARCH_DIAG: document=%s query_text_raw=%.500s "
        "query_text_repr=%r top_k=%d rrf_depth=%d filters=%s enable_trigram=%s",
        document_id,
        query_text,
        query_text,
        top_k,
        rrf_depth,
        filters,
        enable_trigram,
    )

    # Run vector search.
    vector_results = _vector_search(
        document_id=document_id,
        query_vector=query_vector,
        top_k=rrf_depth,
        min_score=min_score,
        filters=filters,
    )

    # ---- DIAGNOSTIC: log top-5 vector results with scores ----
    logger.info(
        "HYBRID_SEARCH_DIAG: vector_search returned %d results for document %s",
        len(vector_results),
        document_id,
    )
    for i, r in enumerate(vector_results[:5]):
        logger.info(
            "HYBRID_SEARCH_DIAG:   vector[%d] chunk_id=%s vector_score=%.6f "
            "content_preview=%.150s",
            i,
            r.get("chunk_id", "?"),
            r.get("vector_score", r.get("relevance_score", 0.0)),
            r.get("content", "")[:150],
        )

    # Run keyword search.
    keyword_results = keyword_search(
        document_id=document_id,
        query_text=query_text,
        top_k=rrf_depth,
        filters=filters,
    )

    # ---- DIAGNOSTIC: log the effective FTS query and top-5 keyword results ----
    # Compute what keyword_search actually sent to FTS (after normalization).
    _fts_effective = query_text
    _fts_effective = PersianNormalizer.normalize_for_fts(_fts_effective)
    _fts_effective = _remove_stop_words(_fts_effective)
    logger.info(
        "HYBRID_SEARCH_DIAG: keyword_search for document %s — "
        "original_query=%.500s effective_fts_query=%.500s "
        "returned %d results",
        document_id,
        query_text,
        _fts_effective,
        len(keyword_results),
    )
    for i, r in enumerate(keyword_results[:5]):
        logger.info(
            "HYBRID_SEARCH_DIAG:   keyword[%d] chunk_id=%s keyword_score=%.6f "
            "content_preview=%.150s",
            i,
            r.get("chunk_id", "?"),
            r.get("keyword_score", r.get("relevance_score", 0.0)),
            r.get("content", "")[:150],
        )

    # Collect result lists and score keys.
    result_lists: list[list[dict[str, Any]]] = [vector_results, keyword_results]
    score_keys: list[str] = ["vector_score", "keyword_score"]

    # Optionally run trigram search.
    trigram_results: list[dict[str, Any]] = []
    if enable_trigram:
        trigram_results = trigram_search(
            document_id=document_id,
            query_text=query_text,
            top_k=rrf_depth,
            filters=filters,
        )

        # ---- DIAGNOSTIC: log top-5 trigram results with scores ----
        logger.info(
            "HYBRID_SEARCH_DIAG: trigram_search for document %s — "
            "query=%.500s returned %d results",
            document_id,
            query_text,
            len(trigram_results),
        )
        for i, r in enumerate(trigram_results[:5]):
            logger.info(
                "HYBRID_SEARCH_DIAG:   trigram[%d] chunk_id=%s trigram_score=%.6f "
                "content_preview=%.150s",
                i,
                r.get("chunk_id", "?"),
                r.get("trigram_score", r.get("relevance_score", 0.0)),
                r.get("content", "")[:150],
            )

        result_lists.append(trigram_results)
        score_keys.append("trigram_score")

    # Determine RRF weights.
    # Default: vector search gets 3x weight because it's the most reliable
    # method (especially with HyDE). Keyword and trigram get 1x each.
    if rrf_weights is None:
        if enable_trigram:
            rrf_weights = [3.0, 1.0, 1.0]
        else:
            rrf_weights = [3.0, 1.0]

    # ---- DIAGNOSTIC: log RRF weights ----
    logger.info(
        "HYBRID_SEARCH_DIAG: RRF weights=%s for document %s",
        rrf_weights,
        document_id,
    )

    # Fuse using multi-list RRF with alpha weights.
    fused = _rrf_fusion_multi(
        result_lists, top_k, score_keys=score_keys, weights=rrf_weights,
    )

    # Ensure trigram_score key exists even if trigram search was disabled.
    if not enable_trigram:
        for result in fused:
            result["trigram_score"] = 0.0

    # ---- DIAGNOSTIC: log top-5 fused results ----
    logger.info(
        "HYBRID_SEARCH_DIAG: fused results for document %s — top_k=%d returned %d",
        document_id,
        top_k,
        len(fused),
    )
    for i, r in enumerate(fused[:5]):
        logger.info(
            "HYBRID_SEARCH_DIAG:   fused[%d] chunk_id=%s rrf_score=%.6f "
            "vector_score=%.6f keyword_score=%.6f trigram_score=%.6f "
            "content_preview=%.150s",
            i,
            r.get("chunk_id", "?"),
            r.get("rrf_score", 0.0),
            r.get("vector_score", 0.0),
            r.get("keyword_score", 0.0),
            r.get("trigram_score", 0.0),
            r.get("content", "")[:150],
        )

    logger.info(
        "hybrid_search: document=%s top_k=%d min_score=%.2f filters=%s "
        "enable_trigram=%s rrf_weights=%s → vector=%d keyword=%d trigram=%d fused=%d",
        document_id,
        top_k,
        min_score,
        filters,
        enable_trigram,
        rrf_weights,
        len(vector_results),
        len(keyword_results),
        len(trigram_results),
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
