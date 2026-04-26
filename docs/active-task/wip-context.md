# WIP Context — Task 7: Retry API

## What Was Just Completed

**Implementation of `POST /documents/processing-tasks/{task_id}/retry/` endpoint** — all 5 steps completed.

### Step 1 — Model + Migration
- Added `retry_count = models.IntegerField(default=0)` to [`ProcessingTask`](src/backend/tasks/models.py:39)
- Created and applied migration `tasks.0003_processingtask_retry_count`

### Step 2 — View
- Created [`ProcessingTaskRetryView`](src/backend/documents/views.py:241) with full validation logic:
  - `IsAuthenticated` permission
  - Fetches `ProcessingTask` by UUID → 404 if not found
  - Verifies ownership via `task.document.user != request.user` → 403
  - Checks `task.status == "failed"` → 400 if not
  - Checks `task.retry_count < 3` → 400 with `max_retries_exceeded` if exceeded
  - Increments `retry_count`, resets `status="pending"`, clears `error_message` and `completed_at`
  - Calls `process_document(str(task.document.id))` to re-trigger Celery chain
  - If `process_document` returns `None` → 400 (document already processing/completed)
  - Updates `celery_task_id` with new task ID, saves, returns 200

### Step 3 — URL Route
- Registered `processing-tasks/<uuid:task_id>/retry/` in [`documents/urls.py`](src/backend/documents/urls.py:36)

### Step 4 — Tests
- Added [`ProcessingTaskRetryViewTests`](src/backend/documents/tests/test_views.py:145) with 12 test cases:
  - `test_nonexistent_task_returns_404`
  - `test_other_users_task_returns_403`
  - `test_unauthenticated_request_returns_401`
  - `test_non_failed_task_returns_400`
  - `test_max_retries_exceeded_returns_400`
  - `test_successful_retry_returns_200`
  - `test_successful_retry_increments_retry_count`
  - `test_successful_retry_clears_error_message`
  - `test_successful_retry_resets_status_to_pending`
  - `test_successful_retry_updates_celery_task_id`
  - `test_successful_retry_clears_completed_at`
  - `test_retry_when_document_already_processing_returns_400`
- All 48 tests in `test_views.py` pass (12 new + 36 existing)

### Step 5 — Reference Documentation
- Added retry endpoint to [`docs/references/api-registry.md`](docs/references/api-registry.md) under Documents section
- Added `retry_count` field to [`docs/references/database-schema.md`](docs/references/database-schema.md) in the `processing_tasks` table

## Current State of Code

- [`src/backend/tasks/models.py`](src/backend/tasks/models.py) — `ProcessingTask` has `retry_count` field
- [`src/backend/tasks/migrations/0003_processingtask_retry_count.py`](src/backend/tasks/migrations/0003_processingtask_retry_count.py) — Migration applied
- [`src/backend/documents/views.py`](src/backend/documents/views.py) — `ProcessingTaskRetryView` implemented
- [`src/backend/documents/urls.py`](src/backend/documents/urls.py) — Retry route registered
- [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) — 12 retry tests passing
- [`docs/references/api-registry.md`](docs/references/api-registry.md) — Retry endpoint documented
- [`docs/references/database-schema.md`](docs/references/database-schema.md) — `retry_count` field documented

## Exact Next Step

Task 7 implementation is complete. Ready for review.
