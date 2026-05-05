# Fix Plan: 19 Test Failures After Epic 6 Hybrid Search Refactoring

## Overview

After implementing Epic 6 (Hybrid Search + Metadata Filtering), 19 tests are failing. This document identifies the 5 root causes and provides a step-by-step fix plan.

---

## Root Cause Analysis

### Root Cause 1: Wrong Mock Path — `conversations.rag_service.search_chunks` doesn't exist

**Problem:** The [`run_rag_query()`](src/backend/conversations/rag_service.py:161) function now calls [`hybrid_search()`](src/backend/conversations/rag_service.py:210) (imported at line 24 from `documents.services.search_service`), NOT `search_chunks()`. However, all tests in both test files still mock `conversations.rag_service.search_chunks`, which no longer exists as a reference in that module.

**Affected Tests (11 failures):**
- [`conversations/tests/test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py) — All 9 tests in `RunRagQueryTests`:
  - `test_normal_response` (line 212)
  - `test_citation_extraction_integration` (line 269)
  - `test_history_truncation` (line 326)
  - `test_chat_provider_error_handling` (line 379)
  - `test_embedding_error_handling` (line 403)
  - `test_search_error_handling` (line 426)
  - `test_empty_chunks_returns_response` (line 450)
  - `test_custom_top_k` (line 486)
- [`conversations/tests/test_integration.py`](src/backend/conversations/tests/test_integration.py) — `test_rag_service_integration` (line 184)

**Fix:** Change all `@patch("conversations.rag_service.search_chunks")` to `@patch("conversations.rag_service.hybrid_search")`.

Additionally, the `test_custom_top_k` test (line 486) asserts `mock_search_chunks.assert_called_once_with(document_id=..., query_vector=..., top_k=3)`. But `hybrid_search` has a different signature: `hybrid_search(document_id, query_vector, query_text, top_k, min_score, filters)`. The test needs to be updated to match the `hybrid_search` call signature.

---

### Root Cause 2: `SearchResultSerializer` Test Data Missing Required Fields

**Problem:** The [`SearchResultSerializer`](src/backend/documents/serializers.py:257) requires these fields: `chunk_id`, `chunk_index`, `page_start`, `page_end`, `content`, `relevance_score`, `token_count`, `metadata`. The `page_start`, `page_end`, `token_count`, and `metadata` fields are **required** (no `required=False`).

But the test data in 3 serializer tests omits `page_start`, `page_end`, `token_count`, and `metadata`:

**Affected Tests (3 failures):**
- [`test_minimal_result_passes`](src/backend/documents/tests/test_serializers.py:697) — data only has `chunk_id`, `chunk_index`, `content`, `relevance_score`
- [`test_hybrid_result_fields`](src/backend/documents/tests/test_serializers.py:707) — data only has `chunk_id`, `chunk_index`, `content`, `relevance_score`, `vector_score`, `keyword_score`, `rrf_score`
- [`test_hybrid_result_fields_optional`](src/backend/documents/tests/test_serializers.py:730) — data only has `chunk_id`, `chunk_index`, `content`, `relevance_score`

**Fix:** Add the missing required fields (`page_start`, `page_end`, `token_count`, `metadata`) to all three test data dicts.

---

### Root Cause 3: `SearchResponseSerializer` Test Data Missing Required Fields

**Problem:** The [`SearchResponseSerializer`](src/backend/documents/serializers.py:326) requires these fields: `results`, `query`, `top_k`, `min_score`, `search_mode`, `filters`, `total_results`. The `query`, `top_k`, and `min_score` fields are **required** (no `required=False`).

But the test data in 3 serializer tests omits `query`, `top_k`, and `min_score`:

**Affected Tests (3 failures):**
- [`test_response_contains_search_mode_and_filters`](src/backend/documents/tests/test_serializers.py:753) — data only has `results`, `total_results`, `search_mode`, `filters`
- [`test_response_search_mode_defaults_to_hybrid`](src/backend/documents/tests/test_serializers.py:769) — data only has `results`, `total_results`
- [`test_response_filters_defaults_to_none`](src/backend/documents/tests/test_serializers.py:778) — data only has `results`, `total_results`

**Fix:** Add the missing required fields (`query`, `top_k`, `min_score`) to all three test data dicts.

---

### Root Cause 4: `search_chunks` Precision/Filtering Issues (2 tests)

**Problem:** Two tests in [`test_search_service.py`](src/backend/documents/tests/test_search_service.py) are failing with unexpected result counts:

1. [`test_search_chunks_filters_by_min_score`](src/backend/documents/tests/test_search_service.py:183) — Expects 3 results with `min_score=0.7`, gets 2. The `_medium_vector()` chunk has a theoretical relevance of ~0.707, which should pass. Possible pgvector floating-point precision issue where the computed score is slightly below 0.7.

2. [`test_search_chunks_orders_by_relevance`](src/backend/documents/tests/test_search_service.py:230) — Expects 4 results, gets 2. This is likely the same precision issue affecting the `_medium_vector()` and `_far_vector()` chunks.

**Investigation needed:** The exact cause needs to be determined by examining the actual relevance scores returned by pgvector. Possible causes:
- pgvector `CosineDistance` computation differs slightly from the mathematical expectation
- The `_vector_search` function's `min_score` filter (line 297) is filtering out chunks with scores just below the threshold
- Some other query-level issue

**Fix:** 
1. First, add debug logging or a diagnostic test to see actual scores
2. Adjust test expectations or adjust the test vectors to ensure clear separation above/below thresholds
3. If it's a precision issue, lower the `min_score` threshold slightly in the test or adjust the test vectors

---

### Root Cause 5: Search Integration Test Returns 400 Instead of 200

**Problem:** [`test_search_integration_end_to_end`](src/backend/documents/tests/test_search_integration.py:173) sends a valid search request but gets HTTP 400 instead of 200.

The test mocks `documents.views.embed_query` but does NOT mock `search_chunks` or `hybrid_search`. Since the view now routes to `hybrid_search` by default (line 898-907), the real `hybrid_search` runs against the test database.

The 400 status likely comes from the `SearchResponseSerializer` validation at line 919-920. The `hybrid_search` function returns results via `_rrf_fusion`, which adds `vector_score`, `keyword_score`, and `rrf_score` keys. These extra keys should be fine since the serializer has them as optional.

However, the real issue might be that the `SearchResponseSerializer` validation fails because the response data structure doesn't match expectations. Or it could be that the `SearchRequestSerializer` validation is failing for some reason.

**Investigation needed:** Determine the exact validation error. The most likely cause is that the `SearchResponseSerializer` is rejecting the data because of missing or extra fields.

**Fix:** 
1. Identify the exact validation error (add debug logging or check the serializer errors)
2. Adjust either the test data or the serializer expectations accordingly

---

## Fix Plan — Step by Step

### Step 1: Fix Mock Paths in Conversations Tests (Root Cause 1)

**Files to modify:**
- `src/backend/conversations/tests/test_rag_service.py`
- `src/backend/conversations/tests/test_integration.py`

**Changes:**
1. In `test_rag_service.py`: Replace all 9 instances of `@patch("conversations.rag_service.search_chunks")` with `@patch("conversations.rag_service.hybrid_search")`
2. In `test_integration.py`: Replace `@patch("conversations.rag_service.search_chunks")` with `@patch("conversations.rag_service.hybrid_search")` (line 184)
3. In `test_rag_service.py::test_custom_top_k` (line 486): Update the `mock_search_chunks.assert_called_once_with(...)` assertion to match `hybrid_search`'s signature: `hybrid_search(document_id=..., query_vector=..., query_text=..., top_k=3, min_score=0.0, filters={"legal_status": "valid"})`

### Step 2: Fix SearchResultSerializer Test Data (Root Cause 2)

**File to modify:** `src/backend/documents/tests/test_serializers.py`

**Changes:**
1. In `test_minimal_result_passes` (line 697): Add `"page_start": 1, "page_end": 2, "token_count": 10, "metadata": {}`
2. In `test_hybrid_result_fields` (line 707): Add `"page_start": 1, "page_end": 2, "token_count": 10, "metadata": {}`
3. In `test_hybrid_result_fields_optional` (line 730): Add `"page_start": 1, "page_end": 2, "token_count": 10, "metadata": {}`

### Step 3: Fix SearchResponseSerializer Test Data (Root Cause 3)

**File to modify:** `src/backend/documents/tests/test_serializers.py`

**Changes:**
1. In `test_response_contains_search_mode_and_filters` (line 753): Add `"query": "test", "top_k": 10, "min_score": 0.0`
2. In `test_response_search_mode_defaults_to_hybrid` (line 769): Add `"query": "test", "top_k": 10, "min_score": 0.0`
3. In `test_response_filters_defaults_to_none` (line 778): Add `"query": "test", "top_k": 10, "min_score": 0.0`

### Step 4: Investigate and Fix Search Service Tests (Root Cause 4)

**File to modify:** `src/backend/documents/tests/test_search_service.py`

**Approach:**
1. First, add a diagnostic test to print actual relevance scores from `_vector_search`
2. If precision is the issue, adjust the `_medium_vector()` to have a higher theoretical score (e.g., `[1.0, 0.5, 0.0, ...]` instead of `[1.0, 1.0, 0.0, ...]`) to ensure it's clearly above 0.7
3. Alternatively, lower the `min_score` threshold in the test to `0.69` to account for floating-point variance

### Step 5: Fix Search Integration Test (Root Cause 5)

**File to modify:** `src/backend/documents/tests/test_search_integration.py`

**Approach:**
1. Run the test with debug output to see the actual 400 error details
2. The most likely fix is to ensure the response data matches the `SearchResponseSerializer` expectations
3. If the issue is that `hybrid_search` returns results with extra keys (`vector_score`, `keyword_score`, `rrf_score`) that the test's `expected_keys` check doesn't account for, update the `expected_keys` set at line 223

### Step 6: Run Tests and Verify

Run the full test suite:
```bash
docker-compose exec backend pytest
```

Verify that all 19 previously failing tests now pass and no regressions were introduced.

### Step 7: Update Documentation

Update `docs/active-task/wip-context.md` with the fix summary.

---

## Summary of Changes

| File | Changes |
|------|---------|
| `src/backend/conversations/tests/test_rag_service.py` | Fix 9 mock paths + 1 assertion signature |
| `src/backend/conversations/tests/test_integration.py` | Fix 1 mock path |
| `src/backend/documents/tests/test_serializers.py` | Add missing required fields to 6 test data dicts |
| `src/backend/documents/tests/test_search_service.py` | Adjust test vectors/thresholds for precision |
| `src/backend/documents/tests/test_search_integration.py` | Fix expected_keys or response handling |
