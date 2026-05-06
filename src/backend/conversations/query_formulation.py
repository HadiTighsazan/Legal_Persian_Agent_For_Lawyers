"""
LLM Query Formulation Layer for the RAG pipeline.

Transforms a user's raw conversational query into optimized search strings
for both Full-Text Search (FTS) and Vector Search.

Architecture::

    User Query
        │
        ▼
    ┌─────────────────────────────────────┐
    │  LLM Query Formulation              │
    │  (single chat completion call)      │
    │                                     │
    │  Input:  raw user query             │
    │  Output: QueryFormulationResult     │
    │    ├── fts_query: str               │
    │    └── vector_query: str            │
    └─────────────────────────────────────┘
        │                    │
        ▼                    ▼
    embed_query(vector_query)    fts_query ──► keyword_search()
        │
        ▼
    vector_search(query_vector)
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from documents.services.persian_normalizer import PersianNormalizer
from providers.registry import get_chat_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Max length for fts_query field
FTS_QUERY_MAX_LENGTH: int = 500

# Max length for vector_query field
VECTOR_QUERY_MAX_LENGTH: int = 1000

# System prompt for the LLM query formulation call
SYSTEM_PROMPT: str = (
    "You are a Persian legal search query optimizer. Your task is to transform a "
    "user's conversational question into optimized search queries for a legal "
    "document retrieval system.\n\n"
    "The system uses two search methods:\n"
    "1. **Full-Text Search (FTS)**: PostgreSQL `websearch` over Persian legal texts. "
    "Needs exact keyword matches. Persian digits must be converted to English "
    'digits (e.g., "۲۲" \u2192 "22").\n'
    "2. **Vector Search**: Semantic similarity search. Benefits from a clean, "
    "entity-rich query free of conversational filler.\n\n"
    "### Instructions:\n"
    "1. Extract the core legal entities and concepts from the user's question.\n"
    "2. Translate informal Persian terms to formal legal terminology.\n"
    "   - Example: \"حکم حبس\" \u2192 \"مجازات حبس\"\n"
    "   - Example: \"چقدر باید بده\" \u2192 \"میزان مجازات\"\n"
    "   - Example: \"کلاهبرداری\" \u2192 \"کلاهبرداری\" (already formal)\n"
    "3. For mixed-language queries, preserve English terms exactly as-is.\n"
    "4. **CRITICAL — Preserve all entities in comparative queries**: If the user "
    "asks about multiple concepts (e.g., comparing two things, listing alternatives, "
    "or asking about a relationship between concepts), include ALL concepts in both "
    "``fts_query`` and ``vector_query``. Do NOT drop any entity.\n"
    "   - Example: \"فرق بین عقد لازم و عقد جایز چیست؟\" \u2192 "
    'fts_query includes both "عقد لازم" AND "عقد جایز"\n'
    "5. **Preserve all numbers exactly**: Do not modify, drop, or simplify any "
    "numeric values (article numbers, penalty amounts, percentages, dates, etc.). "
    "Keep them exactly as they appear in the user query (after digit conversion).\n"
    "6. Output ONLY valid JSON with two keys:\n"
    '   - "fts_query": A keyword string optimized for PostgreSQL websearch.\n'
    "     - Use space-separated keywords (websearch handles AND implicitly).\n"
    "     - Convert all Persian digits to English digits.\n"
    "     - Remove stop words, filler, and conversational particles.\n"
    "     - Include both the conversational term AND its formal legal equivalent\n"
    "       when there's a terminology gap (e.g., \"حبس مجازات_حبس\").\n"
    '   - "vector_query": A clean, natural-language query string optimized for\n'
    "     embedding.\n"
    "     - Remove filler words but keep the semantic structure.\n"
    "     - Use formal legal terminology where applicable.\n"
    "     - Keep the query as a natural sentence fragment, not just keywords.\n\n"
    "### Examples:\n\n"
    'Input: "ماده ۲۲ قانون مدنی رو برام توضیح بده"\n'
    "Output:\n"
    '{"fts_query": "ماده 22 قانون مدنی", "vector_query": "ماده 22 قانون مدنی"}\n\n'
    'Input: "حکم حبس برای کلاهبرداری چقدره؟"\n'
    "Output:\n"
    '{"fts_query": "مجازات حبس کلاهبرداری", "vector_query": "مجازات حبس برای جرم کلاهبرداری"}\n\n'
    'Input: "فرق بین عقد لازم و عقد جایز چیست؟"\n'
    "Output:\n"
    '{"fts_query": "عقد لازم عقد جایز", "vector_query": "تفاوت بین عقد لازم و عقد جایز"}\n\n'
    'Input: "What is the penalty for کلاهبرداری under Islamic Penal Code?"\n'
    "Output:\n"
    '{"fts_query": "penalty کلاهبرداری Islamic Penal Code مجازات", '
    '"vector_query": "What is the penalty for کلاهبرداری under the Islamic Penal Code"}'
)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class QueryFormulationResult:
    """Result of the LLM query formulation step.

    Attributes:
        fts_query: Optimized keyword string for PostgreSQL ``websearch`` FTS.
        vector_query: Clean, natural-language query string for embedding /
            vector search.
    """

    fts_query: str = ""
    vector_query: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def formulate_query(user_query: str) -> QueryFormulationResult:
    """Transform a raw user query into optimized search strings.

    Makes a single lightweight chat completion call to the configured chat
    provider. Falls back to using the raw ``user_query`` for both fields on
    any failure (network error, invalid JSON, empty response, etc.).

    If ``settings.QUERY_FORMULATION_ENABLED`` is ``False``, the formulation
    step is skipped entirely and the raw query is returned as-is.

    If ``len(user_query) < 10``, the query is too short to benefit from
    formulation, so the raw query is returned as-is (optimization to avoid
    unnecessary LLM calls for trivial queries).

    Args:
        user_query: The raw user question text.

    Returns:
        A :class:`QueryFormulationResult` with optimized search strings.
    """
    # Normalize Arabic character variants to Persian equivalents
    # This prevents LLM failures caused by mixed Unicode codepoints
    # (e.g., Arabic Yeh U+064A → Persian Yeh U+06CC)
    _ARABIC_TO_PERSIAN = str.maketrans({
        '\u064A': '\u06CC',  # Arabic Yeh → Persian Yeh
        '\u0643': '\u06A9',  # Arabic Kaf → Persian Kaf
    })
    user_query = user_query.translate(_ARABIC_TO_PERSIAN)

    # NFKC normalization — converts Arabic Presentation Forms (positional
    # glyph variants from PDFs) to standard Unicode codepoints.  This is
    # defense-in-depth: even if the user copies text directly from a PDF
    # that uses presentation forms, the query will be normalized before
    # being sent to the LLM or used in FTS.
    user_query = unicodedata.normalize("NFKC", user_query)

    # Short-circuit: skip formulation if disabled or query is too short
    if not settings.QUERY_FORMULATION_ENABLED:
        logger.debug("formulate_query: disabled, returning raw query")
        return QueryFormulationResult(
            fts_query=user_query,
            vector_query=user_query,
        )

    if len(user_query) < 10:
        logger.debug(
            "formulate_query: query too short (%d chars), returning raw query",
            len(user_query),
        )
        return QueryFormulationResult(
            fts_query=user_query,
            vector_query=user_query,
        )

    try:
        messages = _build_formulation_messages(user_query)
        provider = get_chat_provider()
        result = provider.chat(
            messages=messages,
            max_tokens=settings.QUERY_FORMULATION_MAX_TOKENS,
        )
        raw_content = result["content"]
        formulation = _parse_formulation_response(raw_content)

        # Validate non-empty fields with fallback
        if not formulation.fts_query.strip():
            logger.warning(
                "formulate_query: fts_query empty after parsing, falling back to raw query"
            )
            formulation.fts_query = user_query

        if not formulation.vector_query.strip():
            logger.warning(
                "formulate_query: vector_query empty after parsing, falling back to raw query"
            )
            formulation.vector_query = user_query

        logger.info(
            "formulate_query: SUCCESS — fts_query=%.300s vector_query=%.300s",
            formulation.fts_query,
            formulation.vector_query,
        )

        return formulation

    except Exception as e:
        logger.warning(
            "formulate_query: LLM call failed (%s: %s), using raw query as fallback",
            type(e).__name__,
            e,
        )
        return QueryFormulationResult(
            fts_query=user_query,
            vector_query=user_query,
        )


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _build_formulation_messages(user_query: str) -> list[dict[str, str]]:
    """Build the messages array for the query formulation LLM call.

    Args:
        user_query: The raw user question text.

    Returns:
        A list of message dicts with ``role`` and ``content`` keys.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query},
    ]


def _parse_formulation_response(raw_content: str) -> QueryFormulationResult:
    """Parse and validate the LLM JSON response.

    Handles the following failure modes:
    - Invalid JSON (not parseable)
    - Valid JSON but missing ``fts_query`` or ``vector_query`` keys
    - Valid JSON with fields exceeding max length (truncated with warning)

    Args:
        raw_content: The raw string content returned by the chat provider.

    Returns:
        A :class:`QueryFormulationResult` with the parsed values. Missing or
        invalid fields default to empty strings (caller handles fallback).
    """
    # Attempt to extract JSON from the response (handle markdown code fences)
    cleaned = raw_content.strip()

    # Strip markdown code fences if present (```json ... ```)
    if cleaned.startswith("```"):
        # Remove opening fence
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
        elif "```" in cleaned:
            cleaned = cleaned[: cleaned.rfind("```")].strip()

    try:
        data: dict[str, Any] = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(
            "_parse_formulation_response: invalid JSON (%s), raw_content=%.200s",
            e,
            raw_content,
        )
        return QueryFormulationResult()

    # Extract and validate fts_query
    fts_query = data.get("fts_query", "")
    if not isinstance(fts_query, str):
        logger.warning(
            "_parse_formulation_response: fts_query is not a string (%s), resetting",
            type(fts_query).__name__,
        )
        fts_query = ""

    if len(fts_query) > FTS_QUERY_MAX_LENGTH:
        logger.warning(
            "_parse_formulation_response: fts_query exceeds %d chars, truncating",
            FTS_QUERY_MAX_LENGTH,
        )
        fts_query = fts_query[:FTS_QUERY_MAX_LENGTH]

    # Extract and validate vector_query
    vector_query = data.get("vector_query", "")
    if not isinstance(vector_query, str):
        logger.warning(
            "_parse_formulation_response: vector_query is not a string (%s), resetting",
            type(vector_query).__name__,
        )
        vector_query = ""

    if len(vector_query) > VECTOR_QUERY_MAX_LENGTH:
        logger.warning(
            "_parse_formulation_response: vector_query exceeds %d chars, truncating",
            VECTOR_QUERY_MAX_LENGTH,
        )
        vector_query = vector_query[:VECTOR_QUERY_MAX_LENGTH]

    return QueryFormulationResult(
        fts_query=fts_query,
        vector_query=vector_query,
    )
