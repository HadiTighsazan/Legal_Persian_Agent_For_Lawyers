# WIP Context — Task 2: `search_chunks()` Implementation

## What Was Just Completed

Implemented `search_chunks()` — a pure service function for cosine similarity search against `DocumentChunk` embeddings using pgvector's `CosineDistance` annotation. Followed TDD flow:

### RED Phase
- Created [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) with 5 test methods:
  1. `test_search_chunks_returns_top_k` — verifies `top_k` limits results
  2. `test_search_chunks_filters_by_min_score` — verifies `min_score` threshold filtering
  3. `test_search_chunks_excludes_unembedded_chunks` — verifies NULL embeddings are excluded
  4. `test_search_chunks_orders_by_relevance` — verifies descending `relevance_score` ordering
  5. `test_search_chunks_empty_result` — verifies empty document returns `[]`
- Confirmed tests failed to collect with `ModuleNotFoundError` (service module didn't exist)

### GREEN Phase
- Created [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) with `search_chunks()` function
- Uses pgvector's `CosineDistance` annotation (no raw SQL)
- Computes `relevance_score = 1 - distance` via Django `F` expressions
- Filters by `relevance_score__gte=min_score`, orders by `distance ASC`, limits via `[:top_k]`
- Returns `list[dict]` with keys: `chunk_id`, `chunk_index`, `page_start`, `page_end`, `content`, `relevance_score`, `token_count`, `metadata`
- All 5 tests passed on first run after fixing test vector math (collinear vectors gave distance=0)

### REFACTOR Phase
- Test vectors use two non-zero components for predictable cosine distances (documented with full math)
- Service function is clean, well-documented, follows existing service-layer pattern (standalone functions)
- No HTTP `request` object dependency — pure service function

## Current State of Code

- [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) — New file with `search_chunks()` function
- [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) — New file with 5 test methods
- All 205 document tests pass (5 new + 200 existing) — no regressions

## Next Step

No further steps for this task. The implementation is complete and all acceptance criteria are met:

- [x] `search_chunks()` is a pure function with no HTTP `request` object
- [x] Uses pgvector `CosineDistance` annotation (not raw SQL)
- [x] NULL embeddings are excluded from results
- [x] Results are ordered by `relevance_score` descending (highest first)
- [x] `top_k` limits the number of results
- [x] `min_score` filters out low-relevance chunks
- [x] Empty results return `[]` (not `None`)
- [x] All 5 tests pass
- [x] No regressions in existing test suite (205 passed, 0 failed)
