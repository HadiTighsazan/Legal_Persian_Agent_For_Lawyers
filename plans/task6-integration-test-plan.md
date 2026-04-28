# Task 6 — Integration Test & API Registry Update

## Overview

This is the final task of Epic E06 (Semantic Search & Retrieval). It creates an end-to-end integration test that exercises the full search pipeline against a real test database with pgvector, and updates the API registry to mark the endpoint as implemented.

## Files to Create/Modify

| File | Action |
|---|---|
| `src/backend/documents/tests/test_search_integration.py` | **Create new** |
| `docs/references/api-registry.md` | Update implementation status |

## Prerequisites (Already Done)

All Tasks 1–5 are complete and verified:
- ✅ `embed_query()` in `embedding_service.py` (Task 1)
- ✅ `search_chunks()` in `search_service.py` (Task 2)
- ✅ `SearchRequestSerializer`, `SearchResultSerializer`, `SearchResponseSerializer` (Task 3)
- ✅ `DocumentSearchView` + URL registration (Task 4)
- ✅ `ivfflat.probes` tuning in `search_service.py` (Task 5)
- ✅ All 19+ unit tests pass

---

## Step 1 — Create Integration Test

**File:** `src/backend/documents/tests/test_search_integration.py`

### Design

The integration test follows the same patterns established in:
- [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) — uses `_make_vector()`, `_query_vector()`, etc. helpers
- [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) — uses `APIClient`, `_auth_header()`, `_create_document()`

### Test Class: `DocumentSearchIntegrationTest`

**Decorator:** `@pytest.mark.django_db(transaction=True)` — uses transaction=True because pgvector operations may require transactional isolation.

**`setUp()`:**
1. Create a user via `User.objects.create_user(email=..., password=...)`
2. Create a document with `processing_status='completed'` using the existing `_create_document()` helper pattern
3. Create 3 chunks with **known real embedding vectors** using the same `_make_vector()` helper from `test_search_service.py`:
   - Chunk 0: `_query_vector()` = `[1.0, 0.0, 0.0, ...]` — content "Exact match chunk"
   - Chunk 1: `_close_vector()` = `[1.0, 0.1, 0.0, ...]` — content "Close match chunk"
   - Chunk 2: `_far_vector()` = `[0.0, 1.0, 0.0, ...]` — content "Distant match chunk"
4. Set up `APIClient` and compute the search URL via `reverse("documents:document-search", kwargs={"document_id": doc.id})`

### Test: `test_search_integration_end_to_end`

**Goal:** Verify the full search pipeline works end-to-end.

**Steps:**
1. **Mock only `embed_query`** at `documents.views.embed_query` to return `_query_vector()` (the vector that matches chunk 0 perfectly)
2. **Send POST** to the search URL with `{"query": "test query", "top_k": 5}`
3. **Assertions:**
   - Response status is `200 OK`
   - `total_results >= 1`
   - First result has the **highest** `relevance_score` (i.e., results are ordered descending by relevance)
   - The first result's `chunk_id` matches chunk 0 (the exact match)
   - Response contains all expected keys: `results`, `query`, `top_k`, `min_score`, `total_results`
   - Each result contains: `chunk_id`, `chunk_index`, `page_start`, `page_end`, `content`, `relevance_score`, `token_count`, `metadata`

### Key Design Decisions

1. **Mock only `embed_query`** — This is the only external dependency (Gemini API call). The `search_chunks()` function runs against real pgvector in the test DB, giving us a true integration test of the vector similarity search.
2. **Use `_make_vector()` helper** — Reuses the same well-tested helper from `test_search_service.py` to create deterministic embedding vectors with known cosine distances.
3. **Use `APIClient`** — Same as `test_views.py`, exercises the full Django request/response cycle including auth, URL routing, serialization, and error handling.
4. **`transaction=True`** — Required because pgvector's `CosineDistance` may need transactional isolation for the `ivfflat.probes` setting to take effect properly.

### Expected Behavior

Given the three chunks with embeddings:
- Chunk 0: `[1.0, 0.0, ...]` (query vector)
- Chunk 1: `[1.0, 0.1, ...]` (close vector, distance ≈ 0.005)
- Chunk 2: `[0.0, 1.0, ...]` (far vector, distance = 1.0)

When `embed_query` returns `[1.0, 0.0, ...]`:
- Chunk 0: relevance_score ≈ 1.0 (distance ≈ 0.0)
- Chunk 1: relevance_score ≈ 0.995 (distance ≈ 0.005)
- Chunk 2: relevance_score ≈ 0.0 (distance = 1.0)

Results should be ordered: Chunk 0 > Chunk 1 > Chunk 2 (if min_score allows all three).

---

## Step 2 — Update API Registry

**File:** `docs/references/api-registry.md`

### Changes to Make

The `POST /documents/{document_id}/search/` entry is at lines 798-838 under the **Search & Retrieval** section. The entry already has:
- `Implementation Date: 2026-04-27`
- `Test Coverage: 7 view tests (DocumentSearchViewTests)`
- `View Class: DocumentSearchView`

**Add the following after the existing `View Class` line:**
- `**Status:** ✅ Implemented`
- `**Implementation Notes:** Uses `embed_query()` from the embedding service to vectorize the search query, then `search_chunks()` from the search service to perform cosine similarity search via pgvector's `<=>` operator. Results are ordered by relevance_score descending. The `ivfflat.probes` session parameter is set before each query for performance tuning.`

**Update `Test Coverage` to include the integration test:**
- Change `7 view tests (DocumentSearchViewTests)` to `7 view tests + 1 integration test (DocumentSearchViewTests + DocumentSearchIntegrationTest)`

---

## Step 3 — Verify No Regressions

After creating the test file and updating the registry, run:
```bash
docker-compose exec backend pytest documents/tests/ --tb=short -v
```

Expected: All existing tests pass + the new integration test passes.

---

## Execution Order

```
Step 1: Create test_search_integration.py
    ↓
Step 2: Update api-registry.md
    ↓
Step 3: Run full test suite to verify no regressions
```

## Acceptance Criteria

- [ ] Integration test passes against test DB with pgvector extension
- [ ] `api-registry.md` is updated with correct implementation status and notes
- [ ] All unit tests from Tasks 1–5 pass (`pytest --tb=short`)
- [ ] No regression in existing test suite
