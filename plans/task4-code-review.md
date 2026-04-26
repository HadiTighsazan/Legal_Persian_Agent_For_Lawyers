# Code Review Report — Task 4: Celery Document Processing Pipeline

**Reviewer:** Architect Mode  
**Date:** 2026-04-26  
**Scope:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py), [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py), and related infrastructure

---

## Executive Summary

The Task 4 implementation is **well-structured and functionally correct**. The bug fixes documented in [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) have addressed the critical issues (deadlock risk from `process_document` being a Celery task, `chunk_document` reusing the extract `ProcessingTask`, etc.). The code follows clean architecture patterns, has good error handling, and the tests are comprehensive.

However, I've identified **6 issues** — 2 bugs, 2 design concerns, and 2 test gaps — that should be addressed before moving forward.

---

## 🔴 Bug #1: `extract_text_from_pdf` never sets `document.processing_status = "completed"` on success

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:90)

**Problem:**  
In the happy path of [`extract_text_from_pdf()`](src/backend/documents/tasks/document_processing.py:42), the function sets `document.processing_status = "processing"` at line 90, but **never updates it to `"completed"`** after successful extraction. It only updates `extracted_text_length` and `total_pages` (line 139-140).

Meanwhile, [`chunk_document()`](src/backend/documents/tasks/document_processing.py:175) sets `document.processing_status = "completed"` at line 243. This means:

- If the chain runs fully (extract → chunk), the document ends up as `"completed"` — correct.
- **But if extraction succeeds and chunking fails**, the document remains stuck at `"processing"` even though extraction completed successfully. The `processing_error` field would contain the chunking error, but `processing_status` would misleadingly say `"processing"`.

**Impact:** Medium. The status healing mechanism in [`DocumentProcessingStatusView`](src/backend/documents/views.py:214) only checks Celery `AsyncResult` state, not the DB-level status inconsistency. A failed chunk step after successful extraction would leave the document in a confusing state.

**Fix:** Either:
1. Set `document.processing_status = "completed"` in `extract_text_from_pdf` after successful extraction (but then `chunk_document` would need to set it back to `"processing"` — not ideal).
2. Better: Don't set `processing_status` at all in individual tasks. Let the **orchestrator** (`process_document`) manage the top-level status. The individual tasks should only manage their own `ProcessingTask` records.

**Recommendation:** Option 2 — refactor so that `process_document` is responsible for the document-level `processing_status`, and individual tasks only update their own `ProcessingTask`. However, this is a larger refactor. For a minimal fix, ensure `chunk_document` handles the case where it fails and the document was left at `"processing"` by the extract step.

---

## 🔴 Bug #2: `chunk_document` does not handle the case where `extract_text_from_pdf` already set `processing_status = "failed"`

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:175)

**Problem:**  
In a Celery chain, if `extract_text_from_pdf` fails (returns `""`), the chain still proceeds to `chunk_document` with an empty string. The `chunk_document` task handles empty text gracefully (sets `total_chunks = 0`, marks as completed). However, the document's `processing_status` was already set to `"failed"` by `_fail_extract()`, and then `chunk_document` **overwrites it to `"completed"`** at line 243.

**Scenario:**
1. `extract_text_from_pdf` encounters a corrupted PDF → calls `_fail_extract()` → sets `document.processing_status = "failed"`, `document.processing_error = "PDF file is corrupted or unreadable"`
2. Chain passes `""` to `chunk_document`
3. `chunk_document` sees empty text → sets `document.processing_status = "completed"`, `document.total_chunks = 0`
4. **Result:** Document shows `"completed"` with 0 chunks, but the error message from extraction is lost (overwritten by `chunk_document`'s success path)

**Impact:** High. This is a data integrity issue — a failed document gets incorrectly marked as completed.

**Fix:** In `chunk_document`, before updating `document.processing_status`, check if it's already `"failed"`. If so, don't overwrite it.

---

## 🟡 Design Concern #1: `process_document` doesn't handle chain-level failures

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:279)

**Problem:**  
The [`process_document()`](src/backend/documents/tasks/document_processing.py:279) function submits the chain via `apply_async()` but does not attach a **link_error** callback. If the entire chain fails (e.g., the worker crashes), the `ProcessingTask` with `task_type='extract'` remains stuck at `"pending"` status forever.

The status healing in [`DocumentProcessingStatusView`](src/backend/documents/views.py:214) only checks `AsyncResult` for tasks that have a `celery_task_id` and are in `"running"` or `"pending"` state. But the chain's task ID is stored on the "extract" `ProcessingTask`, and if the chain fails, the extract task's status would still be `"pending"` (never updated to `"running"` because the task never actually executed).

**Impact:** Medium. Stale `"pending"` records that never resolve.

**Fix:** Add a Celery [`link_error`](https://docs.celeryq.dev/en/stable/userguide/canvas.html#error-callbacks) to the chain that updates the `ProcessingTask` status to `"failed"` on chain-level failure. Alternatively, add a periodic cleanup task (Celery Beat) that sweeps stale `"pending"` tasks.

---

## 🟡 Design Concern #2: `extract_text_from_pdf` has no retry mechanism

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:41)

**Problem:**  
The `@shared_task` decorator has no `autoretry_for` or `max_retries` configuration. The docstring at line 56-57 explicitly says "exceptions are **not** re-raised so the Celery worker does not retry indefinitely." While this is intentional for permanent failures (corrupted PDF, password-protected), transient failures (e.g., database connection timeout, storage backend hiccup) would also be silently swallowed.

**Impact:** Low-Medium. Transient failures that could be resolved by a retry (e.g., DB connection pool exhaustion) will permanently fail the document.

**Fix:** Add `autoretry_for=(IntegrityError, OperationalError, ...)` with `max_retries=3` and `retry_backoff=True` to the `@shared_task` decorator, so transient DB/storage errors are retried while permanent PDF errors still fail immediately.

---

## 🟡 Test Gap #1: No test for the extract-then-chunk-failure scenario (Bug #1)

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py)

**Problem:**  
There is no test that simulates the full chain where extraction succeeds but chunking fails. This would catch Bug #1 (document stuck at `"processing"`).

**Fix:** Add a test that:
1. Runs `extract_text_from_pdf` successfully
2. Then runs `chunk_document` with a mocked `ChunkingService` that raises
3. Verifies the document's `processing_status` is `"failed"` (not `"processing"`)

---

## 🟡 Test Gap #2: No test for the extract-fail-then-chunk-overwrite scenario (Bug #2)

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py)

**Problem:**  
There is no test that simulates the chain where extraction fails (returns `""`) and then chunking runs on the empty string. This would catch Bug #2 (chunking overwrites the failed status).

**Fix:** Add a test that:
1. Sets up a document with `processing_status = "failed"` and `processing_error = "some error"`
2. Runs `chunk_document("", document_id)`
3. Verifies that `processing_status` remains `"failed"` and `processing_error` is preserved

---

## ✅ What's Working Well

1. **Architecture:** The separation of `process_document` as a regular Python function (not a Celery task) is the correct design — it avoids the deadlock risk of a Celery task calling `apply_async()`.

2. **Error Handling:** The `_fail_extract()` helper cleanly centralizes failure logic. The `try/except` blocks in both tasks are appropriately scoped.

3. **PDF Path Resolution:** The `os.path.isabs()` check at line 97 correctly handles both absolute paths (from `LocalStorageBackend.save_file()`) and relative paths.

4. **Empty PDF Handling:** The manual zero-page PDF construction in tests (`_create_empty_pdf`) is clever and necessary since PyMuPDF won't save 0-page documents.

5. **Test Quality:** The tests use `TestCase` (not `SimpleTestCase`), properly clean up temp directories in `tearDown()`, and mock Celery's `Task.request` correctly via `PropertyMock`.

6. **Bulk Insert:** Using `DocumentChunk.objects.bulk_create()` inside `transaction.atomic()` is the correct approach for performance.

7. **Status Healing:** The `AsyncResult` check in `DocumentProcessingStatusView` is a good defense against stale Celery state.

---

## Summary of Issues

| # | Severity | Category | Description | File:Line |
|---|----------|----------|-------------|-----------|
| 1 | 🔴 Bug | Logic | `extract_text_from_pdf` never sets `processing_status = "completed"` on success; if chunking fails after, document stuck at `"processing"` | [`document_processing.py:90`](src/backend/documents/tasks/document_processing.py:90) |
| 2 | 🔴 Bug | Logic | `chunk_document` overwrites `processing_status = "failed"` to `"completed"` when extraction already failed and passed empty text | [`document_processing.py:204-208`](src/backend/documents/tasks/document_processing.py:204) |
| 3 | 🟡 Design | Resilience | No `link_error` callback on the Celery chain; chain-level failures leave `ProcessingTask` stuck at `"pending"` | [`document_processing.py:323-326`](src/backend/documents/tasks/document_processing.py:323) |
| 4 | 🟡 Design | Resilience | No retry mechanism for transient failures (DB, storage); all exceptions are silently swallowed | [`document_processing.py:41`](src/backend/documents/tasks/document_processing.py:41) |
| 5 | 🟡 Test Gap | Coverage | Missing test for extract-success + chunk-failure scenario | [`test_tasks.py`](src/backend/documents/tests/test_tasks.py) |
| 6 | 🟡 Test Gap | Coverage | Missing test for extract-fail + chunk-on-empty scenario | [`test_tasks.py`](src/backend/documents/tests/test_tasks.py) |

---

## Recommended Fix Order

1. **Bug #2** (highest impact — data integrity issue)
2. **Bug #1** (medium impact — stale status)
3. **Test Gap #1 + #2** (add tests for the bugs)
4. **Design Concern #1** (link_error callback)
5. **Design Concern #2** (retry for transient failures)
