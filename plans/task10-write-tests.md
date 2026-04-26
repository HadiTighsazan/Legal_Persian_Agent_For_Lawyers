# Task 10: Write Tests — Implementation Plan

## Objective

Create a comprehensive test file at [`src/backend/tests/test_processing.py`](src/backend/tests/test_processing.py) covering the document processing pipeline across three categories: **Chunking Service** (pure unit tests), **Task Tests** (DB + Celery), and **API Endpoint Tests** (DB + HTTP).

---

## Background Context

The existing test suite already has thorough coverage in:
- [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py) — 32 tests for `extract_text_from_pdf`, `chunk_document`, `process_document`, `_handle_chain_error`
- [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) — 48 tests for all 5 API views
- [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py) — 28 tests for serializers

**Key insight:** The user's Task 10 specification describes tests that **overlap significantly** with existing tests. The new file at [`src/backend/tests/test_processing.py`](src/backend/tests/test_processing.py) should focus on **gaps not yet covered** by the existing tests, while also providing a consolidated integration-style test file.

---

## Test Categories & Detailed Plan

### Category 1: Chunking Service Tests (Unit Tests, No DB Needed)

**Target:** [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py) — `ChunkingService.chunk_text()`

These are pure unit tests that instantiate `ChunkingService` directly and call `chunk_text()` with various inputs. No database or Celery needed.

| # | Test Name | What It Verifies | Status in Existing Tests |
|---|-----------|-----------------|--------------------------|
| 1 | `test_chunk_text_short_text_returns_one_chunk` | Text ≤ chunk_size → exactly 1 chunk | ❌ Not covered |
| 2 | `test_chunk_text_long_text_returns_multiple_chunks` | Text > chunk_size → multiple chunks | ❌ Not covered (task tests use ChunkingService indirectly) |
| 3 | `test_chunk_text_overlap_is_correct` | Consecutive chunks share `overlap` characters | ❌ Not covered |
| 4 | `test_chunk_text_preserves_sentence_boundaries` | Split occurs at sentence boundary (`.`, `!`, `?`) not mid-sentence | ❌ Not covered |
| 5 | `test_chunk_text_token_count_calculation` | `token_count` matches tiktoken encoding | ❌ Not covered |
| 6 | `test_chunk_text_empty_text_returns_empty_list` | Empty string → `[]` | ❌ Not covered (task tests test empty text at task level) |
| 7 | `test_chunk_text_page_number_tracking` | `page_start`/`page_end` correctly resolved from `[PAGE N]` markers | ❌ Not covered |

**Implementation notes:**
- Use `from documents.services.chunking_service import ChunkingService`
- Instantiate `ChunkingService()` directly (no mocks needed)
- For token count verification, use `tiktoken.get_encoding("cl100k_base")` to compute expected counts
- For overlap test: create text with known pattern, verify chunk N's end overlaps with chunk N+1's start
- For sentence boundary test: create text with long sentence that would be split mid-sentence if not for boundary preservation
- For page tracking: inject `[PAGE 1]` and `[PAGE 2]` markers and verify `page_start`/`page_end`

---

### Category 2: Task Tests (Require DB + Celery Mocking)

**Target:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)

These tests require a database (Django `TestCase`) and mock Celery's `@shared_task` machinery. **Most of these are already covered** in [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py). The new tests should focus on gaps.

| # | Test Name | What It Verifies | Status in Existing Tests |
|---|-----------|-----------------|--------------------------|
| 8 | `test_extract_text_from_pdf_valid_pdf` | Valid PDF → extracted text with page markers | ✅ Covered (`test_extracts_text_with_page_markers`) |
| 9 | `test_extract_text_from_pdf_corrupted_pdf` | Corrupted PDF → status `failed` | ✅ Covered (`test_corrupted_pdf_sets_failed_status`) |
| 10 | `test_extract_text_from_pdf_empty_pdf` | Empty PDF → empty result | ✅ Covered (`test_empty_pdf_returns_empty_string`) |
| 11 | `test_chunk_document_with_extracted_text` | Valid text → chunks created in DB | ✅ Covered (`test_creates_chunks_from_text`) |
| 12 | `test_chunk_document_empty_text_zero_chunks` | Empty text → 0 chunks | ✅ Covered (`test_empty_text_sets_zero_chunks`) |
| 13 | `test_process_document_orchestration_chain` | Chain is built with correct tasks | ✅ Covered (`test_builds_celery_chain`) |

**Decision:** Since all 6 task tests are already covered by existing tests in [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py), **do not duplicate them**. Instead, add a **single integration-style test** that exercises the full pipeline end-to-end with mocked Celery:

| # | Test Name | What It Verifies | Notes |
|---|-----------|-----------------|-------|
| 13 (new) | `test_full_pipeline_integration` | Creates a real PDF, calls `process_document`, verifies ProcessingTask created, mocks Celery chain execution | New — integration test |

---

### Category 3: API Endpoint Tests (Require DB + HTTP)

**Target:** [`src/backend/documents/views.py`](src/backend/documents/views.py) — All 5 views

These tests use Django's `APIClient` to make HTTP requests. **Most are already covered** in [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py).

| # | Test Name | What It Verifies | Status in Existing Tests |
|---|-----------|-----------------|--------------------------|
| 14 | `POST /documents/{id}/process` → 202 | Happy path returns 202 | ✅ Covered (`test_starts_processing_and_returns_202`) |
| 15 | `POST /documents/{id}/process` with non-existent doc → 404 | Non-existent ID returns 404 | ✅ Covered (`test_nonexistent_document_returns_404`) |
| 16 | `GET /documents/{id}/processing-status` → 200 | Status endpoint returns 200 | ✅ Covered (multiple tests) |
| 17 | `GET /documents/{id}/chunks` → 200 with pagination | Paginated chunks response | ✅ Covered (multiple pagination tests) |
| 18 | `GET /documents/{id}/chunks` with empty doc → 200 empty list | Empty chunks returns 200 with `[]` | ✅ Covered (`test_empty_chunks_returns_200_with_empty_list`) |
| 19 | `POST /processing-tasks/{id}/retry` → 200 | Successful retry returns 200 | ✅ Covered (`test_successful_retry_returns_200`) |
| 20 | `POST /processing-tasks/{id}/retry` with max retries → 400 | Max retries returns 400 | ✅ Covered (`test_max_retries_exceeded_returns_400`) |
| 21 | Auth required for all endpoints | 401 without JWT | ✅ Covered (all views have `test_unauthenticated_request_returns_401`) |

**Decision:** All 8 API endpoint tests are already covered. **Do not duplicate them.**

---

## Final Test List for `src/backend/tests/test_processing.py`

Based on the gap analysis, here is the **consolidated test file** to create:

### ChunkingService Unit Tests (7 tests — all new)

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_chunk_text_short_text_returns_one_chunk` | Text of 50 chars with chunk_size=1000 → 1 chunk |
| 2 | `test_chunk_text_long_text_returns_multiple_chunks` | Text of 3000 chars with chunk_size=1000 → 3+ chunks |
| 3 | `test_chunk_text_overlap_is_correct` | Two chunks should share ~200 chars of overlap |
| 4 | `test_chunk_text_preserves_sentence_boundaries` | Split at `.` not mid-word |
| 5 | `test_chunk_text_token_count_calculation` | `token_count` matches `len(encoding.encode(content))` |
| 6 | `test_chunk_text_empty_text_returns_empty_list` | `""` → `[]` |
| 7 | `test_chunk_text_page_number_tracking` | `[PAGE 1]` and `[PAGE 2]` markers → correct `page_start`/`page_end` |

### Integration Test (1 test — new)

| # | Test Method | Description |
|---|-------------|-------------|
| 8 | `test_full_pipeline_integration` | Create real PDF → upload → process_document → verify ProcessingTask created with correct status |

### API Auth Tests (1 consolidated test — new, covers gap)

| # | Test Method | Description |
|---|-------------|-------------|
| 9 | `test_all_endpoints_require_authentication` | Parametrized: hit all 5 endpoints without auth → all return 401 |

**Total: 9 new tests**

---

## Implementation Details

### File Structure

```python
"""
Tests for the document processing pipeline.

Covers:
- ChunkingService unit tests (no DB)
- Full pipeline integration test (DB + mocked Celery)
- Authentication requirement for all processing endpoints
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import MagicMock, PropertyMock, patch

import fitz
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import Document
from documents.services.chunking_service import ChunkingService
from tasks.models import ProcessingTask
from users.models import User
```

### Key Patterns to Follow

1. **ChunkingService tests** — Use `TestCase` (not `SimpleTestCase`) for consistency, even though no DB is needed. Instantiate `ChunkingService()` in `setUp`.

2. **Overlap test** — Create text like `"A" * 800 + ". " + "B" * 800 + ". " + "C" * 800` with `chunk_size=1000, overlap=200`. Verify chunk 1 ends with `"B"` content and chunk 2 starts with overlapping `"B"` content.

3. **Sentence boundary test** — Create text with a very long first sentence that exceeds `chunk_size`, verify the split happens at the sentence-ending `.` not in the middle.

4. **Token count test** — Use `tiktoken.get_encoding("cl100k_base")` to compute expected token count and compare with `chunk.token_count`.

5. **Page tracking test** — Create text like `"[PAGE 1]\nHello world.\n[PAGE 2]\nSecond page content."` with `chunk_size=1000`, verify `page_start=1, page_end=2`.

6. **Integration test** — Create a real PDF with `fitz`, create a `Document` record, call `process_document()` with mocked Celery chain, verify `ProcessingTask` was created with `status="pending"`.

7. **Auth test** — Use `APIClient` and iterate over all 5 endpoints, assert `401` for each without auth headers.

### Mock Celery Request Pattern

Reuse the existing `_mock_celery_request` helper from [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py):

```python
def _mock_celery_request(task_func, celery_task_id: str = "test-celery-id"):
    return patch(
        "celery.app.task.Task.request",
        new_callable=PropertyMock,
        return_value=MagicMock(id=celery_task_id),
    )
```

### How to Run

```bash
# Run only the new test file
docker-compose exec backend python -m pytest src/backend/tests/test_processing.py -v

# Run all document processing tests
docker-compose exec backend python -m pytest src/backend/documents/tests/ src/backend/tests/test_processing.py -v
```

---

## Summary of What's New vs. What Exists

| Category | Existing Tests | New Tests | File |
|----------|---------------|-----------|------|
| ChunkingService unit tests | 0 | 7 | `src/backend/tests/test_processing.py` |
| Task tests | 32 (in `test_tasks.py`) | 1 integration | `src/backend/tests/test_processing.py` |
| API endpoint tests | 48 (in `test_views.py`) | 1 auth consolidation | `src/backend/tests/test_processing.py` |
| **Total** | **80** | **9** | |

---

## Dependencies

- [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py) — The `ChunkingService` class under test
- [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) — Celery tasks
- [`src/backend/documents/services/processing_service.py`](src/backend/documents/services/processing_service.py) — `process_document` orchestration
- [`src/backend/documents/views.py`](src/backend/documents/views.py) — API views
- [`src/backend/documents/urls.py`](src/backend/documents/urls.py) — URL patterns for `reverse()`
- [`src/backend/documents/models.py`](src/backend/documents/models.py) — `Document`, `DocumentChunk`
- [`src/backend/tasks/models.py`](src/backend/tasks/models.py) — `ProcessingTask`
- [`src/backend/users/models.py`](src/backend/users/models.py) — `User`
- `tiktoken` — For token count verification in tests
- `fitz` (PyMuPDF) — For creating test PDFs
