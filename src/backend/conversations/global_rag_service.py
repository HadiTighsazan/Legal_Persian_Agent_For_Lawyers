"""
Global RAG (Lite) Service — Multi-Hub Legal Research.

Extends the existing RAG pipeline to support **cross-document** search across
the three Persian legal knowledge hubs (Legislation, Judicial Precedent,
Advisory Opinions).

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
    │                      │
    │  ┌──────────────┐    │
    │  │ Legislation  │────│── cross_document_hybrid_search()
    │  └──────────────┘    │
    │  ┌──────────────┐    │
    │  │ Judicial     │────│── cross_document_hybrid_search()
    │  │ Precedent    │    │
    │  └──────────────┘    │
    │  ┌──────────────┐    │
    │  │ Advisory     │────│── cross_document_hybrid_search()
    │  │ Opinions     │    │
    │  └──────────────┘    │
    └─────────┬────────────┘
              │ hub_results: {hub: [chunks]}
              │
              ▼
    ┌──────────────────────┐
    │  Context Builder     │  ← build_global_context()
    │  (per-hub sections)  │
    └─────────┬────────────┘
              │ context string
              │
              ▼
    ┌──────────────────────┐
    │  LLM Synthesis       │  ← run_global_rag_query()
    │  (single call)       │
    │                      │
    │  System Prompt:      │
    │  "You are a Persian  │
    │   legal researcher   │
    │   synthesizing       │
    │   answers from       │
    │   multiple hubs..."  │
    └──────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Any

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
_GLOBAL_TOP_K_PER_HUB: int = 10

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
# System Prompt
# ---------------------------------------------------------------------------


def build_global_system_prompt() -> str:
    """Build the system prompt for the Global RAG synthesis LLM call.

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
# Main Pipeline
# ---------------------------------------------------------------------------


def run_global_rag_query(
    question: str,
    conversation_history: list[dict[str, str]] | None = None,
    top_k_per_hub: int = _GLOBAL_TOP_K_PER_HUB,
) -> dict[str, Any]:
    """Execute the full Global RAG pipeline.

    Steps:
    1. **Route** the question to relevant hubs via :func:`route_question`.
    2. **Search** each relevant hub via :func:`multi_hub_search`.
    3. **Build** a structured context via :func:`build_global_context`.
    4. **Synthesize** an answer via the configured chat provider.
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
        - ``token_usage`` (dict): Token usage from the LLM call.
        - ``hub_metadata`` (dict): Per-hub metadata including chunks retrieved
          and sub-queries used. This is stored in the ``hub_metadata`` JSONB
          field on the :class:`~conversations.models.Message` model.
        - ``raw_chunks`` (list[dict]): All raw chunks from all hubs.

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
    # Step 3: Build structured context
    # ------------------------------------------------------------------
    context = build_global_context(hub_results)

    logger.info(
        "run_global_rag_query: Context built — %d chars, %d total chunks from %d hubs",
        len(context),
        len(all_chunks),
        len(hub_results),
    )

    # ------------------------------------------------------------------
    # Step 4: Build messages array
    # ------------------------------------------------------------------
    messages: list[dict[str, str]] = []

    # System prompt
    system_prompt = build_global_system_prompt()
    messages.append({"role": "system", "content": system_prompt})

    # Conversation history (last N turns)
    if conversation_history:
        max_turns = settings.RAG_MAX_HISTORY_TURNS
        recent_history = conversation_history[-(max_turns * 2):]
        messages.extend(recent_history)

    # User question with context
    user_message = (
        f"Context:\n{context}\n\n"
        f"Question: {question}"
    )
    messages.append({"role": "user", "content": user_message})

    # ------------------------------------------------------------------
    # Step 5: Call the configured chat provider
    # ------------------------------------------------------------------
    logger.info("run_global_rag_query: Calling chat provider")
    try:
        provider = get_chat_provider()
        result = provider.chat(
            messages=messages,
            max_tokens=settings.CHAT_MAX_TOKENS,
        )
        response_content = result["content"]
        token_usage = result["token_usage"]
    except Exception as e:
        logger.exception("run_global_rag_query: Chat provider API call failed")
        raise GlobalRAGServiceException(
            f"Chat provider API call failed: {e}"
        ) from e

    # ------------------------------------------------------------------
    # Step 6: Extract citations
    # ------------------------------------------------------------------
    from conversations.rag_service import extract_citations

    sources = extract_citations(response_content, all_chunks)

    # ------------------------------------------------------------------
    # Step 7: Return result
    # ------------------------------------------------------------------
    return {
        "content": response_content,
        "sources": sources,
        "token_usage": token_usage,
        "hub_metadata": hub_metadata,
        "raw_chunks": all_chunks,
    }
