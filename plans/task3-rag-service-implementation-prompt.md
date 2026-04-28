# Task 3 — RAG Service Layer: Implementation Prompt for Code Mode

## Overview

Implement the RAG (Retrieval-Augmented Generation) service layer for DocuChat. This service orchestrates the full RAG pipeline: embedding a user question, searching for relevant document chunks, building a context string, calling OpenAI's chat API, and extracting citations from the response.

---

## Files to Create / Modify

| Action | File | Description |
|--------|------|-------------|
| **CREATE** | `src/backend/conversations/rag_service.py` | Main RAG service module |
| **CREATE** | `src/backend/conversations/tests/test_rag_service.py` | Unit tests for RAG service |
| **MODIFY** | `src/backend/config/settings.py` | Add 4 new settings |
| **MODIFY** | `.env.example` | Add new env vars for reference |

---

## Step 1 — Add Settings to `src/backend/config/settings.py`

Add these 4 settings **after the existing `VECTOR_SEARCH_PROBES` setting** (around line 247):

```python
# OpenAI Chat Configuration
OPENAI_CHAT_MODEL = env("OPENAI_CHAT_MODEL", default="gpt-4o-mini")
OPENAI_CHAT_MAX_TOKENS = env.int("OPENAI_CHAT_MAX_TOKENS", default=1000)

# RAG Configuration
RAG_MAX_HISTORY_TURNS = env.int("RAG_MAX_HISTORY_TURNS", default=10)
RAG_CONTEXT_TOKEN_BUDGET = env.int("RAG_CONTEXT_TOKEN_BUDGET", default=4000)
```

Also update `.env.example` to include these new variables (add after line 72 `OPENAI_CHAT_MODEL` is already there — just ensure `OPENAI_CHAT_MAX_TOKENS`, `RAG_MAX_HISTORY_TURNS`, and `RAG_CONTEXT_TOKEN_BUDGET` are documented).

---

## Step 2 — Create `src/backend/conversations/rag_service.py`

### 2.1 — Imports & Constants

```python
"""
RAG (Retrieval-Augmented Generation) service for DocuChat.

Provides the core RAG pipeline: embedding a question, searching chunks,
building context, calling OpenAI chat, and extracting citations.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings
from openai import OpenAI

from documents.services.embedding_service import embed_query
from documents.services.search_service import search_chunks

logger = logging.getLogger(__name__)

# Regex pattern for [Source N] citations
SOURCE_PATTERN = re.compile(r"\[Source\s+(\d+)\]")

# Approximate characters per token for budget estimation
_CHARS_PER_TOKEN: int = 4
```

### 2.2 — Custom Exception

```python
class RAGServiceException(Exception):
    """Raised when the RAG pipeline encounters an unrecoverable error."""
    pass
```

### 2.3 — `build_context(chunks: list[dict]) -> str`

```python
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

    for i, chunk in enumerate(chunks):
        header = f"[Source {i + 1} | Pages {chunk['page_start']}-{chunk['page_end']}]"
        part = f"{header}\n{chunk['content']}"

        # If adding this part would exceed the budget, stop.
        current_len = sum(len(p) for p in context_parts)
        if current_len + len(part) > max_chars:
            remaining = max_chars - current_len
            if remaining > 0:
                # Truncate the content portion to fit
                truncated_content = chunk['content'][:remaining - len(header) - 1]
                if truncated_content:
                    context_parts.append(f"{header}\n{truncated_content}")
            break

        context_parts.append(part)

    return "\n\n".join(context_parts)
```

### 2.4 — `build_system_prompt(document_title: str) -> str`

```python
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
```

### 2.5 — `extract_citations(content: str, chunks: list[dict]) -> list[dict]`

```python
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
```

### 2.6 — `run_rag_query(question, document_id, conversation_history, top_k=5) -> dict`

```python
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

    # Step 2: Search for relevant chunks
    logger.info(
        "run_rag_query: Searching chunks for document %s (top_k=%d)",
        document_id,
        top_k,
    )
    try:
        chunks = search_chunks(
            document_id=document_id,
            query_vector=query_embedding,
            top_k=top_k,
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

    # Step 5: Call OpenAI
    logger.info("run_rag_query: Calling OpenAI chat completion")
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=settings.OPENAI_CHAT_MAX_TOKENS,
        )
    except Exception as e:
        logger.exception("run_rag_query: OpenAI API call failed")
        raise RAGServiceException(f"OpenAI API call failed: {e}") from e

    # Extract response content
    choice = response.choices[0]
    response_content = choice.message.content or ""

    # Step 6: Extract citations
    sources = extract_citations(response_content, chunks)

    # Build token usage dict
    token_usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }

    # Step 7: Return result
    return {
        "content": response_content,
        "sources": sources,
        "token_usage": token_usage,
        "raw_chunks": chunks,
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
        from documents.models import Document
        return str(Document.objects.values_list("title", flat=True).get(id=document_id))
    except Exception:
        logger.warning(
            "run_rag_query: Document %s not found, using fallback title",
            document_id,
        )
        return "Unknown Document"
```

---

## Step 3 — Create `src/backend/conversations/tests/test_rag_service.py`

### 3.1 — Test Structure

Use `unittest.mock.patch` to mock:
- `embed_query` from `documents.services.embedding_service`
- `search_chunks` from `documents.services.search_service`
- `OpenAI` client from `openai`

### 3.2 — Test Classes

#### `BuildContextTests`
- `test_formats_chunks_correctly` — Verify `[Source 1 | Pages 1-3]\ncontent` format
- `test_trims_to_token_budget` — Provide chunks exceeding budget, verify truncation
- `test_empty_chunks_list` — Empty list returns empty string
- `test_single_chunk_within_budget` — Single chunk under budget returned as-is

#### `BuildSystemPromptTests`
- `test_includes_document_title` — Prompt contains the document title
- `test_instructions_present` — Prompt includes key instructions (only answer from context, cite sources, "don't have enough information")

#### `ExtractCitationsTests`
- `test_cited_sources_are_extracted` — Response cites [Source 1] and [Source 3], only those are returned
- `test_uncited_sources_ignored` — Chunks exist but are not cited, returns empty list
- `test_malformed_references_ignored` — `[Source abc]`, `[Source]`, `[abc]` are ignored
- `test_out_of_range_source_ignored` — `[Source 99]` when only 5 chunks exist
- `test_multiple_citations_same_source` — Multiple `[Source 1]` references return one citation
- `test_empty_content` — Empty string returns empty list

#### `RunRagQueryTests`
- `test_normal_response` — Full pipeline: mock embed_query → search_chunks → OpenAI → verify result dict keys and structure
- `test_citation_extraction_integration` — OpenAI returns content with `[Source 1]`, verify sources list is populated
- `test_history_truncation` — Provide 20 history turns, verify only last `RAG_MAX_HISTORY_TURNS` (10) are included in messages
- `test_openai_error_handling` — Mock OpenAI to raise an exception, verify `RAGServiceException` is raised
- `test_embedding_error_handling` — Mock `embed_query` to raise, verify `RAGServiceException`
- `test_search_error_handling` — Mock `search_chunks` to raise, verify `RAGServiceException`
- `test_empty_chunks_returns_response` — No chunks found, still calls OpenAI with empty context
- `test_custom_top_k` — Passing `top_k=3` is forwarded to `search_chunks`

### 3.3 — Mocking Strategy

```python
from unittest.mock import patch, MagicMock

@patch("conversations.rag_service.search_chunks")
@patch("conversations.rag_service.embed_query")
@patch("conversations.rag_service.OpenAI")
def test_normal_response(
    mock_openai: MagicMock,
    mock_embed_query: MagicMock,
    mock_search_chunks: MagicMock,
) -> None:
    # Arrange
    mock_embed_query.return_value = [0.1] * 768
    mock_search_chunks.return_value = [
        {
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 3,
            "content": "Sample content for testing.",
            "relevance_score": 0.95,
            "token_count": 10,
            "metadata": {},
        }
    ]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        "Based on the context, [Source 1] provides relevant information."
    )
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    mock_response.usage.total_tokens = 150
    mock_openai.return_value.chat.completions.create.return_value = mock_response

    # Act
    result = run_rag_query(
        question="What is the document about?",
        document_id="doc-123",
        top_k=5,
    )

    # Assert
    assert "content" in result
    assert "sources" in result
    assert "token_usage" in result
    assert "raw_chunks" in result
    assert len(result["sources"]) == 1
    assert result["sources"][0]["chunk_id"] == "chunk-1"
    assert result["token_usage"]["total_tokens"] == 150
```

---

## Step 4 — Update `.env.example`

Add these lines after the existing `OPENAI_CHAT_MODEL` line (around line 72):

```bash
# OpenAI Chat Max Tokens (max tokens per response)
OPENAI_CHAT_MAX_TOKENS=1000

# RAG Configuration
RAG_MAX_HISTORY_TURNS=10
RAG_CONTEXT_TOKEN_BUDGET=4000
```

---

## Implementation Order

1. **Add settings** to `settings.py` and `.env.example`
2. **Create `rag_service.py`** with all 5 functions + exception class
3. **Create `test_rag_service.py`** with comprehensive test coverage
4. **Run tests** to verify everything passes

---

## Acceptance Criteria Checklist

- [ ] `build_context` formats chunks with `[Source N | Pages X-Y]` headers
- [ ] `build_context` trims to `RAG_CONTEXT_TOKEN_BUDGET` (4000 tokens ≈ 16000 chars)
- [ ] `build_system_prompt` includes document title and all required instructions
- [ ] `extract_citations` parses `[Source N]` from response, returns only cited chunks
- [ ] `extract_citations` ignores malformed/out-of-range references
- [ ] `run_rag_query` orchestrates full pipeline: embed → search → context → OpenAI → citations
- [ ] `run_rag_query` includes conversation history (last `RAG_MAX_HISTORY_TURNS` turns)
- [ ] `run_rag_query` raises `RAGServiceException` on OpenAI API errors
- [ ] `run_rag_query` raises `RAGServiceException` on embedding/search errors
- [ ] All unit tests pass with mocked OpenAI client and mocked services
- [ ] Tests cover: normal response, citation extraction, history truncation, OpenAI error, embedding error, search error
