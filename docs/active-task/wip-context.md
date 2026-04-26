# WIP Context — Task 6: Chunks Retrieval API

## What Was Just Completed

**Task 6 — Implement `GET /documents/{document_id}/chunks/` endpoint** that returns paginated document chunks for a given document.

### Changes Made

| File | Change |
|------|--------|
| [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py:100) | Added `DocumentChunkSerializer` with 7 fields (id, chunk_index, page_start, page_end, content, token_count, metadata) |
| [`src/backend/documents/views.py`](src/backend/documents/views.py:238) | Added `DocumentChunksListView` — GET handler with ownership verification, pagination, and ordered-by-chunk_index query |
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py:30) | Registered `<uuid:document_id>/chunks/` route as `document-chunks` |
| [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py:431) | Added `DocumentChunksListViewTests` with 9 test cases |
| [`docs/references/api-registry.md`](docs/references/api-registry.md:437) | Documented the new endpoint with request/response format |

### Test Coverage (9 new tests)

| Test | What it verifies |
|------|-----------------|
| `test_nonexistent_document_returns_404` | 404 for non-existent document |
| `test_other_users_document_returns_403` | 403 for other user's document |
| `test_unauthenticated_request_returns_401` | 401 without auth |
| `test_empty_chunks_returns_200_with_empty_list` | 200 with empty results |
| `test_returns_chunks_in_order` | Chunks ordered by `chunk_index` ASC |
| `test_pagination_page_size` | `page_size` limits results |
| `test_pagination_second_page` | Page 2 returns correct slice |
| `test_pagination_last_page` | Last page has `next=None` |
| `test_response_format_contains_expected_fields` | All expected fields present |

### Test Results

- **All 36 document view tests pass** (0 failures, 0 errors)
- Tests run via: `docker-compose exec backend python -m pytest documents/tests/test_views.py --ds=config.settings -v`

### Reference Documentation Updated

- **`docs/references/api-registry.md`**: Added `GET /documents/{document_id}/chunks/` endpoint documentation with request/response format, error responses, and implementation notes

## Current State of Code

- `DocumentChunksListView` follows the same ownership-verification pattern as `DocumentProcessView` and `DocumentProcessingStatusView`
- Uses manual pagination (slice-based) instead of DRF's `PageNumberPagination` for consistency with existing patterns
- Returns `count`, `page`, `page_size`, `total_pages`, `next`, `previous`, `results` for full pagination metadata
- Handles invalid/negative page/page_size gracefully by falling back to defaults
- Chunks are ordered by `chunk_index` ASC
- `DocumentChunkSerializer` serializes all 7 fields from the `DocumentChunk` model

## Exact Next Step

Task 6 is complete. All 36 document view tests pass. The next task can proceed.
