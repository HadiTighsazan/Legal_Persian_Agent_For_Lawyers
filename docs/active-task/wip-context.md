# WIP Context — Task 4: Search View + URL Registration

## What Was Just Completed

Implemented `DocumentSearchView` (APIView), registered its URL pattern, and wrote 7 test methods following TDD (RED → GREEN → REFACTOR).

### View Added

1. **`DocumentSearchView`** in [`src/backend/documents/views.py`](src/backend/documents/views.py) — `POST /documents/<uuid:document_id>/search/`:
   - **Authentication:** `IsAuthenticated`
   - **Step 1:** Fetch document by ID → 404 `not_found` if missing
   - **Step 2:** Ownership check → 403 `permission_denied` if mismatch
   - **Step 3:** Processing status check → 422 `document_not_ready` if not `completed`
   - **Step 4:** Validate request body via `SearchRequestSerializer` → 400 on DRF validation failure
   - **Step 5:** Call `embed_query()` → 500 `embedding_failed` on `EmbeddingError`
   - **Step 6:** Call `search_chunks()` with `document_id`, `query_vector`, `top_k`, `min_score`
   - **Step 7:** Serialize response via `SearchResponseSerializer`
   - **Step 8:** Return 200 OK with results

### URL Registered

- [`src/backend/documents/urls.py`](src/backend/documents/urls.py) — Added:
  ```python
  path("<uuid:document_id>/search/", DocumentSearchView.as_view(), name="document-search")
  ```

### Tests Added

Added `DocumentSearchViewTests` class in [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) with 7 test methods:

1. `test_search_requires_auth` — POST without auth → 401
2. `test_search_document_not_found` — POST to non-existent UUID → 404 `not_found`
3. `test_search_document_wrong_user` — POST as other user → 403 `permission_denied`
4. `test_search_document_not_completed` — Document with `processing_status='processing'` → 422 `document_not_ready`
5. `test_search_valid_request` — Mock `embed_query` + `search_chunks`, assert 200 with correct response shape
6. `test_search_invalid_top_k` — `top_k=0` → 400 (DRF validation)
7. `test_search_empty_results` — Mock returns empty list → 200 with `results=[]` and `total_results=0`

## Current State of Code

- [`src/backend/documents/views.py`](src/backend/documents/views.py) — Added imports (`SearchRequestSerializer`, `SearchResponseSerializer`, `EmbeddingError`, `embed_query`, `search_chunks`) + `DocumentSearchView` class at end of file
- [`src/backend/documents/urls.py`](src/backend/documents/urls.py) — Added `DocumentSearchView` import + URL pattern
- [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) — Added `DocumentSearchViewTests` class with 7 test methods
- All **55 view tests pass** (48 existing + 7 new) — no regressions

## Next Step

No further steps for this task. The implementation is complete and all acceptance criteria are met:

- [x] `DocumentSearchView` implemented with all 8 steps (fetch, ownership, processing check, validation, embed, search, serialize, return)
- [x] Error handling matrix: 404 (not_found), 403 (permission_denied), 422 (document_not_ready), 400 (DRF validation), 500 (embedding_failed)
- [x] URL registered at `POST /documents/<uuid:document_id>/search/` with name `document-search`
- [x] All 7 test methods pass
- [x] No regressions in existing view tests (55 passed, 0 failed)
- [x] `docs/references/api-registry.md` updated with new endpoint
