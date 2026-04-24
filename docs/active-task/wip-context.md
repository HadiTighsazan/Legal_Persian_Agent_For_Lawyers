# WIP Context — Epic E-04 Bug Fixes (Tasks 4 & 5)

## What Was Just Completed

Applied comprehensive bug fixes to Tasks 4 (Celery Tasks) and 5 (Processing Status API) of Epic E-04. All 12 identified bugs were addressed across 3 phases.

### Files Modified

1. **`src/backend/documents/tasks/document_processing.py`** — Major refactor:
   - **Bug #2**: Removed `@shared_task(bind=True)` from `process_document` — it's now a regular Python function called directly from the view, eliminating the deadlock risk of a Celery task submitting `apply_async()`.
   - **Bug #3**: `chunk_document` now creates its own `ProcessingTask` with `task_type="chunk"` instead of reusing/modifying the "extract" task's status.
   - **Bug #6**: PDF path resolution now checks `os.path.isabs()` first before joining with `MEDIA_ROOT`, fixing the issue for absolute paths returned by local storage.
   - **Bug #5**: `process_document` now checks for both `"processing"` AND `"completed"` status to prevent duplicate processing.
   - **Bug #12**: Improved error message for corrupted PDFs to "PDF file is corrupted or unreadable".

2. **`src/backend/documents/views.py`** — Major refactor:
   - **Bug #4**: Removed `.delay()` call since `process_document` is no longer a Celery task. Now calls `process_document()` directly and uses its return value (the chain's task ID).
   - **Bug #5**: Added check for `"completed"` status alongside `"processing"` to prevent re-processing.
   - **Bug #7**: Added Celery `AsyncResult` healing mechanism — checks real-time Celery state for tasks stuck at "running"/"pending" and updates DB accordingly.
   - **Bug #8**: Status view now returns `"pending"` when no ProcessingTasks exist (document hasn't been processed yet), vs using `document.processing_status` directly.
   - **Bug #10**: Replaced `get_object_or_404` with explicit `try/except Document.DoesNotExist` returning proper JSON error responses.
   - **Bug #11**: Standardized all error responses to `{"error": "error_code", "message": "..."}` format matching the API registry.

3. **`src/backend/documents/tests/test_tasks.py`** — Updated tests:
   - **Bug #1**: Fixed `chunk_document` test calls to match the correct argument order: `chunk_document(extracted_text, document_id)`.
   - **Bug #3**: Added `test_creates_chunk_processing_task` to verify a "chunk" ProcessingTask is created.
   - **Bug #5**: Added `test_skips_if_already_completed` test.
   - Updated `process_document` tests since it's no longer a Celery task (no `.delay()` mock needed).

4. **`src/backend/tasks/models.py`** — **Bug #9**: Removed `unique=True` from `celery_task_id`, replaced with `db_index=True`.

5. **`src/backend/tasks/migrations/0002_alter_celery_task_id_unique.py`** — New migration for the `celery_task_id` constraint change.

### Reference Documentation Updated

6. **`docs/references/database-schema.md`** — Updated `celery_task_id` description to reflect removed UNIQUE constraint.
7. **`docs/references/api-registry.md`** — Updated implementation notes for `POST /documents/{id}/process/` to reflect new behavior.

## Current State of Code

- `process_document` is a regular function (not a Celery task) — called directly from `DocumentProcessView.post()`
- `chunk_document` creates its own `ProcessingTask` with `task_type="chunk"` and manages its own lifecycle
- `extract_text_from_pdf` manages the "extract" ProcessingTask as before
- The Celery chain still works: `extract_text_from_pdf → chunk_document`, with extracted text passed as first arg
- Error responses follow the API registry format
- Celery `AsyncResult` healing prevents stale "running" statuses
- PDF path resolution works for both relative and absolute paths

## Exact Next Step

Run the tests to verify all fixes work correctly:

```bash
docker-compose exec backend python -m pytest documents/tests/test_tasks.py -v
```

Then run the full test suite to ensure no regressions:

```bash
docker-compose exec backend python -m pytest
```

If tests pass, apply the new migration:

```bash
docker-compose exec backend python manage.py migrate tasks 0002
```
