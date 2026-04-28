# WIP Context — Task 5: ivfflat Index Probe Tuning

## What Was Just Completed

Added pgvector `ivfflat.probes` session-level configuration to improve recall/performance trade-off for similarity searches. The probes setting controls how many lists are searched during an ivfflat index scan — higher values improve recall but slow down queries.

### Files Modified

1. **`src/backend/config/settings.py`** — Added `VECTOR_SEARCH_PROBES=(int, 10)` to the `env` constructor's default casting block (line 32), and a dedicated setting line `VECTOR_SEARCH_PROBES = env("VECTOR_SEARCH_PROBES")` after the Embedding Provider section (line 245).

2. **`.env.example`** — Added `VECTOR_SEARCH_PROBES=10` under the Application-Specific Configuration section with a comment explaining the valid range (1-100) and trade-off.

3. **`src/backend/documents/services/search_service.py`** — Added imports for `django.conf.settings` and `django.db.connection`. Added `_set_probes()` helper function that executes `SET ivfflat.probes = %s` via a raw cursor. Called `_set_probes()` at the beginning of `search_chunks()` before the queryset is built.

4. **`src/backend/documents/tests/test_search_service.py`** — Added `from unittest.mock import patch` and `from django.db import connection` imports. Added `test_search_service_sets_probes` test method that verifies `_set_probes()` executes `SET ivfflat.probes = %s` with the correct value using a mocked cursor.

### Test Results

```
documents/tests/test_search_service.py::SearchChunksTest::test_search_chunks_empty_result PASSED
documents/tests/test_search_service.py::SearchChunksTest::test_search_chunks_excludes_unembedded_chunks PASSED
documents/tests/test_search_service.py::SearchChunksTest::test_search_chunks_filters_by_min_score PASSED
documents/tests/test_search_service.py::SearchChunksTest::test_search_chunks_orders_by_relevance PASSED
documents/tests/test_search_service.py::SearchChunksTest::test_search_chunks_returns_top_k PASSED
documents/tests/test_search_service.py::SearchChunksTest::test_search_service_sets_probes PASSED
```

**6/6 tests pass** (5 existing + 1 new).

## Current State of Code

- [`src/backend/config/settings.py`](src/backend/config/settings.py) — `VECTOR_SEARCH_PROBES` setting added with default value 10
- [`.env.example`](.env.example) — `VECTOR_SEARCH_PROBES=10` documented
- [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) — `_set_probes()` helper added, called at start of `search_chunks()`
- [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) — New test `test_search_service_sets_probes` added

## Next Step

No further steps. Task 5 is complete and verified.

### Acceptance Criteria

- [x] `VECTOR_SEARCH_PROBES` setting added to `settings.py` with default `10`
- [x] `VECTOR_SEARCH_PROBES=10` added to `.env.example` with explanatory comment
- [x] `_set_probes()` helper added to `search_service.py` — executes `SET ivfflat.probes = %s`
- [x] `_set_probes()` called at the beginning of `search_chunks()` before queryset construction
- [x] New test `test_search_service_sets_probes` verifies the SQL execution via mocked cursor
- [x] All 6 tests pass (5 existing + 1 new)
