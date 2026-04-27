# WIP Context — Task 1: `embed_query()` Implementation

## What Was Just Completed

Implemented `embed_query(text: str) -> list[float]` in the embedding service, following TDD flow:

### RED Phase
- Wrote 3 test methods in `EmbedQueryTests` class in [`test_embedding.py`](src/backend/documents/tests/test_embedding.py)
- Confirmed tests failed to collect (ImportError: `EmbeddingError` and `embed_query` didn't exist yet)

### GREEN Phase
1. **Added `EmbeddingError` exception** in [`embedding_service.py`](src/backend/documents/services/embedding_service.py) — a custom exception raised when embedding generation fails, allowing the view layer to catch it specifically.

2. **Added `embed_query()` function** in [`embedding_service.py`](src/backend/documents/services/embedding_service.py) — converts a search query string into a 768-dim vector using Ollama `nomic-embed-text` model. Key differences from `generate_embedding()`:
   - Empty/whitespace-only text raises `ValueError` (vs returning `None`)
   - API failure after retries raises `EmbeddingError` (vs returning `None`)
   - Return type is `list[float]` (guaranteed, vs `list[float] | None`)

### REFACTOR Phase
- No duplication issues — the retry logic intentionally mirrors `generate_embedding()` for clarity and independence.

## Current State of Code

- [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) — Contains `EmbeddingError` exception class and `embed_query()` function
- [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py) — Contains `EmbedQueryTests` class with 3 test methods
- All 59 tests pass (3 new + 56 existing)

## Next Step

No further steps for this task. The implementation is complete and all acceptance criteria are met:

- [x] `embed_query("hello world")` returns a `list[float]` of length 768
- [x] `EmbeddingError` is raised when Ollama is unreachable or returns HTTP error
- [x] `ValueError` is raised for empty/whitespace-only input
- [x] No new model, API key, or external dependency introduced
- [x] All 3 new tests pass (plus existing tests remain green)
