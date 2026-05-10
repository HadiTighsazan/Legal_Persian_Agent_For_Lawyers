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

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from providers.registry import get_chat_provider

logger = logging.getLogger(__name__)

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
    "You are a Persian legal question router. Your task is to analyse a user's "
    "legal question and determine which of the three Persian legal knowledge "
    "hubs are relevant, generating optimised search queries for each.\n\n"
    "### The Three Legal Hubs:\n"
    "1. **legislation** — قوانین مصوب (Legislation) — Enacted laws, codes, and "
    "statutes (e.g., قانون مجازات اسلامی, قانون مدنی).\n"
    "2. **judicial_precedent** — رویه‌های قضایی (Judicial Precedent) — Court "
    "rulings, judicial precedents, and case law from the Supreme Court and "
    "other courts.\n"
    "3. **advisory_opinion** — نظریات مشورتی (Advisory Opinions) — Legal "
    "advisory opinions issued by the Legal Department of the Judiciary "
    "(معاونت حقوقی قوه قضاییه).\n\n"
    "### Instructions:\n"
    "1. Analyse the user's question and determine which hubs are relevant.\n"
    "   - Questions about specific laws, articles, or statutes → **legislation**\n"
    "   - Questions about court rulings, judicial interpretations, or case "
    "outcomes → **judicial_precedent**\n"
    "   - Questions about legal interpretations, procedural guidance, or "
    "advisory opinions → **advisory_opinion**\n"
    "   - Many questions will be relevant to MULTIPLE hubs. Include all "
    "relevant hubs.\n"
    "2. For each relevant hub, generate two search queries:\n"
    '   - **fts_query**: A keyword string optimised for PostgreSQL websearch '
    'FTS. Use space-separated keywords. Convert Persian digits to English '
    'digits. Remove stop words.\n'
    "   - **vector_query**: A hypothetical answer (HyDE-style) written in "
    "the style of Persian legal text from that specific hub, optimised for "
    "embedding similarity.\n"
    "3. For hubs that are NOT relevant, set both queries to empty strings.\n"
    "4. **CRITICAL — Preserve all entities**: If the user asks about multiple "
    "concepts, include ALL concepts in the sub-queries for each relevant hub.\n"
    "5. **Preserve all numbers exactly**: Do not modify or drop any numeric "
    "values (article numbers, penalty amounts, dates, etc.).\n"
    "6. Output ONLY valid JSON with the following structure:\n"
    "```\n"
    "{\n"
    '  "reasoning": "Brief explanation of which hubs were selected and why.",\n'
    '  "sub_queries": {\n'
    '    "legislation": {\n'
    '      "fts_query": "keyword string or empty",\n'
    '      "vector_query": "hypothetical answer or empty"\n'
    "    },\n"
    '    "judicial_precedent": {\n'
    '      "fts_query": "keyword string or empty",\n'
    '      "vector_query": "hypothetical answer or empty"\n'
    "    },\n"
    '    "advisory_opinion": {\n'
    '      "fts_query": "keyword string or empty",\n'
    '      "vector_query": "hypothetical answer or empty"\n'
    "    }\n"
    "  }\n"
    "}\n"
    "```\n\n"
    "### Examples:\n\n"
    'Input: "مجازات کلاهبرداری طبق قانون چقدر است؟"\n'
    "Output:\n"
    '{\n'
    '  "reasoning": "The question asks about a specific penalty under the law, '
    'which is primarily a legislation matter. Judicial precedent may also be '
    'relevant for how courts have applied this penalty.",\n'
    '  "sub_queries": {\n'
    '    "legislation": {\n'
    '      "fts_query": "مجازات کلاهبرداری قانون مجازات اسلامی",\n'
    '      "vector_query": "مجازات کلاهبرداری حسب قانون مجازات اسلامی حبس از یک تا هفت سال و پرداخت جزای نقدی معادل مال اخذ شده می‌باشد."\n'
    "    },\n"
    '    "judicial_precedent": {\n'
    '      "fts_query": "کلاهبرداری مجازات رأی دیوان عالی کشور",\n'
    '      "vector_query": "در رویه قضایی، مجازات کلاهبرداری حسب مورد و با توجه به میزان مال مورد کلاهبرداری تعیین می‌گردد."\n'
    "    },\n"
    '    "advisory_opinion": {\n'
    '      "fts_query": "",\n'
    '      "vector_query": ""\n'
    "    }\n"
    "  }\n"
    "}\n\n"
    'Input: "نظریه مشورتی در مورد ماده ۲۲ قانون مدنی"\n'
    "Output:\n"
    '{\n'
    '  "reasoning": "The user explicitly asks for an advisory opinion about a '
    'specific article of the Civil Code. Both advisory_opinion and legislation '
    'are relevant.",\n'
    '  "sub_queries": {\n'
    '    "legislation": {\n'
    '      "fts_query": "ماده 22 قانون مدنی",\n'
    '      "vector_query": "ماده 22 قانون مدنی: هر کس مال غیر را تصرف کند باید آن را به صاحبش مسترد نماید."\n'
    "    },\n"
    '    "judicial_precedent": {\n'
    '      "fts_query": "",\n'
    '      "vector_query": ""\n'
    "    },\n"
    '    "advisory_opinion": {\n'
    '      "fts_query": "ماده 22 قانون مدنی نظریه مشورتی",\n'
    '      "vector_query": "نظریه مشورتی در خصوص ماده 22 قانون مدنی: تصرف مال غیر و الزام به استرداد."\n'
    "    }\n"
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
    """

    sub_queries: dict[str, SubQuery] = field(default_factory=dict)
    reasoning: str = ""


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
    - Invalid JSON (not parseable)
    - Valid JSON but missing ``sub_queries`` or ``reasoning`` keys
    - Valid JSON with sub-query fields exceeding max length (truncated)

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

    try:
        data: dict[str, Any] = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(
            "_parse_router_response: invalid JSON (%s), raw_content=%.200s",
            e,
            raw_content,
        )
        return RouterResult()

    # Extract reasoning
    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = ""

    # Extract sub_queries
    sub_queries_data = data.get("sub_queries")
    if sub_queries_data is None:
        logger.warning(
            "_parse_router_response: sub_queries key missing, returning empty",
        )
        return RouterResult(reasoning=reasoning)
    if not isinstance(sub_queries_data, dict):
        logger.warning(
            "_parse_router_response: sub_queries is not a dict (%s), returning empty",
            type(sub_queries_data).__name__,
        )
        return RouterResult(reasoning=reasoning)

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
    )
