"""
Global RAG (Full) Service — Multi-Hub Legal Research with Per-Hub Partial Answers.

Extends the Phase 2a (Lite) pipeline to support **per-hub partial answers**
with **answer synthesis** and **conflict detection**.

Architecture::

    User Query
        │
        ▼
    ┌──────────────────────┐
    │  Question Router     │  ← route_question()
    │  (LLM)               │
    └─────────┬────────────┘
              │ sub_queries: {hub: {fts_query, vector_query}}
              │
              ▼
    ┌──────────────────────┐
    │  Multi-Hub Search    │  ← multi_hub_search()
    │  (parallel per hub)  │
    └─────────┬────────────┘
              │ hub_results: {hub: [chunks]}
              │
              ▼
    ┌──────────────────────┐
    │  Per-Hub Partial     │  ← generate_hub_partial_answer()
    │  Answers (3 LLM)     │     (specialized prompts per hub)
    └─────────┬────────────┘
              │ partial_answers: {hub: {content, token_usage}}
              │
              ▼
    ┌──────────────────────┐
    │  Answer Synthesis    │  ← synthesize_answers()
    │  (1 LLM)             │     (conflict detection + legal hierarchy)
    └─────────┬────────────┘
              │
              ▼
    Final Answer + Conflict Report + Per-Document Citations + Hub Metadata
"""

from __future__ import annotations

import logging
from typing import Any, Generator

from django.conf import settings

from documents.services.embedding_service import embed_query
from documents.services.search_service import cross_document_hybrid_search

from conversations.question_router import (
    HUB_LABELS,
    RouterResult,
    SubQuery,
    route_question,
)

from providers.registry import get_chat_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Approximate characters per token for budget estimation
_CHARS_PER_TOKEN: int = 4

# Number of chunks to retrieve per hub
_GLOBAL_TOP_K_PER_HUB: int = 5

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GlobalRAGServiceException(Exception):
    """Raised when the Global RAG pipeline encounters an unrecoverable error."""
    pass


# ---------------------------------------------------------------------------
# Multi-Hub Search
# ---------------------------------------------------------------------------


def multi_hub_search(
    router_result: RouterResult,
    top_k_per_hub: int = _GLOBAL_TOP_K_PER_HUB,
) -> dict[str, dict[str, Any]]:
    """Execute cross-document hybrid search for each relevant hub.

    For each hub with non-empty sub-queries, this function:
    1. Embeds the hub's ``vector_query`` using :func:`embed_query`.
    2. Calls :func:`cross_document_hybrid_search` with the hub's queries.
    3. Stores the results keyed by hub type.

    Args:
        router_result: The :class:`RouterResult` from :func:`route_question`
            containing sub-queries for each hub.
        top_k_per_hub: Number of top chunks to retrieve per hub (default 10).

    Returns:
        A dict mapping hub type to a result dict with keys:
        - ``chunks`` (list[dict]): Retrieved chunks for this hub.
        - ``sub_query`` (SubQuery): The sub-query used for this hub.
        - ``token_usage`` (dict): Token usage for embedding this hub's query.
    """
    hub_results: dict[str, dict[str, Any]] = {}

    for hub_type, sub_query in router_result.sub_queries.items():
        # Skip hubs with no queries (not relevant)
        if not sub_query.fts_query and not sub_query.vector_query:
            logger.info(
                "multi_hub_search: Skipping hub '%s' — no queries (not relevant)",
                hub_type,
            )
            hub_results[hub_type] = {
                "chunks": [],
                "sub_query": sub_query,
                "token_usage": {"embedding_tokens": 0},
            }
            continue

        logger.info(
            "multi_hub_search: Searching hub '%s' — "
            "fts_query=%.300s vector_query=%.300s",
            hub_type,
            sub_query.fts_query,
            sub_query.vector_query,
        )

        try:
            # Embed the vector query for this hub
            query_embedding = embed_query(sub_query.vector_query)

            # Cross-document hybrid search within this hub
            chunks = cross_document_hybrid_search(
                hub_type=hub_type,
                query_vector=query_embedding,
                query_text=sub_query.fts_query,
                top_k=top_k_per_hub,
            )

            logger.info(
                "multi_hub_search: Hub '%s' returned %d chunks",
                hub_type,
                len(chunks),
            )

            hub_results[hub_type] = {
                "chunks": chunks,
                "sub_query": sub_query,
                "token_usage": {"embedding_tokens": 0},
            }

        except Exception as e:
            logger.exception(
                "multi_hub_search: Search failed for hub '%s': %s",
                hub_type,
                e,
            )
            hub_results[hub_type] = {
                "chunks": [],
                "sub_query": sub_query,
                "error": str(e),
                "token_usage": {"embedding_tokens": 0},
            }

    return hub_results


# ---------------------------------------------------------------------------
# Context Builder
# ---------------------------------------------------------------------------


def build_global_context(
    hub_results: dict[str, dict[str, Any]],
) -> str:
    """Format multi-hub search results into a structured context string.

    Each hub's chunks are grouped under a labelled section::

        === [Legislation — قوانین مصوب] ===
        [Source 1 | Pages X-Y]
        {content}

        === [Judicial Precedent — رویه‌های قضایی] ===
        [Source 2 | Pages X-Y]
        {content}

    Source numbering is **global** across all hubs (not per-hub), so the
    LLM can cite ``[Source N]`` unambiguously.

    The total context is trimmed to ``settings.RAG_CONTEXT_TOKEN_BUDGET``
    tokens using a character estimate (1 token ≈ 4 chars).

    Args:
        hub_results: The result dict from :func:`multi_hub_search`, mapping
            hub type to a dict with ``chunks`` and ``sub_query`` keys.

    Returns:
        A formatted context string with per-hub sections, possibly truncated
        to fit the token budget.
    """
    max_chars = settings.RAG_CONTEXT_TOKEN_BUDGET * _CHARS_PER_TOKEN
    context_parts: list[str] = []
    total_chars = 0
    global_source_num = 1

    # Order hubs consistently
    hub_order = ["legislation", "judicial_precedent", "advisory_opinion"]

    for hub_type in hub_order:
        hub_data = hub_results.get(hub_type)
        if not hub_data:
            continue

        chunks = hub_data.get("chunks", [])
        if not chunks:
            continue

        hub_label = HUB_LABELS.get(hub_type, hub_type)
        section_header = f"=== [{hub_label}] ==="

        # Estimate header cost (+2 for newlines)
        header_cost = len(section_header) + 2
        if total_chars + header_cost > max_chars:
            break

        section_parts: list[str] = [section_header]
        section_chars = header_cost

        for chunk in chunks:
            page_start = chunk.get("page_start", "?")
            page_end = chunk.get("page_end", "?")
            content = chunk.get("content", "")
            legal_context = chunk.get("legal_context", "")

            # Include hub type in the source header so the LLM can
            # distinguish which knowledge hub a citation belongs to
            hub_label = HUB_LABELS.get(hub_type, hub_type)

            if legal_context:
                source_header = (
                    f"[Source {global_source_num} | Hub: {hub_label} "
                    f"| Pages {page_start}-{page_end} "
                    f"| {legal_context}]"
                )
            else:
                source_header = (
                    f"[Source {global_source_num} | Hub: {hub_label} "
                    f"| Pages {page_start}-{page_end}]"
                )

            part = f"{source_header}\n{content}"
            part_cost = len(part) + 2  # +2 for separator newlines

            if total_chars + section_chars + part_cost > max_chars:
                remaining = max_chars - total_chars - section_chars
                if remaining > 0:
                    truncated_content = content[:remaining - len(source_header) - 1]
                    if truncated_content:
                        section_parts.append(f"{source_header}\n{truncated_content}")
                break

            section_parts.append(part)
            section_chars += part_cost
            global_source_num += 1

        section_text = "\n".join(section_parts)
        context_parts.append(section_text)
        total_chars += len(section_text) + 2  # +2 for inter-section newlines

    return "\n\n".join(context_parts)


# ---------------------------------------------------------------------------
# Phase 2b: Per-Hub Specialized Prompts
# ---------------------------------------------------------------------------


def build_hub_system_prompt(hub_type: str) -> str:
    """Build a specialized system prompt for a single legal knowledge hub.

    Each prompt instructs the LLM to act as a specialist in that legal domain
    and produce a **partial answer** focused only on that hub's data.

    Args:
        hub_type: One of ``"legislation"``, ``"judicial_precedent"``,
            or ``"advisory_opinion"``.

    Returns:
        The specialized system prompt string for the given hub type.

    Raises:
        ValueError: If ``hub_type`` is not a recognised hub.
    """
    hub_label = HUB_LABELS.get(hub_type, hub_type)

    base_instructions = (
        f"You are a Persian legal {hub_label} specialist. Your task is to answer "
        "the user's question based ONLY on the context provided below.\n\n"
        "Instructions:\n"
        "1. Answer the user's question based ONLY on the context provided below.\n"
        "2. If the context does not contain enough information to answer the "
        'question, say "I don\'t have enough information in this hub to answer '
        'that question based on the provided context."\n'
        "3. When you use information from the context, cite the source using "
        "the format [Source N] where N is the source number as shown in the "
        "context headers (e.g., [Source 1], [Source 2]).\n"
        "4. Answer in Persian (formal legal Persian) unless the user asks in "
        "another language.\n"
        "5. Be precise and cite specific references (article numbers, judgment "
        "numbers, opinion numbers, dates, issuing authorities) when available "
        "in the context.\n"
        "6. This is a PARTIAL answer — you are answering only from the "
        "perspective of this specific legal hub. Do not try to answer from "
        "other hubs' perspectives.\n"
    )

    if hub_type == "legislation":
        return (
            base_instructions
            + "\n"
            + "You are answering from the **Legislation (قوانین مصوب)** hub. "
            "Focus on enacted laws, codes, and statutes. Cite specific article "
            "numbers (ماده), law names, chapter references (فصل, کتاب, بخش), "
            "and approval dates when available."
        )
    elif hub_type == "judicial_precedent":
        return (
            base_instructions
            + "\n"
            + "You are answering from the **Judicial Precedent (رویه‌های قضایی)** hub. "
            "Focus on court rulings, judicial precedents, and case law. Cite "
            "specific judgment numbers (شماره رأی), court names, issue dates, "
            "and whether the ruling is a binding unified precedent (رأی وحدت رویه)."
        )
    elif hub_type == "advisory_opinion":
        return (
            base_instructions
            + "\n"
            + "You are answering from the **Advisory Opinions (نظریات مشورتی)** hub. "
            "Focus on legal advisory opinions issued by the Legal Department of "
            "the Judiciary (اداره کل حقوقی قوه قضاییه) and judicial meeting "
            "proceedings (مشروح نشست‌های قضایی). Cite specific opinion numbers, "
            "issue dates, and issuing authorities when available."
        )
    else:
        raise ValueError(f"Unknown hub_type: {hub_type}")


def build_synthesis_system_prompt() -> str:
    """Build the system prompt for the answer synthesis LLM call.

    The prompt instructs the assistant to:
    - Merge partial answers from all three legal hubs into a comprehensive answer.
    - Detect conflicts/contradictions between hubs.
    - Resolve conflicts using legal hierarchy: Legislation > Judicial Precedent
      > Advisory Opinions.
    - Report conflicts explicitly with a ``[Conflict]`` marker.
    - Produce a final comprehensive answer in Persian.

    Returns:
        The synthesis system prompt string.
    """
    return (
        "You are a Persian legal synthesis specialist. Your task is to merge "
        "partial answers from three specialised legal knowledge hubs into a "
        "single comprehensive answer.\n\n"
        "The partial answers below were generated independently by specialists "
        "in each hub:\n"
        "- **Legislation (قوانین مصوب)** — Enacted laws, codes, and statutes.\n"
        "- **Judicial Precedent (رویه‌های قضایی)** — Court rulings and case law.\n"
        "- **Advisory Opinions (نظریات مشورتی)** — Legal advisory opinions.\n\n"
        "Instructions:\n"
        "1. Synthesise the partial answers into a coherent, comprehensive "
        "response that addresses the user's original question.\n"
        "2. **Conflict Detection**: Carefully compare information across hubs. "
        "If you find contradictions or differences between hubs:\n"
        "   a. Mark each conflict explicitly with **[Conflict]** at the "
        "beginning of the relevant paragraph.\n"
        "   b. Explain both sides of the conflict clearly.\n"
        "   c. Resolve the conflict using the following legal hierarchy:\n"
        "      - **Legislation** (highest authority) — enacted laws take precedence.\n"
        "      - **Judicial Precedent** (intermediate) — court interpretations "
        "of legislation.\n"
        "      - **Advisory Opinions** (lowest) — non-binding legal guidance.\n"
        "   d. State which position prevails based on this hierarchy.\n"
        "3. If there are NO conflicts, simply synthesise the information "
        "without mentioning conflicts.\n"
        "4. When you use information from a partial answer, indicate which "
        "hub it comes from (e.g., \"According to legislation...\" or \"Based "
        "on judicial precedent...\").\n"
        "5. If a hub's partial answer says it has no relevant information, "
        "you may omit that hub from the synthesis or note that it had no "
        "relevant information.\n"
        "6. Answer in Persian (formal legal Persian) unless the user asks in "
        "another language.\n"
        "7. Be precise and cite specific references (article numbers, judgment "
        "numbers, opinion numbers) when available in the partial answers.\n"
        "8. Structure your answer logically: start with the most authoritative "
        "sources (legislation), then precedent, then advisory opinions."
    )


# ---------------------------------------------------------------------------
# Phase 2b: Per-Hub Partial Answer Generation
# ---------------------------------------------------------------------------


def generate_hub_partial_answer(
    hub_type: str,
    question: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a partial answer for a single legal knowledge hub.

    Builds a mini-context from the hub's chunks, calls the chat provider with
    a hub-specific system prompt, and returns the partial answer.

    Args:
        hub_type: One of ``"legislation"``, ``"judicial_precedent"``,
            or ``"advisory_opinion"``.
        question: The original user question.
        chunks: List of chunk dicts retrieved for this hub.

    Returns:
        A dict with keys:
        - ``content`` (str): The partial answer text.
        - ``token_usage`` (dict): Token usage from the LLM call.
        - ``error`` (str | None): Error message if the LLM call failed.
    """
    # If no chunks, return a "no info" answer immediately (no LLM call)
    if not chunks:
        hub_label = HUB_LABELS.get(hub_type, hub_type)
        logger.info(
            "generate_hub_partial_answer: Hub '%s' has no chunks — skipping LLM call",
            hub_type,
        )
        return {
            "content": f"هیچ اطلاعات مرتبطی در {hub_label} یافت نشد.",
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": None,
        }

    logger.info(
        "generate_hub_partial_answer: Generating partial answer for hub '%s' "
        "with %d chunks",
        hub_type,
        len(chunks),
    )

    try:
        # Build a single-hub context
        single_hub_results = {
            hub_type: {
                "chunks": chunks,
                "sub_query": SubQuery(),
            }
        }
        context = build_global_context(single_hub_results)

        # Build messages
        system_prompt = build_hub_system_prompt(hub_type)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ]

        # Call the chat provider
        provider = get_chat_provider()
        result = provider.chat(
            messages=messages,
            max_tokens=settings.CHAT_MAX_TOKENS,
        )

        logger.info(
            "generate_hub_partial_answer: Hub '%s' partial answer generated "
            "(%d tokens)",
            hub_type,
            result["token_usage"].get("total_tokens", 0),
        )

        return {
            "content": result["content"],
            "token_usage": result["token_usage"],
            "error": None,
        }

    except Exception as e:
        logger.exception(
            "generate_hub_partial_answer: LLM call failed for hub '%s': %s",
            hub_type,
            e,
        )
        hub_label = HUB_LABELS.get(hub_type, hub_type)
        return {
            "content": (
                f"تولید پاسخ جزئی برای {hub_label} با خطا مواجه شد: {str(e)}"
            ),
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Phase 2b: Answer Synthesis with Conflict Detection
# ---------------------------------------------------------------------------


def synthesize_answers(
    question: str,
    partial_answers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Synthesise partial answers from all hubs into a final answer.

    Builds a synthesis context from the partial answers, calls the chat
    provider with the synthesis prompt (which includes conflict detection
    and legal hierarchy resolution), and returns the final answer.

    Args:
        question: The original user question.
        partial_answers: A dict mapping hub type to its partial answer dict
            (as returned by :func:`generate_hub_partial_answer`).

    Returns:
        A dict with keys:
        - ``content`` (str): The synthesised final answer.
        - ``token_usage`` (dict): Token usage from the LLM call.
        - ``error`` (str | None): Error message if the LLM call failed.
    """
    # Build synthesis context from partial answers
    hub_order = ["legislation", "judicial_precedent", "advisory_opinion"]
    synthesis_parts: list[str] = []

    for hub_type in hub_order:
        pa = partial_answers.get(hub_type)
        if not pa:
            continue

        hub_label = HUB_LABELS.get(hub_type, hub_type)
        content = pa.get("content", "")
        error = pa.get("error")

        if error:
            section = (
                f"=== [{hub_label}] ===\n"
                f"[Note: This hub's partial answer encountered an error: {error}]\n"
                f"{content}"
            )
        else:
            section = f"=== [{hub_label}] ===\n{content}"

        synthesis_parts.append(section)

    synthesis_context = "\n\n".join(synthesis_parts)

    logger.info(
        "synthesize_answers: Building synthesis from %d partial answers "
        "(%d chars)",
        len(partial_answers),
        len(synthesis_context),
    )

    try:
        # Build messages
        system_prompt = build_synthesis_system_prompt()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Partial Answers:\n{synthesis_context}\n\n"
                    f"Original Question: {question}"
                ),
            },
        ]

        # Call the chat provider — use SYNTHESIS_MAX_TOKENS for synthesis
        # to prevent truncation of comprehensive Persian legal answers
        provider = get_chat_provider()
        result = provider.chat(
            messages=messages,
            max_tokens=settings.SYNTHESIS_MAX_TOKENS,
        )

        logger.info(
            "synthesize_answers: Synthesis generated (%d tokens)",
            result["token_usage"].get("total_tokens", 0),
        )

        return {
            "content": result["content"],
            "token_usage": result["token_usage"],
            "error": None,
        }

    except Exception as e:
        logger.exception(
            "synthesize_answers: LLM call failed: %s",
            e,
        )
        return {
            "content": (
                f"تلفیق پاسخ‌های جزئی با خطا مواجه شد: {str(e)}"
            ),
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Phase 2a (Legacy) System Prompt — kept for backward compatibility
# ---------------------------------------------------------------------------


def build_global_system_prompt() -> str:
    """Build the system prompt for the Global RAG synthesis LLM call.

    .. deprecated::
        This prompt is used by Phase 2a (Lite). Phase 2b (Full) uses
        :func:`build_hub_system_prompt` and :func:`build_synthesis_system_prompt`
        instead.

    The prompt instructs the assistant to:
    - Act as a Persian legal researcher synthesising answers from multiple hubs.
    - Answer based ONLY on the provided context.
    - Say "I don't have enough information" if the context is insufficient.
    - Cite sources using ``[Source N]`` markers.
    - Clearly indicate which hub each piece of information comes from.

    Returns:
        The system prompt string.
    """
    return (
        "You are a Persian legal researcher assistant. Your task is to answer "
        "the user's legal question by synthesising information from multiple "
        "Persian legal knowledge hubs.\n\n"
        "The context below is organised into sections, each corresponding to a "
        "different legal knowledge hub:\n"
        "- **Legislation (قوانین مصوب)** — Enacted laws, codes, and statutes.\n"
        "- **Judicial Precedent (رویه‌های قضایی)** — Court rulings and case law.\n"
        "- **Advisory Opinions (نظریات مشورتی)** — Legal advisory opinions.\n\n"
        "Instructions:\n"
        "1. Answer the user's question based ONLY on the context provided below.\n"
        "2. If the context does not contain enough information to answer the "
        "question, say \"I don't have enough information to answer that question "
        "based on the provided context.\"\n"
        "3. When you use information from the context, cite the source using "
        "the format [Source N] where N is the source number as shown in the "
        "context headers (e.g., [Source 1], [Source 2]).\n"
        "4. When information comes from different hubs, clearly indicate which "
        "hub each piece of information comes from (e.g., \"According to "
        "legislation...\" or \"Based on judicial precedent...\").\n"
        "5. If there are conflicts or differences between hubs (e.g., a law "
        "says one thing but judicial precedent interprets it differently), "
        "present both perspectives clearly and note the distinction.\n"
        "6. Answer in Persian (formal legal Persian) unless the user asks in "
        "another language.\n"
        "7. Be precise and cite specific article numbers, law names, or case "
        "references when available in the context."
    )


# ---------------------------------------------------------------------------
# Main Pipeline (Phase 2b — Full)
# ---------------------------------------------------------------------------


def run_global_rag_query(
    question: str,
    conversation_history: list[dict[str, str]] | None = None,
    top_k_per_hub: int = _GLOBAL_TOP_K_PER_HUB,
) -> dict[str, Any]:
    """Execute the full Global RAG pipeline (Phase 2b — Full).

    Steps:
    1. **Route** the question to relevant hubs via :func:`route_question`.
    2. **Search** each relevant hub via :func:`multi_hub_search`.
    3. **Generate** per-hub partial answers via :func:`generate_hub_partial_answer`.
    4. **Synthesize** partial answers via :func:`synthesize_answers` with
       conflict detection and legal hierarchy resolution.
    5. **Extract** citations and return the result.

    Args:
        question: The user's legal question text.
        conversation_history: Optional list of prior message dicts with
            ``role`` and ``content`` keys. Only the last
            ``RAG_MAX_HISTORY_TURNS`` turns are included.
        top_k_per_hub: Number of top chunks to retrieve per hub (default 10).

    Returns:
        A dict with keys:
        - ``content`` (str): The assistant's synthesised response.
        - ``sources`` (list[dict]): Extracted citations across all hubs.
        - ``token_usage`` (dict): Combined token usage from all LLM calls.
        - ``hub_metadata`` (dict): Per-hub metadata including chunks retrieved,
          sub-queries used, partial answers, and per-hub token usage.
        - ``raw_chunks`` (list[dict]): All raw chunks from all hubs.
        - ``partial_answers`` (dict): Per-hub partial answers for transparency.

    Raises:
        GlobalRAGServiceException: If any step of the pipeline fails.
    """
    # ------------------------------------------------------------------
    # Step 1: Route the question to relevant hubs
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query: Routing question to hubs")
    try:
        router_result = route_question(question)
    except Exception as e:
        raise GlobalRAGServiceException(f"Question routing failed: {e}") from e

    active_hubs = [
        hub for hub, sq in router_result.sub_queries.items()
        if sq.fts_query or sq.vector_query
    ]
    logger.info(
        "run_global_rag_query: Router identified active hubs: %s",
        active_hubs,
    )

    # ------------------------------------------------------------------
    # Step 2: Search each relevant hub
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query: Searching hubs")
    try:
        hub_results = multi_hub_search(
            router_result=router_result,
            top_k_per_hub=top_k_per_hub,
        )
    except Exception as e:
        raise GlobalRAGServiceException(f"Multi-hub search failed: {e}") from e

    # Collect all chunks and build hub_metadata
    all_chunks: list[dict[str, Any]] = []
    hub_metadata: dict[str, Any] = {}

    for hub_type, hub_data in hub_results.items():
        chunks = hub_data.get("chunks", [])
        all_chunks.extend(chunks)

        hub_metadata[hub_type] = {
            "chunks_count": len(chunks),
            "sub_query": {
                "fts_query": hub_data.get("sub_query", SubQuery()).fts_query,
                "vector_query": hub_data.get("sub_query", SubQuery()).vector_query,
            },
            "error": hub_data.get("error"),
        }

        logger.info(
            "run_global_rag_query: Hub '%s' — %d chunks retrieved",
            hub_type,
            len(chunks),
        )

    # ------------------------------------------------------------------
    # Step 3: Generate per-hub partial answers
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query: Generating per-hub partial answers")
    partial_answers: dict[str, dict[str, Any]] = {}
    total_token_usage: dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
        hub_data = hub_results.get(hub_type)
        chunks = hub_data.get("chunks", []) if hub_data else []

        pa = generate_hub_partial_answer(
            hub_type=hub_type,
            question=question,
            chunks=chunks,
        )
        partial_answers[hub_type] = pa

        # Accumulate token usage
        pa_tokens = pa.get("token_usage", {})
        for key in total_token_usage:
            total_token_usage[key] += pa_tokens.get(key, 0)

        # Update hub_metadata with partial answer info
        hub_metadata[hub_type]["partial_answer"] = pa.get("content", "")
        hub_metadata[hub_type]["partial_answer_token_usage"] = pa_tokens
        hub_metadata[hub_type]["partial_answer_error"] = pa.get("error")

        logger.info(
            "run_global_rag_query: Hub '%s' partial answer generated (%d tokens)",
            hub_type,
            pa_tokens.get("total_tokens", 0),
        )

    # ------------------------------------------------------------------
    # Step 4: Synthesize partial answers
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query: Synthesizing partial answers")
    try:
        synthesis_result = synthesize_answers(
            question=question,
            partial_answers=partial_answers,
        )
    except Exception as e:
        raise GlobalRAGServiceException(f"Answer synthesis failed: {e}") from e

    # Check if synthesis returned an error (synthesize_answers catches exceptions
    # internally and returns them in the result dict)
    if synthesis_result.get("error"):
        logger.error(
            "run_global_rag_query: Synthesis returned an error: %s",
            synthesis_result["error"],
        )
        raise GlobalRAGServiceException(
            f"Answer synthesis failed: {synthesis_result['error']}"
        )

    # Accumulate synthesis token usage
    synth_tokens = synthesis_result.get("token_usage", {})
    for key in total_token_usage:
        total_token_usage[key] += synth_tokens.get(key, 0)

    response_content = synthesis_result.get("content", "")
    synthesis_error = synthesis_result.get("error")

    logger.info(
        "run_global_rag_query: Synthesis complete (%d total tokens across all calls)",
        total_token_usage.get("total_tokens", 0),
    )

    # ------------------------------------------------------------------
    # Step 5: Extract citations from the final answer
    # ------------------------------------------------------------------
    from conversations.rag_service import extract_citations

    sources = extract_citations(response_content, all_chunks)

    # ------------------------------------------------------------------
    # Step 6: Return result
    # ------------------------------------------------------------------
    return {
        "content": response_content,
        "sources": sources,
        "token_usage": total_token_usage,
        "hub_metadata": hub_metadata,
        "raw_chunks": all_chunks,
        "partial_answers": {
            hub_type: {
                "content": pa.get("content", ""),
                "token_usage": pa.get("token_usage", {}),
                "error": pa.get("error"),
            }
            for hub_type, pa in partial_answers.items()
        },
    }


# ---------------------------------------------------------------------------
# Streaming Pipeline (Phase 2b — Full)
# ---------------------------------------------------------------------------


def run_global_rag_query_stream(
    question: str,
    conversation_history: list[dict[str, str]] | None = None,
    top_k_per_hub: int = _GLOBAL_TOP_K_PER_HUB,
) -> Generator[tuple[str, dict[str, Any]], None, None]:
    """Execute the Global RAG pipeline with streaming synthesis.

    Steps 1-3 (routing, search, partial answers) run identically to
    :func:`run_global_rag_query`.  Step 4 (synthesis) uses the chat
    provider's ``chat_stream()`` method so tokens are yielded as they
    arrive, providing a responsive UX.

    Yields:
        ``(event_type, data)`` tuples:

        - ``("token", {"content": str})`` — A content token from the
          synthesis LLM call.
        - ``("done", {...})`` — Final event with keys:
          ``content``, ``sources``, ``token_usage``, ``hub_metadata``,
          ``raw_chunks``, ``partial_answers``.

    Raises:
        GlobalRAGServiceException: If any step of the pipeline fails.
    """
    # ------------------------------------------------------------------
    # Step 1: Route the question to relevant hubs
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query_stream: Routing question to hubs")
    try:
        router_result = route_question(question)
    except Exception as e:
        raise GlobalRAGServiceException(f"Question routing failed: {e}") from e

    active_hubs = [
        hub for hub, sq in router_result.sub_queries.items()
        if sq.fts_query or sq.vector_query
    ]
    logger.info(
        "run_global_rag_query_stream: Router identified active hubs: %s",
        active_hubs,
    )

    # ------------------------------------------------------------------
    # Step 2: Search each relevant hub
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query_stream: Searching hubs")
    try:
        hub_results = multi_hub_search(
            router_result=router_result,
            top_k_per_hub=top_k_per_hub,
        )
    except Exception as e:
        raise GlobalRAGServiceException(f"Multi-hub search failed: {e}") from e

    # Collect all chunks and build hub_metadata
    all_chunks: list[dict[str, Any]] = []
    hub_metadata: dict[str, Any] = {}

    for hub_type, hub_data in hub_results.items():
        chunks = hub_data.get("chunks", [])
        all_chunks.extend(chunks)

        hub_metadata[hub_type] = {
            "chunks_count": len(chunks),
            "sub_query": {
                "fts_query": hub_data.get("sub_query", SubQuery()).fts_query,
                "vector_query": hub_data.get("sub_query", SubQuery()).vector_query,
            },
            "error": hub_data.get("error"),
        }

        logger.info(
            "run_global_rag_query_stream: Hub '%s' — %d chunks retrieved",
            hub_type,
            len(chunks),
        )

    # ------------------------------------------------------------------
    # Step 3: Generate per-hub partial answers
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query_stream: Generating per-hub partial answers")
    partial_answers: dict[str, dict[str, Any]] = {}
    total_token_usage: dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    for hub_type in ["legislation", "judicial_precedent", "advisory_opinion"]:
        hub_data = hub_results.get(hub_type)
        chunks = hub_data.get("chunks", []) if hub_data else []

        pa = generate_hub_partial_answer(
            hub_type=hub_type,
            question=question,
            chunks=chunks,
        )
        partial_answers[hub_type] = pa

        # Accumulate token usage
        pa_tokens = pa.get("token_usage", {})
        for key in total_token_usage:
            total_token_usage[key] += pa_tokens.get(key, 0)

        # Update hub_metadata with partial answer info
        hub_metadata[hub_type]["partial_answer"] = pa.get("content", "")
        hub_metadata[hub_type]["partial_answer_token_usage"] = pa_tokens
        hub_metadata[hub_type]["partial_answer_error"] = pa.get("error")

        logger.info(
            "run_global_rag_query_stream: Hub '%s' partial answer generated (%d tokens)",
            hub_type,
            pa_tokens.get("total_tokens", 0),
        )

    # ------------------------------------------------------------------
    # Step 4: Synthesize partial answers (STREAMING)
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query_stream: Synthesizing partial answers (streaming)")

    # Build synthesis context (same as synthesize_answers)
    hub_order = ["legislation", "judicial_precedent", "advisory_opinion"]
    synthesis_parts: list[str] = []

    for hub_type in hub_order:
        pa = partial_answers.get(hub_type)
        if not pa:
            continue

        hub_label = HUB_LABELS.get(hub_type, hub_type)
        content = pa.get("content", "")
        error = pa.get("error")

        if error:
            section = (
                f"=== [{hub_label}] ===\n"
                f"[Note: This hub's partial answer encountered an error: {error}]\n"
                f"{content}"
            )
        else:
            section = f"=== [{hub_label}] ===\n{content}"

        synthesis_parts.append(section)

    synthesis_context = "\n\n".join(synthesis_parts)

    logger.info(
        "run_global_rag_query_stream: Building synthesis from %d partial answers "
        "(%d chars)",
        len(partial_answers),
        len(synthesis_context),
    )

    try:
        # Build messages
        system_prompt = build_synthesis_system_prompt()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Partial Answers:\n{synthesis_context}\n\n"
                    f"Original Question: {question}"
                ),
            },
        ]

        # Call the chat provider with streaming
        provider = get_chat_provider()
        response_content: str = ""
        synthesis_token_usage: dict[str, int] | None = None

        for token_text, is_last, metadata in provider.chat_stream(
            messages=messages,
            max_tokens=settings.SYNTHESIS_MAX_TOKENS,
        ):
            if token_text:
                response_content += token_text
                yield ("token", {"content": token_text})

            if is_last and metadata:
                synthesis_token_usage = metadata.get("token_usage")

        # If no metadata from stream, fall back to zeros
        if synthesis_token_usage is None:
            synthesis_token_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        # Accumulate synthesis token usage
        for key in total_token_usage:
            total_token_usage[key] += synthesis_token_usage.get(key, 0)

        logger.info(
            "run_global_rag_query_stream: Synthesis complete (%d total tokens across all calls)",
            total_token_usage.get("total_tokens", 0),
        )

    except Exception as e:
        logger.exception(
            "run_global_rag_query_stream: Synthesis streaming failed: %s",
            e,
        )
        raise GlobalRAGServiceException(f"Answer synthesis failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 5: Extract citations from the final answer
    # ------------------------------------------------------------------
    from conversations.rag_service import extract_citations

    sources = extract_citations(response_content, all_chunks)

    # ------------------------------------------------------------------
    # Step 6: Yield done event with full result
    # ------------------------------------------------------------------
    yield ("done", {
        "content": response_content,
        "sources": sources,
        "token_usage": total_token_usage,
        "hub_metadata": hub_metadata,
        "raw_chunks": all_chunks,
        "partial_answers": {
            hub_type: {
                "content": pa.get("content", ""),
                "token_usage": pa.get("token_usage", {}),
                "error": pa.get("error"),
            }
            for hub_type, pa in partial_answers.items()
        },
    })
