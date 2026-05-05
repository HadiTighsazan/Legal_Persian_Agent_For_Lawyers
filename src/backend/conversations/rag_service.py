"""
RAG (Retrieval-Augmented Generation) service for DocuChat.

Provides the core RAG pipeline: embedding a question, searching chunks,
building context, calling the configured chat provider, and extracting
citations.

The RAG pipeline uses **hybrid search** (vector + keyword with RRF fusion)
by default, with a ``legal_status: "valid"`` filter to exclude obsolete or
repealed laws from the retrieved context.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

from documents.models import Document
from documents.services.embedding_service import embed_query
from documents.services.search_service import hybrid_search
from providers.registry import get_chat_provider

logger = logging.getLogger(__name__)

# Regex pattern for [Source N] citations
SOURCE_PATTERN = re.compile(r"\[Source\s+(\d+)\]")

# Approximate characters per token for budget estimation
_CHARS_PER_TOKEN: int = 4


class RAGServiceException(Exception):
    """Raised when the RAG pipeline encounters an unrecoverable error."""
    pass


def build_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context string for the LLM prompt.

    Each chunk is formatted as::

        [Source {i+1} | Pages {page_start}-{page_end}]
        {content}

    The total context is trimmed to ``settings.RAG_CONTEXT_TOKEN_BUDGET``
    tokens using a character estimate (1 token ≈ 4 chars).

    Args:
        chunks: List of chunk dicts as returned by :func:`search_chunks`.

    Returns:
        A formatted context string, possibly truncated to fit the token budget.
    """
    max_chars = settings.RAG_CONTEXT_TOKEN_BUDGET * _CHARS_PER_TOKEN
    context_parts: list[str] = []
    total_chars = 0

    for i, chunk in enumerate(chunks):
        page_start = chunk.get("page_start", "?")
        page_end = chunk.get("page_end", "?")
        content = chunk.get("content", "")
        legal_context = chunk.get("legal_context", "")

        # Include legal context (article/chapter info) in the header if available
        if legal_context:
            header = f"[Source {i + 1} | Pages {page_start}-{page_end} | {legal_context}]"
        else:
            header = f"[Source {i + 1} | Pages {page_start}-{page_end}]"

        part = f"{header}\n{content}"

        # If adding this part would exceed the budget, stop.
        if total_chars + len(part) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 0:
                # Truncate the content portion to fit
                truncated_content = content[:remaining - len(header) - 1]
                if truncated_content:
                    context_parts.append(f"{header}\n{truncated_content}")
            break

        context_parts.append(part)
        total_chars += len(part)

    return "\n\n".join(context_parts)


def build_system_prompt(document_title: str) -> str:
    """Build the system prompt instructing the assistant on RAG behavior.

    The prompt instructs the assistant to:
    - Only answer from the provided context.
    - Say "I don't have enough information" if the context is insufficient.
    - Cite sources using ``[Source N]`` markers.

    Args:
        document_title: The title of the document being queried.

    Returns:
        The system prompt string.
    """
    return (
        f"You are a helpful assistant answering questions about the document "
        f"\"{document_title}\". "
        f"Answer the user's question based ONLY on the context provided below. "
        f"If the context does not contain enough information to answer the "
        f"question, say \"I don't have enough information to answer that "
        f"question based on the provided context.\" "
        f"When you use information from the context, cite the source using "
        f"the format [Source N] where N is the source number as shown in "
        f"the context headers (e.g., [Source 1], [Source 2])."
    )


def extract_citations(content: str, chunks: list[dict]) -> list[dict]:
    """Parse ``[Source N]`` references from the assistant response.

    Only includes chunks that are actually cited in the response. Each
    citation dict matches the ``sources`` JSONB schema on the
    :class:`~conversations.models.Message` model.

    Args:
        content: The assistant's response text.
        chunks: The list of chunk dicts that were provided in the context
            (same order as passed to :func:`build_context`).

    Returns:
        A list of citation dicts with keys:
        ``chunk_id``, ``page_start``, ``page_end``, ``content_preview``,
        ``relevance_score``.
    """
    # Find all unique source numbers cited in the response
    cited_numbers: set[int] = set()
    for match in SOURCE_PATTERN.finditer(content):
        try:
            cited_numbers.add(int(match.group(1)))
        except (ValueError, IndexError):
            continue

    citations: list[dict[str, Any]] = []
    for num in sorted(cited_numbers):
        # Convert 1-based source number to 0-based chunk index
        idx = num - 1
        if 0 <= idx < len(chunks):
            chunk = chunks[idx]
            citations.append({
                "chunk_id": chunk["chunk_id"],
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "content_preview": chunk["content"][:200],
                "relevance_score": chunk["relevance_score"],
            })

    return citations


def run_rag_query(
    question: str,
    document_id: str,
    conversation_history: list[dict[str, str]] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Execute the full RAG pipeline.

    Steps:
    1. Call :func:`embed_query` to vectorize the question.
    2. Call :func:`search_chunks` to retrieve relevant chunks.
    3. Call :func:`build_context` to format the context string.
    4. Build the messages array: system prompt + history + user question.
    5. Call OpenAI ``chat.completions.create``.
    6. Call :func:`extract_citations` to parse source references.
    7. Return the result dict.

    Args:
        question: The user's question text.
        document_id: UUID of the document to search.
        conversation_history: Optional list of prior message dicts with
            ``role`` and ``content`` keys. Only the last
            ``RAG_MAX_HISTORY_TURNS`` turns are included.
        top_k: Number of top chunks to retrieve (default 5).

    Returns:
        A dict with keys:
        - ``content`` (str): The assistant's response.
        - ``sources`` (list[dict]): Extracted citations.
        - ``token_usage`` (dict): Token usage from the OpenAI response.
        - ``raw_chunks`` (list[dict]): The raw chunks returned by search.

    Raises:
        RAGServiceException: If the OpenAI API call fails.
    """
    # Step 1: Embed the question
    logger.info("run_rag_query: Embedding question for document %s", document_id)
    try:
        query_embedding = embed_query(question)
    except Exception as e:
        raise RAGServiceException(f"Failed to embed question: {e}") from e

    # Step 2: Hybrid search with default legal_status filter
    logger.info(
        "run_rag_query: Hybrid searching chunks for document %s (top_k=%d)",
        document_id,
        top_k,
    )
    try:
        chunks = hybrid_search(
            document_id=document_id,
            query_vector=query_embedding,
            query_text=question,
            top_k=top_k,
            filters={"legal_status": "valid"},
        )
    except Exception as e:
        raise RAGServiceException(f"Failed to search chunks: {e}") from e

    # Step 3: Build context from chunks
    context = build_context(chunks)

    # Step 4: Build messages array
    messages: list[dict[str, str]] = []

    # System prompt
    # We need the document title. Try to get it from the first chunk's document,
    # or use a fallback.
    document_title = _get_document_title(document_id)
    system_prompt = build_system_prompt(document_title)
    messages.append({"role": "system", "content": system_prompt})

    # Conversation history (last N turns)
    if conversation_history:
        max_turns = settings.RAG_MAX_HISTORY_TURNS
        # Each "turn" is a pair of (user, assistant) messages, so we take
        # max_turns * 2 messages from the end.
        recent_history = conversation_history[-(max_turns * 2):]
        messages.extend(recent_history)

    # User question with context
    user_message = (
        f"Context:\n{context}\n\n"
        f"Question: {question}"
    )
    messages.append({"role": "user", "content": user_message})

    # Step 5: Call the configured chat provider
    logger.info("run_rag_query: Calling chat provider")
    try:
        provider = get_chat_provider()
        result = provider.chat(
            messages=messages,
            max_tokens=settings.CHAT_MAX_TOKENS,
        )
        response_content = result["content"]
        token_usage = result["token_usage"]
    except Exception as e:
        logger.exception("run_rag_query: Chat provider API call failed")
        raise RAGServiceException(f"Chat provider API call failed: {e}") from e

    # Step 6: Extract citations
    sources = extract_citations(response_content, chunks)

    # Step 7: Return result
    return {
        "content": response_content,
        "sources": sources,
        "token_usage": token_usage,
        "raw_chunks": chunks,
    }


def run_rag_query_stream(
    question: str,
    document_id: str,
    conversation_history: list[dict[str, str]] | None = None,
    top_k: int = 5,
) -> Any:
    """Execute the RAG pipeline with streaming response.

    Same as :func:`run_rag_query` but yields tokens as they arrive from the
    chat provider, then yields the final metadata (sources, token_usage).

    Yields:
        ``(type: str, data: dict)`` tuples where ``type`` is one of:
        - ``"token"``: A content token. ``data`` = ``{"content": str}``.
        - ``"done"``: Streaming complete. ``data`` = ``{"message_id": str, "sources": list, "token_usage": dict}``.

    Raises:
        RAGServiceException: If any step of the pipeline fails.
    """
    # Step 1: Embed the question
    logger.info("run_rag_query_stream: Embedding question for document %s", document_id)
    try:
        query_embedding = embed_query(question)
    except Exception as e:
        raise RAGServiceException(f"Failed to embed question: {e}") from e

    # Step 2: Hybrid search with default legal_status filter
    logger.info(
        "run_rag_query_stream: Hybrid searching chunks for document %s (top_k=%d)",
        document_id,
        top_k,
    )
    try:
        chunks = hybrid_search(
            document_id=document_id,
            query_vector=query_embedding,
            query_text=question,
            top_k=top_k,
            filters={"legal_status": "valid"},
        )
    except Exception as e:
        raise RAGServiceException(f"Failed to search chunks: {e}") from e

    # Step 3: Build context from chunks
    context = build_context(chunks)

    # Step 4: Build messages array
    messages: list[dict[str, str]] = []

    document_title = _get_document_title(document_id)
    system_prompt = build_system_prompt(document_title)
    messages.append({"role": "system", "content": system_prompt})

    if conversation_history:
        max_turns = settings.RAG_MAX_HISTORY_TURNS
        recent_history = conversation_history[-(max_turns * 2):]
        messages.extend(recent_history)

    user_message = (
        f"Context:\n{context}\n\n"
        f"Question: {question}"
    )
    messages.append({"role": "user", "content": user_message})

    # Step 5: Stream from the chat provider
    logger.info("run_rag_query_stream: Calling chat provider (streaming)")
    try:
        provider = get_chat_provider()
        full_content: list[str] = []
        final_token_usage: dict[str, int] | None = None

        for token_text, is_last, metadata in provider.chat_stream(
            messages=messages,
            max_tokens=settings.CHAT_MAX_TOKENS,
        ):
            if token_text:
                full_content.append(token_text)
                yield "token", {"content": token_text}

            if is_last and metadata:
                final_token_usage = metadata.get("token_usage")

        response_content = "".join(full_content)

    except Exception as e:
        logger.exception("run_rag_query_stream: Chat provider API call failed")
        raise RAGServiceException(f"Chat provider API call failed: {e}") from e

    # Step 6: Extract citations from the full response
    sources = extract_citations(response_content, chunks)

    # Step 7: Yield done event
    token_usage = final_token_usage or {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    yield "done", {
        "content": response_content,
        "sources": sources,
        "token_usage": token_usage,
    }


def _get_document_title(document_id: str) -> str:
    """Retrieve the document title from the database.

    This is a helper used internally by :func:`run_rag_query`. Falls back
    to "Unknown Document" if the document is not found.

    Args:
        document_id: UUID of the document.

    Returns:
        The document title, or "Unknown Document" if not found.
    """
    try:
        return str(Document.objects.values_list("title", flat=True).get(id=document_id))
    except (Document.DoesNotExist, ValidationError):
        logger.warning(
            "run_rag_query: Document %s not found, using fallback title",
            document_id,
        )
        return "Unknown Document"
