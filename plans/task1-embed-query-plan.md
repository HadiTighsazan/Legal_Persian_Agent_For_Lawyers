# Task 1 — Embedding Service: `embed_query()` Implementation Plan

## Overview

Add a new `embed_query(text: str) -> list[float]` function to the existing [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) that converts a search query string into a 768-dim vector using the same Ollama `nomic-embed-text` model. Unlike the existing [`generate_embedding()`](src/backend/documents/services/embedding_service.py:67) which silently returns `None` on failure, this function **must raise an exception** so the view layer can return proper error responses.

---

## Files to Modify

| File | Action |
|---|---|
| [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) | Add `EmbeddingError` exception class + `embed_query()` function |
| [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py) | Add `EmbedQueryTests` test class with 3 test methods |

---

## Step 1 — Add `EmbeddingError` Exception

**File:** [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py)

**Location:** Insert after the constants block (line ~50) and before the helpers section (line ~57).

```python
class EmbeddingError(Exception):
    """Raised when embedding generation fails."""
    pass
```

**Rationale:** A custom exception allows the view layer to catch it specifically (via `except EmbeddingError`) rather than catching a broad `Exception`, which could mask unrelated bugs.

---

## Step 2 — Add `embed_query()` Function

**File:** [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py)

**Location:** Insert after [`generate_embedding()`](src/backend/documents/services/embedding_service.py:67) (ends at line 138) and before [`batch_generate_embeddings()`](src/backend/documents/services/embedding_service.py:141).

### Function Signature

```python
def embed_query(text: str) -> list[float]:
    """Convert a search query string into a 768-dim embedding vector.

    Args:
        text: The search query text (must be non-empty).

    Returns:
        A list of 768 floats representing the query embedding.

    Raises:
        EmbeddingError: If the Ollama API call fails or returns invalid data.
        ValueError: If *text* is empty or whitespace-only.
    """
```

### Implementation Logic

1. **Validate input:** If `not text or not text.strip()`, raise `ValueError("text must be non-empty")`.
2. **Reuse existing patterns:**
   - `_get_ollama_base_url()` for the base URL
   - `EMBEDDING_MODEL` constant (`nomic-embed-text`)
   - `_TIMEOUT_SECONDS` (60) and `_MAX_RETRIES` (3) constants
3. **Call `POST /api/embeddings`** (same endpoint as `generate_embedding()`).
4. **Retry logic:** Same exponential backoff pattern as `generate_embedding()`.
5. **On success:** Return `response.json()["embedding"]` (a `list[float]`).
6. **On failure (all retries exhausted):** Raise `EmbeddingError` with a descriptive message instead of returning `None`.

### Key Difference from `generate_embedding()`

| Aspect | `generate_embedding()` | `embed_query()` |
|---|---|---|
| Empty text | Returns `None` | Raises `ValueError` |
| API failure (after retries) | Returns `None` | Raises `EmbeddingError` |
| Return type | `list[float] \| None` | `list[float]` (guaranteed) |

### Pseudo-code

```python
def embed_query(text: str) -> list[float]:
    if not text or not text.strip():
        raise ValueError("text must be non-empty")

    base_url = _get_ollama_base_url()
    url = f"{base_url}/api/embeddings"

    for attempt in range(_MAX_RETRIES):
        try:
            response = requests.post(
                url,
                json={"model": EMBEDDING_MODEL, "prompt": text},
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            embedding: list[float] = response.json()["embedding"]
            logger.info("embed_query: Generated embedding (dimensions=%d)", len(embedding))
            return embedding

        except requests.exceptions.Timeout:
            if attempt < _MAX_RETRIES - 1:
                sleep_time = 2.0 ** attempt
                logger.warning("embed_query: Timeout, retrying in %.0fs (attempt %d/%d)", ...)
                time.sleep(sleep_time)
            else:
                logger.error("embed_query: Timeout after %d retries", _MAX_RETRIES)
                raise EmbeddingError("Ollama embedding request timed out after retries")

        except requests.exceptions.RequestException as e:
            if attempt < _MAX_RETRIES - 1:
                sleep_time = 2.0 ** attempt
                logger.warning("embed_query: Request failed (%s), retrying in %.0fs ...", e, ...)
                time.sleep(sleep_time)
            else:
                logger.error("embed_query: Request failed after %d retries — %s", _MAX_RETRIES, e)
                raise EmbeddingError(f"Ollama embedding request failed: {e}")

    raise EmbeddingError("Unexpected error in embed_query")
```

---

## Step 3 — Add Tests

**File:** [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py)

**Location:** Insert after the `GenerateEmbeddingTests` class (ends around line 216) and before `BatchGenerateEmbeddingsTests` (starts at line 218).

### Test Class: `EmbedQueryTests`

#### Test 1: `test_embed_query_returns_768_floats`

- **Purpose:** Verify that a valid query returns a list of exactly 768 floats.
- **Approach:** Mock `requests.post` to return a fake Ollama response with a 768-dim embedding.
- **Assertions:**
  - `len(result) == 768`
  - The returned list matches the mock embedding
  - `requests.post` was called with the correct URL, JSON payload, and timeout

#### Test 2: `test_embed_query_raises_on_ollama_failure`

- **Purpose:** Verify that `EmbeddingError` is raised when Ollama is unreachable or returns an error.
- **Approach:** Mock `requests.post` to raise a `Timeout` or `ConnectionError` on every call (all retries exhausted).
- **Assertions:**
  - `assertRaises(EmbeddingError)` context manager passes
  - The exception message contains relevant info

#### Test 3: `test_embed_query_raises_on_empty_text`

- **Purpose:** Verify that empty or whitespace-only input raises `ValueError`.
- **Approach:** Call `embed_query("")`, `embed_query("   ")`, `embed_query("\n\t")`.
- **Assertions:**
  - Each call raises `ValueError`
  - No HTTP request is made (verify `requests.post` is not called)

### Import to Add

```python
from documents.services.embedding_service import (
    ...existing imports...,
    EmbeddingError,
    embed_query,
)
```

---

## Execution Order (for Code Mode)

1. **RED** — Write the 3 test methods in [`test_embedding.py`](src/backend/documents/tests/test_embedding.py) first. Run them to confirm they fail.
2. **GREEN** — Add `EmbeddingError` exception and `embed_query()` function to [`embedding_service.py`](src/backend/documents/services/embedding_service.py). Run tests to confirm they pass.
3. **REFACTOR** — Verify no duplication issues. The retry logic is intentionally duplicated (same pattern as `generate_embedding()`) for clarity and independence.

---

## Mermaid Diagram: Call Flow

```mermaid
flowchart TD
    A[View Layer] -->|calls| B[embed_query text]
    B --> C{text valid?}
    C -->|No| D[raise ValueError]
    C -->|Yes| E[POST /api/embeddings]
    E --> F{Success?}
    F -->|Yes| G[return list[float] len=768]
    F -->|No| H{Retries left?}
    H -->|Yes| I[exponential backoff]
    I --> E
    H -->|No| J[raise EmbeddingError]
```

---

## Acceptance Criteria

- [ ] `embed_query("hello world")` returns a `list[float]` of length 768
- [ ] `EmbeddingError` is raised when Ollama is unreachable or returns HTTP error
- [ ] `ValueError` is raised for empty/whitespace-only input
- [ ] No new model, API key, or external dependency introduced
- [ ] All 3 new tests pass (plus existing tests remain green)
- [ ] [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) is updated after completion
