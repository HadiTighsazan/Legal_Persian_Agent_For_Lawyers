# WIP Context — Epic 6: Hybrid Search + Metadata Filtering

## Status: ✅ COMPLETED (2026-05-05)

All 10 steps of the Epic 6 Hybrid Search refactoring plan have been implemented and are ready for testing.

---

## Post-Epic Fix: 19 Test Failures Resolved (2026-05-05)

After implementing Epic 6, 19 tests were failing due to 5 root causes. All have been fixed:

### Root Cause 1: Wrong Mock Path — `search_chunks` → `hybrid_search`
- [`conversations/tests/test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py): Changed 9 `@patch("conversations.rag_service.search_chunks")` → `@patch("conversations.rag_service.hybrid_search")`, updated `test_custom_top_k` assertion to match `hybrid_search(document_id, query_vector, query_text, top_k, filters)` signature
- [`conversations/tests/test_integration.py`](src/backend/conversations/tests/test_integration.py): Changed 1 mock path
- [`documents/tests/test_views.py`](src/backend/documents/tests/test_views.py): Changed 2 mock paths (`test_search_valid_request`, `test_search_empty_results`) from `search_chunks` → `hybrid_search`

### Root Cause 2: `SearchResultSerializer` Test Data Missing Required Fields
- [`documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py): Added `page_start`, `page_end`, `token_count`, `metadata` to 3 test data dicts

### Root Cause 3: `SearchResponseSerializer` Test Data Missing Required Fields
- [`documents/serializers.py`](src/backend/documents/serializers.py): Added `required=False, default="hybrid"` to `search_mode`, `required=False, default=None` to `filters`
- [`documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py): Added `query`, `top_k`, `min_score` to 3 test data dicts

### Root Cause 4: pgvector Floating-Point Precision in Search Service Tests
- [`documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py): Changed `_medium_vector()` from `[1.0, 1.0, ...]` (cosine_sim ≈ 0.707) to `[1.0, 0.5, ...]` (cosine_sim ≈ 0.894) to ensure clear separation above `min_score=0.7`. Changed `_far_vector()` from `[0.0, 1.0, ...]` (cosine_sim = 0.0) to `[0.01, 1.0, ...]` (cosine_sim ≈ 0.01) to avoid floating-point issues with `relevance_score >= 0.0` filter.

### Root Cause 5: Search Integration Test 400 Error
- [`documents/serializers.py`](src/backend/documents/serializers.py): Added `allow_blank=True` to `legal_context` CharField (DRF rejects `None` on CharField without `allow_blank=True` even when `allow_null=True`)
- [`documents/tests/test_search_integration.py`](src/backend/documents/tests/test_search_integration.py): Updated `expected_keys` to include `legal_context`, `vector_score`, `keyword_score`, `rrf_score`; updated `_far_vector()` to match test_search_service.py

### Result
**575 tests pass**, 0 failures, 4 warnings, 80 subtests passed.

---

## What Was Completed

### Step 1: Persian Number Normalization for FTS
- Added `_PERSIAN_DIGITS` translation table to [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:46) mapping Arabic-Indic (U+0660–U+0669) and Persian (U+06F0–U+06F9) digits to English equivalents
- Added [`normalize_for_fts()`](src/backend/documents/services/persian_normalizer.py:276) static method that converts Persian/Arabic digits to English and replaces ZWNJ with spaces
- Added [`TestNormalizeForFts`](src/backend/documents/tests/test_persian_normalizer.py:217) test class with 8 test cases

### Step 2 & 3: Database Migration — FTS Search Vector + Metadata Fields
- Added to [`DocumentChunk`](src/backend/documents/models.py:82):
  - `search_vector = SearchVectorField(null=True, blank=True, editable=False)`
  - `law_name` (CharField, nullable, db_indexed)
  - `legal_status` (CharField, nullable, db_indexed)
  - `approval_date` (DateField, nullable, db_indexed)
  - `legal_type` (CharField, nullable, db_indexed)
- Added `GinIndex(fields=['search_vector'], name='chunk_search_vector_gin')` to `Meta.indexes`
- Created migration [`0006_add_fts_and_metadata_fields.py`](src/backend/documents/migrations/0006_add_fts_and_metadata_fields.py) that:
  - Adds all 5 new columns to `document_chunks`
  - Creates GIN index `chunk_search_vector_gin`
  - Creates PL/pgSQL function `update_chunk_search_vector()` using `to_tsvector('simple', ...)`
  - Creates trigger `trg_chunk_search_vector` (BEFORE INSERT OR UPDATE OF content)
  - Backfills `search_vector` for existing rows

### Step 4: Hybrid Search Service
- Rewrote [`search_service.py`](src/backend/documents/services/search_service.py) with:
  - [`_apply_metadata_filters()`](src/backend/documents/services/search_service.py:95) — applies WHERE clauses on denormalized columns (validates field names against `{"law_name", "legal_status", "approval_date", "legal_type"}`)
  - [`_build_result_dict()`](src/backend/documents/services/search_service.py:146) — standardized result dict builder
  - [`_rrf_fusion()`](src/backend/documents/services/search_service.py:174) — Reciprocal Rank Fusion with k=60, adds `vector_score`, `keyword_score`, `rrf_score` to results
  - [`_vector_search()`](src/backend/documents/services/search_service.py:246) — internal vector search with metadata filtering support
  - [`keyword_search()`](src/backend/documents/services/search_service.py:329) — PostgreSQL FTS using `SearchQuery(config="simple", search_type="websearch")` and `SearchRank`
  - [`hybrid_search()`](src/backend/documents/services/search_service.py:422) — runs both searches at RRF depth (max(top_k * 3, 60)), fuses via `_rrf_fusion`
  - [`search_chunks()`](src/backend/documents/services/search_service.py:497) — preserved for backward compatibility, delegates to `_vector_search`

### Step 5: Serializer Updates
- Updated [`SearchRequestSerializer`](src/backend/documents/serializers.py:203): Added `search_mode` (ChoiceField: hybrid/vector/keyword, default="hybrid"), `filters` (JSONField, allow_null=True)
- Updated [`SearchResultSerializer`](src/backend/documents/serializers.py:257): Added `legal_context`, `vector_score`, `keyword_score`, `rrf_score` (all optional/allow_null)
- Updated [`SearchResponseSerializer`](src/backend/documents/serializers.py:326): Added `search_mode`, `filters` fields

### Step 6: View Updates
- Updated [`DocumentSearchView.post()`](src/backend/documents/views.py:825): Routes to `keyword_search()` when `search_mode="keyword"`, `search_chunks()` when `"vector"`, `hybrid_search()` when `"hybrid"` (default). Only calls `embed_query()` for vector/hybrid modes.

### Step 7: RAG Service Update
- Updated [`run_rag_query()`](src/backend/conversations/rag_service.py:161) and [`run_rag_query_stream()`](src/backend/conversations/rag_service.py:274) to use `hybrid_search()` with `filters={"legal_status": "valid"}`

### Step 8: API Registry Documentation
- Updated [`docs/references/api-registry.md`](docs/references/api-registry.md) with hybrid search endpoint details, new request/response fields

### Step 9: Database Schema Documentation
- Updated [`docs/references/database-schema.md`](docs/references/database-schema.md) with new columns, indexes, and trigger info for `document_chunks`

### Step 10: Tests
- Added [`TestNormalizeForFts`](src/backend/documents/tests/test_persian_normalizer.py:217) — 8 tests for `normalize_for_fts()`
- Added [`ApplyMetadataFiltersTest`](src/backend/documents/tests/test_search_service.py:293) — 5 tests for `_apply_metadata_filters()`
- Added [`RrfFusionTest`](src/backend/documents/tests/test_search_service.py:373) — 6 tests for `_rrf_fusion()`
- Added [`KeywordSearchTest`](src/backend/documents/tests/test_search_service.py:466) — 4 tests for `keyword_search()`
- Added [`HybridSearchTest`](src/backend/documents/tests/test_search_service.py:554) — 3 tests for `hybrid_search()`
- Added serializer tests: `search_mode` defaults/validation, `filters` acceptance, `SearchResultSerializer` hybrid fields, `SearchResponseSerializer` fields
- Added view tests: hybrid mode, keyword mode, vector mode, hybrid with filters

---

## Files Changed Summary

| File | Action |
|------|--------|
| `src/backend/documents/services/persian_normalizer.py` | Modified (added `normalize_for_fts()`) |
| `src/backend/documents/models.py` | Modified (added `search_vector`, metadata fields, GIN index) |
| `src/backend/documents/migrations/0006_add_fts_and_metadata_fields.py` | **NEW** |
| `src/backend/documents/services/search_service.py` | Rewritten (hybrid search, RRF, keyword search) |
| `src/backend/documents/serializers.py` | Modified (added search_mode, filters, hybrid score fields) |
| `src/backend/documents/views.py` | Modified (hybrid/keyword routing in DocumentSearchView) |
| `src/backend/documents/tasks/document_processing.py` | Modified (populate denormalized metadata fields) |
| `src/backend/conversations/rag_service.py` | Modified (use hybrid_search with legal_status filter) |
| `src/backend/documents/tests/test_persian_normalizer.py` | Modified (added TestNormalizeForFts) |
| `src/backend/documents/tests/test_search_service.py` | Modified (added 4 test classes) |
| `src/backend/documents/tests/test_serializers.py` | Modified (added search_mode, filters, hybrid result tests) |
| `src/backend/documents/tests/test_views.py` | Modified (added hybrid/keyword/vector mode tests) |
| `docs/references/api-registry.md` | Modified (hybrid search docs) |
| `docs/references/database-schema.md` | Modified (new columns, indexes, trigger) |
| `docs/active-task/wip-context.md` | Modified (this file) |

---

## Next Steps / Verification

1. **Run migrations:** `docker-compose exec backend python manage.py migrate`
2. **Run backend tests:** `docker-compose exec backend pytest`
3. **Verify search modes via API:**
   - Default hybrid search: `POST /documents/{id}/search/` with `{"query": "..."}`
   - Keyword-only: `POST /documents/{id}/search/` with `{"query": "...", "search_mode": "keyword"}`
   - Vector-only (legacy): `POST /documents/{id}/search/` with `{"query": "...", "search_mode": "vector"}`
   - With filters: `POST /documents/{id}/search/` with `{"query": "...", "filters": {"legal_status": "valid"}}`
4. **Verify RAG responses** include filtered results (only valid laws)
