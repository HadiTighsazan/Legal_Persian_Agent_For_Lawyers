"""
Question Router for Global RAG (Lite).

The question router decomposes a user's legal question into sub-queries
targeted at the three Persian legal knowledge hubs:

- **Legislation** (``legislation``) — قوانین مصوب
- **Judicial Precedent** (``judicial_precedent``) — رویه‌های قضایی
- **Advisory Opinions** (``advisory_opinion``) — نظریات مشورتی

The router uses an LLM call to determine which hubs are relevant and to
generate optimised search queries (FTS + vector) for each relevant hub.
This enables the Global RAG system to query only the hubs that are likely
to contain relevant information, reducing latency and token usage.

Architecture::

    User Query
        │
        ▼
    ┌──────────────────────────────────────────────┐
    │  Question Router (LLM)                        │
    │                                               │
    │  Input:  user query                           │
    │  Output: RouterResult                         │
    │    ├── sub_queries: dict[str, SubQuery]       │
    │    │   ├── "legislation": SubQuery            │
    │    │   │   ├── fts_query: str                 │
    │    │   │   └── vector_query: str              │
    │    │   ├── "judicial_precedent": SubQuery     │
    │    │   └── "advisory_opinion": SubQuery       │
    │    └── reasoning: str                         │
    └──────────────────────────────────────────────┘
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

from django.conf import settings
from django.core.cache import cache

from providers.registry import get_chat_provider

logger = logging.getLogger(__name__)

# Default TTL for cached router decisions (1 hour)
ROUTER_CACHE_TIMEOUT: int = 3600

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_HUBS = frozenset({"legislation", "judicial_precedent", "advisory_opinion"})

HUB_LABELS: dict[str, str] = {
    "legislation": "قوانین مصوب (Legislation)",
    "judicial_precedent": "رویه‌های قضایی (Judicial Precedent)",
    "advisory_opinion": "نظریات مشورتی (Advisory Opinions)",
}

# Max length for sub-query fields
SUB_QUERY_MAX_LENGTH: int = 500

# System prompt for the question router LLM call
SYSTEM_PROMPT: str = (
    "You are a Persian legal question router. Analyse a user's legal question "
    "and determine which of three Persian legal knowledge hubs are relevant, "
    "generating optimised search queries for each.\n\n"
    "### Hubs:\n"
    "1. **legislation** — قوانین مصوب (enacted laws, codes, statutes)\n"
    "2. **judicial_precedent** — رویه‌های قضایی (court rulings, case law)\n"
    "3. **advisory_opinion** — نظریات مشورتی (advisory opinions from the Legal Dept. of the Judiciary)\n\n"
    "### Instructions:\n"
    "1. Determine relevant hubs: laws/statutes → legislation; court rulings → "
    "judicial_precedent; legal interpretations/guidance → advisory_opinion. "
    "Many questions span MULTIPLE hubs — include all relevant.\n"
    "2. For each relevant hub, generate:\n"
    '   - **fts_query**: Space-separated keywords for PostgreSQL websearch FTS. '
    'Convert Persian digits to English. Remove stop words.\n'
    "   - **vector_query**: A HyDE-style hypothetical answer in Persian legal "
    "text style, optimised for embedding similarity.\n"
    "3. For irrelevant hubs, set both queries to empty strings.\n"
    "4. **CRITICAL**: Preserve ALL entities and numbers exactly (article numbers, "
    "penalty amounts, dates, etc.).\n"
    "5. Also generate a top-level **hypothetical_answer**: 1-3 sentences in "
    "formal Persian legal language that directly answers the user's question "
    "as if it were an excerpt from a legal document. This is used as the "
    "vector query across all relevant hubs.\n"
    "6. Output ONLY valid JSON:\n"
    "```\n"
    "{\n"
    '  "reasoning": "Brief explanation of which hubs were selected and why.",\n'
    '  "hypothetical_answer": "HyDE-style hypothetical answer in Persian legal text style.",\n'
    '  "sub_queries": {\n'
    '    "legislation": {"fts_query": "…", "vector_query": "…"},\n'
    '    "judicial_precedent": {"fts_query": "…", "vector_query": "…"},\n'
    '    "advisory_opinion": {"fts_query": "…", "vector_query": "…"}\n'
    "  }\n"
    "}\n"
    "```\n\n"
    "### Example:\n\n"
    'Input: "مجازات کلاهبرداری طبق قانون چقدر است؟"\n'
    "Output:\n"
    '{\n'
    '  "reasoning": "The question asks about a specific penalty under the law, '
    'primarily a legislation matter. Judicial precedent may also be relevant.",\n'
    '  "hypothetical_answer": "مجازات کلاهبرداری حسب قانون مجازات اسلامی حبس از یک تا هفت سال و پرداخت جزای نقدی معادل مال اخذ شده می‌باشد.",\n'
    '  "sub_queries": {\n'
    '    "legislation": {\n'
    '      "fts_query": "مجازات کلاهبرداری قانون مجازات اسلامی",\n'
    '      "vector_query": "مجازات کلاهبرداری حسب قانون مجازات اسلامی حبس از یک تا هفت سال و پرداخت جزای نقدی معادل مال اخذ شده می‌باشد."\n'
    "    },\n"
    '    "judicial_precedent": {\n'
    '      "fts_query": "کلاهبرداری مجازات رأی دیوان عالی کشور",\n'
    '      "vector_query": "در رویه قضایی، مجازات کلاهبرداری حسب مورد و با توجه به میزان مال مورد کلاهبرداری تعیین می‌گردد."\n'
    "    },\n"
    '    "advisory_opinion": {"fts_query": "", "vector_query": ""}\n'
    "  }\n"
    "}\n"
)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class SubQuery:
    """Search queries for a single legal knowledge hub.

    Attributes:
        fts_query: Keyword string for PostgreSQL ``websearch`` FTS.
            Empty string means the hub is not relevant.
        vector_query: HyDE-style hypothetical answer for embedding / vector
            search. Empty string means the hub is not relevant.
    """

    fts_query: str = ""
    vector_query: str = ""


@dataclass
class RouterResult:
    """Result of the question routing step.

    Attributes:
        sub_queries: Mapping from hub type to its :class:`SubQuery`.
            Only hubs with non-empty queries should be searched.
        reasoning: Brief explanation from the LLM about which hubs were
            selected and why.
        hypothetical_answer: A HyDE-style hypothetical answer written in the
            style of Persian legal text, used as the vector query for all
            relevant hubs. This replaces the separate ``formulate_query()``
            call, saving one LLM invocation per pipeline run.
    """

    sub_queries: dict[str, SubQuery] = field(default_factory=dict)
    reasoning: str = ""
    hypothetical_answer: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def route_question(user_query: str) -> RouterResult:
    """Route a user's legal question to the relevant knowledge hubs.

    Makes a single chat completion call to the configured chat provider to
    determine which of the three legal knowledge hubs are relevant and to
    generate optimised search queries for each.

    Falls back to querying **all hubs** with the raw user query on any
    failure (network error, invalid JSON, empty response, etc.).

    If ``settings.QUERY_FORMULATION_ENABLED`` is ``False``, the routing
    step is skipped and all hubs are queried with the raw user query.

    Args:
        user_query: The raw user question text.

    Returns:
        A :class:`RouterResult` with sub-queries for each relevant hub.
    """
    # Short-circuit: skip routing if disabled
    if not settings.QUERY_FORMULATION_ENABLED:
        logger.debug("route_question: disabled, returning all hubs with raw query")
        return _all_hubs_fallback(user_query, "Question routing disabled.")

    try:
        messages = _build_router_messages(user_query)
        provider = get_chat_provider()
        result = provider.chat(
            messages=messages,
            max_tokens=settings.QUERY_FORMULATION_MAX_TOKENS,
        )
        raw_content = result["content"]
        router_result = _parse_router_response(raw_content)

        # Validate: ensure all hubs are present
        for hub in ALL_HUBS:
            if hub not in router_result.sub_queries:
                logger.warning(
                    "route_question: hub '%s' missing from router response, "
                    "adding with raw query fallback",
                    hub,
                )
                router_result.sub_queries[hub] = SubQuery(
                    fts_query=user_query,
                    vector_query=user_query,
                )

        # Validate non-empty fields with fallback
        for hub, sub_query in router_result.sub_queries.items():
            if sub_query.fts_query and not sub_query.fts_query.strip():
                logger.warning(
                    "route_question: fts_query empty for hub '%s', "
                    "falling back to raw query",
                    hub,
                )
                sub_query.fts_query = user_query
            if sub_query.vector_query and not sub_query.vector_query.strip():
                logger.warning(
                    "route_question: vector_query empty for hub '%s', "
                    "falling back to raw query",
                    hub,
                )
                sub_query.vector_query = user_query

        # Log which hubs are active
        active_hubs = [
            hub for hub, sq in router_result.sub_queries.items()
            if sq.fts_query or sq.vector_query
        ]
        logger.info(
            "route_question: SUCCESS — active_hubs=%s reasoning=%.200s",
            active_hubs,
            router_result.reasoning,
        )

        # Fallback: ensure hypothetical_answer is populated (Phase 3)
        # If the router returned an empty hypothetical_answer (e.g. parsing
        # failed partially), fall back to the raw user query so the pipeline
        # still has a vector query to embed.
        if not router_result.hypothetical_answer:
            router_result.hypothetical_answer = user_query

        return router_result

    except Exception as e:
        logger.warning(
            "route_question: LLM call failed (%s: %s), "
            "falling back to all hubs with raw query",
            type(e).__name__,
            e,
        )
        return _all_hubs_fallback(
            user_query,
            f"Router LLM call failed: {type(e).__name__}: {e}",
        )


def route_question_cached(
    user_query: str,
    timeout: int = ROUTER_CACHE_TIMEOUT,
) -> RouterResult:
    """Route a user's legal question with Redis caching.

    Wraps :func:`route_question` with a Redis cache layer keyed by
    a normalized (lowercased, stripped) version of the query text.
    If the same question is routed again within the TTL window, the
    cached :class:`RouterResult` is returned instead of making an LLM
    call.

    Cache key format: ``docuchat:router:<md5_of_normalized_query>``

    Args:
        user_query: The raw user question text.
        timeout: Cache TTL in seconds (default: 1 hour).

    Returns:
        A :class:`RouterResult` with sub-queries for each relevant hub.
    """
    normalized = user_query.strip().lower()
    cache_key = f"router:{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"
    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("route_question_cached: HIT for query=%.80s", user_query)
        return _router_result_from_dict(cached)
    logger.debug("route_question_cached: MISS for query=%.80s", user_query)
    result = route_question(user_query)
    cache.set(cache_key, asdict(result), timeout)
    return result


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _build_router_messages(user_query: str) -> list[dict[str, str]]:
    """Build the messages array for the question router LLM call.

    Args:
        user_query: The raw user question text.

    Returns:
        A list of message dicts with ``role`` and ``content`` keys.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]


def _parse_router_response(raw_content: str) -> RouterResult:
    """Parse and validate the LLM JSON response for question routing.

    Handles the following failure modes:
    - Invalid JSON (not parseable) — with 3-tier fallback
    - Valid JSON but missing ``sub_queries`` or ``reasoning`` keys
    - Valid JSON with sub-query fields exceeding max length (truncated)

    **3-Tier JSON Parsing Fallback:**
    1. ``json.loads(cleaned)`` — standard strict parsing
    2. ``json.loads(cleaned, strict=False)`` — allows unescaped control
       characters (e.g. newlines) inside string values (common when LLM
       returns Persian text with embedded line breaks)
    3. Regex extraction of JSON object — catches cases where LLM wraps
       JSON in markdown code blocks or adds extra text

    Args:
        raw_content: The raw string content returned by the chat provider.

    Returns:
        A :class:`RouterResult` with parsed values. On failure, returns
        a result with all hubs using the raw query as fallback.
    """
    cleaned = raw_content.strip()

    # Strip markdown code fences if present (```json ... ```)
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
        elif "```" in cleaned:
            cleaned = cleaned[: cleaned.rfind("```")].strip()

    # ------------------------------------------------------------------
    # 3-Tier JSON Parsing Fallback
    # ------------------------------------------------------------------
    data: dict[str, Any] | None = None
    parse_errors: list[str] = []

    # Tier 1: Standard strict parsing
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        parse_errors.append(f"strict: {e}")

    # Tier 2: Non-strict parsing (allows unescaped control chars in strings)
    if data is None:
        try:
            data = json.loads(cleaned, strict=False)
            logger.info(
                "_parse_router_response: recovered with strict=False "
                "(unescaped control chars in string values)"
            )
        except json.JSONDecodeError as e:
            parse_errors.append(f"non-strict: {e}")

    # Tier 3: Regex extraction of JSON object from raw content
    if data is None:
        import re
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            extracted = json_match.group(0)
            try:
                data = json.loads(extracted, strict=False)
                logger.info(
                    "_parse_router_response: recovered via regex extraction"
                )
            except json.JSONDecodeError as e:
                parse_errors.append(f"regex: {e}")

    if data is None:
        logger.warning(
            "_parse_router_response: all 3 parsing tiers failed (%s), "
            "raw_content=%.200s",
            "; ".join(parse_errors),
            raw_content,
        )
        return RouterResult()

    # Extract reasoning
    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = ""

    # Extract hypothetical_answer (HyDE — Phase 3 merge)
    hypothetical_answer = data.get("hypothetical_answer", "")
    if not isinstance(hypothetical_answer, str):
        hypothetical_answer = ""
    if len(hypothetical_answer) > SUB_QUERY_MAX_LENGTH:
        logger.warning(
            "_parse_router_response: hypothetical_answer exceeds %d chars, truncating",
            SUB_QUERY_MAX_LENGTH,
        )
        hypothetical_answer = hypothetical_answer[:SUB_QUERY_MAX_LENGTH]

    # Extract sub_queries
    sub_queries_data = data.get("sub_queries")
    if sub_queries_data is None:
        logger.warning(
            "_parse_router_response: sub_queries key missing, returning empty",
        )
        return RouterResult(
            reasoning=reasoning,
            hypothetical_answer=hypothetical_answer,
        )
    if not isinstance(sub_queries_data, dict):
        logger.warning(
            "_parse_router_response: sub_queries is not a dict (%s), returning empty",
            type(sub_queries_data).__name__,
        )
        return RouterResult(
            reasoning=reasoning,
            hypothetical_answer=hypothetical_answer,
        )

    sub_queries: dict[str, SubQuery] = {}
    for hub in sub_queries_data:
        if hub not in ALL_HUBS:
            continue
        hub_data = sub_queries_data[hub]
        if not isinstance(hub_data, dict):
            logger.warning(
                "_parse_router_response: hub '%s' data is not a dict, skipping",
                hub,
            )
            continue

        fts_query = hub_data.get("fts_query", "")
        vector_query = hub_data.get("vector_query", "")

        # Validate types
        if not isinstance(fts_query, str):
            fts_query = ""
        if not isinstance(vector_query, str):
            vector_query = ""

        # Truncate if too long
        if len(fts_query) > SUB_QUERY_MAX_LENGTH:
            logger.warning(
                "_parse_router_response: fts_query for hub '%s' exceeds %d chars, truncating",
                hub,
                SUB_QUERY_MAX_LENGTH,
            )
            fts_query = fts_query[:SUB_QUERY_MAX_LENGTH]

        if len(vector_query) > SUB_QUERY_MAX_LENGTH:
            logger.warning(
                "_parse_router_response: vector_query for hub '%s' exceeds %d chars, truncating",
                hub,
                SUB_QUERY_MAX_LENGTH,
            )
            vector_query = vector_query[:SUB_QUERY_MAX_LENGTH]

        sub_queries[hub] = SubQuery(
            fts_query=fts_query,
            vector_query=vector_query,
        )

    return RouterResult(
        sub_queries=sub_queries,
        reasoning=reasoning,
        hypothetical_answer=hypothetical_answer,
    )


def _router_result_from_dict(data: dict[str, Any]) -> RouterResult:
    """Reconstruct a :class:`RouterResult` from a serialised dict.

    This is the inverse of ``asdict(result)`` used when storing
    :class:`RouterResult` in the cache.  It converts the nested
    ``sub_queries`` dict-of-dicts back into dict-of-:class:`SubQuery`.

    Args:
        data: A dict produced by ``dataclasses.asdict()`` on a
            :class:`RouterResult`.

    Returns:
        A reconstructed :class:`RouterResult`.
    """
    sub_queries_raw = data.get("sub_queries", {})
    sub_queries: dict[str, SubQuery] = {}
    for hub, sq_data in sub_queries_raw.items():
        if isinstance(sq_data, dict):
            sub_queries[hub] = SubQuery(
                fts_query=sq_data.get("fts_query", ""),
                vector_query=sq_data.get("vector_query", ""),
            )
        elif isinstance(sq_data, SubQuery):
            sub_queries[hub] = sq_data
    return RouterResult(
        sub_queries=sub_queries,
        reasoning=data.get("reasoning", ""),
        hypothetical_answer=data.get("hypothetical_answer", ""),
    )


def _all_hubs_fallback(user_query: str, reason: str) -> RouterResult:
    """Create a fallback :class:`RouterResult` that queries all hubs.

    Used when the LLM call fails or routing is disabled.

    Args:
        user_query: The raw user query to use for all hubs.
        reason: Explanation for the fallback.

    Returns:
        A :class:`RouterResult` with all hubs using the raw query.
    """
    sub_queries: dict[str, SubQuery] = {}
    for hub in ALL_HUBS:
        sub_queries[hub] = SubQuery(
            fts_query=user_query,
            vector_query=user_query,
        )

    return RouterResult(
        sub_queries=sub_queries,
        reasoning=reason,
        hypothetical_answer=user_query,
    )
