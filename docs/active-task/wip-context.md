# WIP Context — Task 8: Error Handling & Edge Cases

## What Was Just Completed

**Implementation of comprehensive error handling for the document processing pipeline** — all 6 steps completed.

### Step 1 — Created `error_handler.py` (Centralized Error Handler Service)

Created [`src/backend/documents/services/error_handler.py`](src/backend/documents/services/error_handler.py) with:

- **`_has_pdf_magic_bytes(file_path)`** — Checks if the first 4 bytes of a file are `%PDF`
- **`classify_pdf_error(exception, pdf_path)`** — Classifies PDF errors:
  - Non-PDF magic bytes → `"File is not a valid PDF"`
  - `fitz.FileDataError` / `fitz.EmptyFileError` → `"PDF file is corrupted or unreadable"`
  - `SoftTimeLimitExceeded` → `"Task timed out"`
  - Exception message contains "password" → `"PDF is password-protected"`
  - Fallback → `str(exception)`
- **`fail_processing_task(processing_task, document, error_message, logger)`** — Sets both `ProcessingTask` and `Document` to `"failed"` status with the error message, logs via `logger.exception()`
- **`log_milestone(logger, document_id, milestone, **extra)`** — Logs processing milestones at INFO level with consistent `[document_id] milestone — key=value` format

### Step 2 — Updated Celery Configuration in `settings.py`

Added to [`src/backend/config/settings.py`](src/backend/config/settings.py) (lines 223–227):
- `CELERY_TASK_ACKS_LATE = True`
- `CELERY_TASK_REJECT_ON_WORKER_LOST = True`
- `CELERY_TASK_RETRY_BACKOFF = True`
- `CELERY_TASK_RETRY_BACKOFF_MAX = 600`
- `CELERY_TASK_RETRY_JITTER = True`

### Step 3 — Refactored `document_processing.py`

Updated [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py):

- **Imports**: Added `_has_pdf_magic_bytes`, `classify_pdf_error`, `fail_processing_task`, `log_milestone` from error_handler
- **`extract_text_from_pdf()`**:
  - Added milestone logging at start (`"Starting extraction"`) and end (`"Extraction complete"`)
  - Added magic bytes check before `fitz.open()` — fails with `"File is not a valid PDF"` if missing
  - Replaced inline error handling with `classify_pdf_error()` + `fail_processing_task()`
  - Removed the old `_fail_extract()` helper function
- **`chunk_document()`**:
  - Added milestone logging at start (`"Starting chunking"`), after success (`"Chunking complete"`), and at pipeline end (`"Pipeline complete"`)
  - Wrapped `bulk_create` in try/except for `IntegrityError`/`OperationalError` → fails with `"Database error during chunking"`
  - Replaced inline error handling with `fail_processing_task()`
- **`_handle_chain_error()`**:
  - Added milestone logging for chain failure

### Step 4 — Updated Tests in `test_tasks.py`

Added 4 new test methods to [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py):

| # | Test Method | Scenario | Status |
|---|---|---|---|
| 1 | `test_password_protected_pdf_sets_failed_status` | Password-protected PDF (mock `fitz.open` with "password" in message) | ✅ Passing |
| 2 | `test_non_pdf_file_sets_failed_status` | Non-PDF file (no `%PDF` magic bytes) | ✅ Passing |
| 3 | `test_database_error_during_chunk_insert` | `IntegrityError` during `bulk_create` | ✅ Passing |
| 4 | `test_celery_task_timeout_behavior` | `SoftTimeLimitExceeded` during extraction | ✅ Passing |

### Step 5 — Ran Tests

All **32 tests** in `documents/tests/test_tasks.py` pass:
- `ExtractTextFromPdfTests` — 9 tests (5 existing + 4 new)
- `ChunkDocumentTests` — 10 tests (all existing)
- `ProcessDocumentTests` — 7 tests (all existing)
- `HandleChainErrorTests` — 6 tests (all existing)

### Step 6 — Reference Documentation

No changes needed to `api-registry.md` or `database-schema.md` — this task did not modify any API endpoints or database schema.

## Current State of Code

- [`src/backend/documents/services/error_handler.py`](src/backend/documents/services/error_handler.py) — Centralized error handler service created
- [`src/backend/config/settings.py`](src/backend/config/settings.py) — New Celery retry/acks-late settings added
- [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) — Refactored to use error handler, magic bytes check, milestone logging, DB error handling
- [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py) — 4 new edge case tests added, all 32 tests passing

## Exact Next Step

Task 8 implementation is complete. Ready for review.
