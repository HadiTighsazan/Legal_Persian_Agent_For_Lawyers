# Task 9: URL Registration — Implementation Prompt

## Context

This is Task 9 of Epic E-04 (Document Processing Pipeline). Tasks 1–8 have already been completed. The views, serializers, services, Celery tasks, and error handling are all implemented and tested.

## Analysis of Current State

After examining the codebase, **all 5 URL routes are already registered** in [`src/backend/documents/urls.py`](src/backend/documents/urls.py). The routes, views, and URL names are:

| Route | Method | View Class | URL Name | Status |
|---|---|---|---|---|
| `upload/` | POST | `DocumentUploadView` | `document-upload` | ✅ Already exists |
| `<uuid:document_id>/process/` | POST | `DocumentProcessView` | `document-process` | ✅ Already exists |
| `<uuid:document_id>/processing-status/` | GET | `DocumentProcessingStatusView` | `document-processing-status` | ✅ Already exists |
| `<uuid:document_id>/chunks/` | GET | `DocumentChunksListView` | `document-chunks` | ✅ Already exists |
| `processing-tasks/<uuid:task_id>/retry/` | POST | `ProcessingTaskRetryView` | `processing-task-retry` | ✅ Already exists |

All 5 views are imported and used. The `config/urls.py` already includes `path('documents/', include('documents.urls'))`. All URL names match what the tests expect (verified via `reverse()` calls in [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py)).

## What Needs to Be Done

Since the URLs are already in place, this task is essentially a **verification + documentation update** task. Here's what's needed:

### Step 1: Verify URL Registration

Run the existing tests to confirm all URL routes resolve correctly:

```bash
docker-compose exec backend python -m pytest documents/tests/test_views.py -v
```

This should show all tests passing (they use `reverse()` with the URL names, so if routes are wrong, tests would fail).

### Step 2: Update `docs/references/api-registry.md`

The API registry already has entries for all 4 new endpoints (process, processing-status, chunks, retry) with `Implementation Date: 2026-04-24`. However, verify that the URL patterns documented match the actual routes in `urls.py`. Specifically check:

- `POST /documents/{document_id}/process/` — route uses `<uuid:document_id>` ✅
- `GET /documents/{document_id}/processing-status/` — route uses `<uuid:document_id>` ✅
- `GET /documents/{document_id}/chunks/` — route uses `<uuid:document_id>` ✅
- `POST /documents/processing-tasks/{task_id}/retry/` — route uses `processing-tasks/<uuid:task_id>` ✅

### Step 3: Update `docs/active-task/wip-context.md`

Overwrite with:
1. What was just completed: Task 9 — verified all URL routes are correctly registered
2. Current state: All 5 URL routes in `documents/urls.py` are properly configured with correct view mappings, URL names, and path converters
3. Exact next step: Task 10 — Write Tests (if not already done) or mark Epic E-04 as complete

### Step 4: Run Full Test Suite

Run the full documents test suite to ensure nothing is broken:

```bash
docker-compose exec backend python -m pytest documents/tests/ -v
```

## Files to Modify

| File | Change |
|---|---|
| [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Update with Task 9 completion status |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | Verify/update URL patterns if needed |

## Files to Verify (no changes needed)

| File | Purpose |
|---|---|
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | All 5 routes already registered correctly |
| [`src/backend/config/urls.py`](src/backend/config/urls.py) | Already includes `documents/` URLs |
| [`src/backend/documents/views.py`](src/backend/documents/views.py) | All 5 views already implemented |
| [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) | Tests use correct URL names |

## Acceptance Criteria

- [ ] All existing tests pass (verifying URL resolution)
- [ ] `wip-context.md` updated with Task 9 completion
- [ ] `api-registry.md` verified for URL pattern accuracy
- [ ] Full test suite passes
