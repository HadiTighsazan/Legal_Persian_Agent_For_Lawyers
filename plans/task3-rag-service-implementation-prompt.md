# Task 3 — RAG Service Layer: Implementation Prompt for Code Mode

## Overview

Implement the RAG (Retrieval-Augmented Generation) service layer for DocuChat. This service orchestrates the full RAG pipeline: embedding a user question, searching for relevant document chunks, building a context string, calling OpenAI's chat API, and extracting citations from the response.

**Important:** The files [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) and [`src/backend/conversations/tests/test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py) already exist with a full implementation. However, you must **verify the implementation is correct**, ensure all tests pass, and fix any issues found. Treat this as a **review + verify + fix** task, not a from-scratch implementation.

---

## Files to Create / Modify

| Action | File | Description |
|--------|------|-------------|
| **VERIFY** | [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) | Main RAG service module (already exists) |
| **VERIFY** | [`src/backend/conversations/tests/test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py) | Unit tests for RAG service (already exist) |
| **VERIFY** | [`src/backend/config/settings.py`](src/backend/config/settings.py) | Settings already have the 4 RAG-related settings |
| **VERIFY** | [`.env.example`](.env.example) | Env vars already documented |

---

## Step 1 — Verify Settings in [`src/backend/config/settings.py`](src/backend/config/settings.py)

Open the file and confirm these 4 settings exist (they should be around lines 249-255):

```python
# OpenAI Chat Configuration
OPENAI_CHAT_MODEL = env("OPENAI_CHAT_MODEL", default="gpt-4o-mini")
OPENAI_CHAT_MAX_TOKENS = env.int("OPENAI_CHAT_MAX_TOKENS", default=1000)

# RAG Configuration
RAG_MAX_HISTORY_TURNS = env.int("RAG_MAX_HISTORY_TURNS", default=10)
RAG_CONTEXT_TOKEN_BUDGET = env.int("RAG_CONTEXT_TOKEN_BUDGET", default=4000)
```

Also verify that `OPENAI_API_KEY` is already configured (line 236):
```python
OPENAI_API_KEY = env('OPENAI_API_KEY', default='')
```

If any are missing, add them.

---

## Step 2 — Verify [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py)

Open the file and verify each component is correctly implemented. The file should contain:

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

### 2.2 — `RAGServiceException`

```python
class RAGServiceException(Exception):
    """Raised when the RAG pipeline encounters an unrecoverable error."""
    pass
```

### 2.3 — `build_context(chunks: list[dict]) -> str`

Verify the function:
- Takes `chunks: list[dict]` — each dict has keys: `chunk_id`, `chunk_index`, `page_start`, `page_end`, `content`, `relevance_score`, `token_count`, `metadata`
- Formats each chunk as `[Source {i+1} | Pages {page_start}-{page_end}]\n{content}`
- Trims total context to `settings.RAG_CONTEXT_TOKEN_BUDGET` tokens using char estimate (1 token ≈ 4 chars)
- Returns formatted context string with `\n\n` separator between chunks
- Handles edge case: empty chunks list returns `""`
- Handles edge case: partial truncation of last chunk to fit budget

### 2.4 — `build_system_prompt(document_title: str) -> str`

Verify the function:
- Takes `document_title: str`
- Returns a system prompt that instructs the assistant to:
  - Only answer from provided context
  - Say "I don't have enough information to answer that question based on the provided context." if insufficient
  - Cite sources using `[Source N]` markers
- Includes the document title in the prompt

### 2.5 — `extract_citations(content: str, chunks: list[dict]) -> list[dict]`

Verify the function:
- Parses `[Source N]` references from assistant response using `SOURCE_PATTERN` regex
- Returns list of citation dicts with keys: `chunk_id`, `page_start`, `page_end`, `content_preview` (first 200 chars), `relevance_score`
- Only includes chunks actually cited in the response
- Handles edge cases: malformed references `[Source abc]`, out-of-range `[Source 99]`, multiple citations to same source (deduplicated), empty content

### 2.6 — `run_rag_query(question, document_id, conversation_history, top_k=5) -> dict`

Verify the function orchestrates the full RAG pipeline:

1. **Embed question**: Call `embed_query(question)` — wrap in try/except, raise `RAGServiceException` on failure
2. **Search chunks**: Call `search_chunks(document_id, query_vector, top_k)` — wrap in try/except, raise `RAGServiceException` on failure
3. **Build context**: Call `build_context(chunks)`
4. **Build messages array**:
   - System prompt (via `build_system_prompt` + internal `_get_document_title` helper)
   - Conversation history: last `RAG_MAX_HISTORY_TURNS * 2` messages (each turn = user + assistant pair)
   - User question with context: `"Context:\n{context}\n\nQuestion: {question}"`
5. **Call OpenAI**: `client.chat.completions.create(model=settings.OPENAI_CHAT_MODEL, messages=messages, max_tokens=settings.OPENAI_CHAT_MAX_TOKENS)`
6. **Extract citations**: Call `extract_citations(response_content, chunks)`
7. **Return dict**: `{"content": str, "sources": list[dict], "token_usage": dict, "raw_chunks": list[dict]}`

Also verify the internal helper `_get_document_title(document_id: str) -> str`:
- Queries `Document.objects.values_list("title", flat=True).get(id=document_id)`
- Falls back to `"Unknown Document"` if document not found

### 2.7 — Verify import paths

The file imports from:
- `documents.services.embedding_service` → `embed_query`
- `documents.services.search_service` → `search_chunks`

Verify these import paths are correct relative to the project structure. The `conversations` app is at [`src/backend/conversations/`](src/backend/conversations/) and the `documents` app is at [`src/backend/documents/`](src/backend/documents/). Since both are Django apps under the same project root, these imports should work.

---

## Step 3 — Verify [`src/backend/conversations/tests/test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py)

Open the file and verify all test classes and methods exist. The test file should contain:

### 3.1 — Fixtures

```python
@pytest.fixture
def sample_chunks() -> list[dict]:
    """Return a list of 3 sample chunk dicts matching search_service output."""
    return [
        {
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 3,
            "content": "The quick brown fox jumps over the lazy dog.",
            "relevance_score": 0.95,
            "token_count": 10,
            "metadata": {},
        },
        # ... 2 more chunks
    ]
```

### 3.2 — `BuildContextTests`

| Test | Description |
|------|-------------|
| `test_formats_chunks_correctly` | Verify `[Source 1 \| Pages 1-3]` headers and content appear |
| `test_trims_to_token_budget` | Use `@override_settings(RAG_CONTEXT_TOKEN_BUDGET=10)`, verify truncation |
| `test_empty_chunks_list` | Empty list returns `""` |
| `test_single_chunk_within_budget` | Single chunk returned as-is |

### 3.3 — `BuildSystemPromptTests`

| Test | Description |
|------|-------------|
| `test_includes_document_title` | Prompt contains the document title |
| `test_instructions_present` | Prompt includes: "ONLY on the context", "don't have enough information", "[Source N]" |

### 3.4 — `ExtractCitationsTests`

| Test | Description |
|------|-------------|
| `test_cited_sources_are_extracted` | Response cites [Source 1] and [Source 3], only those returned |
| `test_uncited_sources_ignored` | No citations in response → empty list |
| `test_malformed_references_ignored` | `[Source abc]`, `[Source]`, `[abc]` ignored |
| `test_out_of_range_source_ignored` | `[Source 99]` when only 3 chunks → ignored |
| `test_multiple_citations_same_source` | Multiple `[Source 1]` → one citation |
| `test_empty_content` | Empty string → empty list |

### 3.5 — `RunRagQueryTests`

All tests use `@patch("conversations.rag_service.search_chunks")`, `@patch("conversations.rag_service.embed_query")`, `@patch("conversations.rag_service.OpenAI")`.

| Test | Description |
|------|-------------|
| `test_normal_response` | Full pipeline: mock all 3, verify result dict has `content`, `sources`, `token_usage`, `raw_chunks` |
| `test_citation_extraction_integration` | OpenAI returns content with `[Source 1]` and `[Source 2]`, verify sources populated |
| `test_history_truncation` | 20 turns of history (40 messages), verify only last 10 turns (20 messages) included in OpenAI call |
| `test_openai_error_handling` | Mock OpenAI to raise `Exception("OpenAI API error")`, verify `RAGServiceException` raised |
| `test_embedding_error_handling` | Mock `embed_query` to raise, verify `RAGServiceException` + OpenAI never called |
| `test_search_error_handling` | Mock `search_chunks` to raise, verify `RAGServiceException` + OpenAI never called |
| `test_empty_chunks_returns_response` | No chunks found, still calls OpenAI with empty context |
| `test_custom_top_k` | `top_k=3` forwarded to `search_chunks` |

---

## Step 4 — Run Tests

Execute the tests using Docker:

```bash
docker-compose exec backend pytest conversations/tests/test_rag_service.py -v
```

Or run all conversation tests:

```bash
docker-compose exec backend pytest conversations/tests/ -v
```

**Expected result:** All tests pass (green).

If any tests fail, debug and fix the issues:
1. Check if the test assertions match the actual implementation
2. Check if import paths are correct
3. Check if mock patch paths match the actual module structure
4. Fix either the implementation or the tests as needed

---

## Step 5 — Verify No Regressions

Run the full test suite to ensure no regressions:

```bash
docker-compose exec backend pytest -v
```

**Expected result:** All tests pass (the WIP context shows 382 tests passing previously).

---

## Implementation Order

1. **Verify settings** in `settings.py` — confirm all 4 settings exist
2. **Verify `rag_service.py`** — review all 5 functions + exception class + helper
3. **Verify `test_rag_service.py`** — review all test classes and methods
4. **Run tests** — fix any failures
5. **Run full suite** — ensure no regressions

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
- [ ] No regressions in existing tests

---

## Key Architecture Notes

### Mocking Strategy

The tests use `unittest.mock.patch` with **path-based mocking**. The patch paths target the module where the name is **used** (not where it's defined):

```python
@patch("conversations.rag_service.search_chunks")   # where search_chunks is imported/used
@patch("conversations.rag_service.embed_query")      # where embed_query is imported/used
@patch("conversations.rag_service.OpenAI")            # where OpenAI is imported/used
```

This is because `rag_service.py` does:
```python
from documents.services.embedding_service import embed_query
from documents.services.search_service import search_chunks
from openai import OpenAI
```

So patching `"conversations.rag_service.embed_query"` replaces the local reference in the `rag_service` module.

### Data Flow

```
User Question
    │
    ▼
embed_query(question) ──────────────────► [0.1, 0.2, ...] (768-dim vector)
    │
    ▼
search_chunks(document_id, query_vector, top_k) ──► list[chunk_dicts]
    │
    ▼
build_context(chunks) ──────────────────► "[Source 1 | Pages 1-3]\ncontent..."
    │
    ▼
build_system_prompt(title) ─────────────► system prompt string
    │
    ▼
OpenAI chat.completions.create(
    model=OPENAI_CHAT_MODEL,
    messages=[system, *history, user_with_context],
    max_tokens=OPENAI_CHAT_MAX_TOKENS,
) ─────────────────────────────────────► response
    │
    ▼
extract_citations(response, chunks) ───► [{"chunk_id": "...", ...}]
    │
    ▼
Result: {content, sources, token_usage, raw_chunks}
```

### Error Handling Flow

```
embed_query fails ──► RAGServiceException("Failed to embed question: ...")
search_chunks fails ──► RAGServiceException("Failed to search chunks: ...")
OpenAI API fails ──► RAGServiceException("OpenAI API call failed: ...")
```

### Settings Dependencies

| Setting | Env Var | Default | Used By |
|---------|---------|---------|---------|
| `OPENAI_API_KEY` | `OPENAI_API_KEY` | `''` | OpenAI client initialization |
| `OPENAI_CHAT_MODEL` | `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | `chat.completions.create(model=...)` |
| `OPENAI_CHAT_MAX_TOKENS` | `OPENAI_CHAT_MAX_TOKENS` | `1000` | `chat.completions.create(max_tokens=...)` |
| `RAG_MAX_HISTORY_TURNS` | `RAG_MAX_HISTORY_TURNS` | `10` | History truncation in `run_rag_query` |
| `RAG_CONTEXT_TOKEN_BUDGET` | `RAG_CONTEXT_TOKEN_BUDGET` | `4000` | Context trimming in `build_context` |
