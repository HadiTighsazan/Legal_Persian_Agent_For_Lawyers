# Code Review: Task 5 — Processing Status API

**Review Date:** 2026-04-26  
**Reviewer:** Roo (Architect)  
**Scope:** [`src/backend/documents/views.py`](src/backend/documents/views.py), [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py), [`src/backend/documents/urls.py`](src/backend/documents/urls.py), [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py), [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py)

---

## Executive Summary

The Task 5 implementation is **functionally correct** and the task-level tests (`test_tasks.py`) are **well-written with good coverage**. However, there are **zero tests for the API views** (`DocumentProcessView`, `DocumentProcessingStatusView`), several **architectural concerns**, and a few **subtle bugs** that could cause issues in production. The code is clean and well-documented, but the missing view-layer tests are a significant gap.

---

## 🔴 Bug #1: `DocumentProcessView` double-checks processing status (redundant + race condition)

**File:** [`src/backend/documents/views.py:147`](src/backend/documents/views.py:147)  
**Severity:** Medium

The view checks `document.processing_status in ("processing", "completed")` and returns `400 Bad Request` if so. But [`process_document()`](src/backend/documents/tasks/document_processing.py:395) performs the **exact same check** again. This is:

1. **Redundant code** — the check exists in two places with the same logic.
2. **A race condition window** — between the view's check and `process_document()`'s check, another request could slip through and create duplicate `ProcessingTask` records.

**Fix:** Remove the check from the view and let `process_document()` handle it. The view should call `process_document()` and check its return value — if `None`, return `400 Bad Request`.

---

## 🔴 Bug #2: `DocumentProcessView` doesn't handle `process_document()` returning `None`

**File:** [`src/backend/documents/views.py:156`](src/backend/documents/views.py:156)  
**Severity:** High

```python
task_id = process_document(str(document.id))
```

If `process_document()` returns `None` (document already processing/completed, or not found), the view **blindly uses `None` as `task_id`** and returns `202 Accepted` with `"task_id": null`. This is a silent failure — the client thinks processing started but it didn't.

**Fix:** Check the return value:
```python
task_id = process_document(str(document.id))
if task_id is None:
    return Response(
        {"error": "bad_request", "message": "Document is already being processed or has been processed"},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

---

## 🔴 Bug #3: `DocumentProcessingStatusView` uses `document.processing_status` directly — can be stale

**File:** [`src/backend/documents/views.py:264`](src/backend/documents/views.py:264)  
**Severity:** Medium

```python
display_status = document.processing_status
```

The view reads `document.processing_status` from the DB, but the Celery `AsyncResult` healing logic (lines 215-233) only updates individual `ProcessingTask` records — it **never updates `document.processing_status`**. So if a task heals from `"running"` to `"failed"` via `AsyncResult`, the top-level `display_status` still shows the old value from the `Document` model.

**Fix:** After the healing loop, recompute `display_status` from the actual task states rather than relying on `document.processing_status`:
- If any task is `"running"` → `"processing"`
- If all tasks are `"completed"` → `"completed"`
- If any task is `"failed"` → `"failed"`
- If no tasks → `"pending"`

---

## 🔴 Bug #4: `extract_text_from_pdf` sets `document.processing_status = "completed"` too early

**File:** [`src/backend/documents/tasks/document_processing.py:152`](src/backend/documents/tasks/document_processing.py:152)  
**Severity:** Medium

After successful text extraction, the task sets:
```python
document.processing_status = "completed"
```

But the **Celery chain hasn't finished yet** — `chunk_document` still needs to run. If the worker crashes between extraction and chunking, the document will be stuck at `"completed"` even though chunking never happened. The `_handle_chain_error` callback won't fire because the chain itself didn't fail — the worker just disappeared.

**Fix:** The `extract_text_from_pdf` task should **not** set `processing_status = "completed"`. Only the **last task in the chain** (`chunk_document`) should set the final status. Extraction should leave it as `"processing"` (which it already set at line 101).

---

## 🟡 Architectural Concern #1: No view-layer tests for Task 5 endpoints

**Files:** [`src/backend/documents/views.py`](src/backend/documents/views.py:113-277), [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py:62-96)  
**Severity:** High

There are **zero tests** for:
- `DocumentProcessView` (`POST /documents/{id}/process/`)
- `DocumentProcessingStatusView` (`GET /documents/{id}/processing-status/`)
- `ProcessingStatusSerializer`
- `ProcessingTaskSerializer`

The existing tests in [`test_tasks.py`](src/backend/documents/tests/test_tasks.py) only cover the Celery task layer. The API views are completely untested.

**Required tests:**
1. `POST /documents/{id}/process/` — happy path (returns 202)
2. `POST /documents/{id}/process/` — document not found (returns 404)
3. `POST /documents/{id}/process/` — wrong owner (returns 403)
4. `POST /documents/{id}/process/` — already processing (returns 400)
5. `GET /documents/{id}/processing-status/` — happy path with tasks
6. `GET /documents/{id}/processing-status/` — no tasks (returns pending)
7. `GET /documents/{id}/processing-status/` — document not found (returns 404)
8. `GET /documents/{id}/processing-status/` — wrong owner (returns 403)
9. `ProcessingStatusSerializer` — validation of response data
10. `ProcessingTaskSerializer` — serialization of task data

---

## 🟡 Architectural Concern #2: `DocumentProcessingStatusView` has too many responsibilities

**File:** [`src/backend/documents/views.py:189-277`](src/backend/documents/views.py:189-277)  
**Severity:** Medium

The view does **four things** in one method:
1. Fetches the document and checks ownership
2. Fetches `ProcessingTask` records
3. Heals stale task states via Celery `AsyncResult` (side effect: writes to DB)
4. Computes progress and builds response

The `AsyncResult` healing logic (lines 215-233) is a **side effect inside a GET endpoint** — it writes to the database during a read operation. This violates the principle of Command-Query Separation (CQS).

**Fix:** Extract the healing logic into a service function (e.g., `heal_stale_tasks(document)`) and call it before building the response. Or better, move healing to a separate periodic task (Celery Beat) and keep the view read-only.

---

## 🟡 Architectural Concern #3: `extract_text_from_pdf` manages its own `ProcessingTask` lifecycle

**File:** [`src/backend/documents/tasks/document_processing.py:78-98`](src/backend/documents/tasks/document_processing.py:78-98)  
**Severity:** Low

The task searches for an existing `ProcessingTask` with `task_type="extract"` and either creates or updates it. This is fragile — if the task is retried by Celery's `autoretry_for`, it will find the same task and update it, which is fine. But if the task is **manually retried** later, it might find a completed task and incorrectly re-use it.

**Fix:** Add a `status__in=("pending", "running")` filter to the lookup query to ensure it only finds active tasks. If none found, create a new one.

---

## 🟡 Architectural Concern #4: `chunk_document` creates a `ProcessingTask` but `extract_text_from_pdf` reuses one — inconsistency

**File:** [`src/backend/documents/tasks/document_processing.py:218`](src/backend/documents/tasks/document_processing.py:218) vs [line 79](src/backend/documents/tasks/document_processing.py:79)  
**Severity:** Low

`chunk_document` always creates a **new** `ProcessingTask` with `task_type="chunk"`, while `extract_text_from_pdf` tries to **find an existing one** first. This inconsistency is confusing. Both should follow the same pattern.

**Recommendation:** Standardize on one approach. Since `process_document()` already creates the "extract" task, `extract_text_from_pdf` should just find and update it (no fallback creation). And `chunk_document` should also check for an existing "chunk" task before creating one.

---

## 🟡 Architectural Concern #5: `Document` model has two status fields — confusing

**File:** [`src/backend/documents/models.py:33-37`](src/backend/documents/models.py:33-37)  
**Severity:** Medium

The `Document` model has:
- `status` (choices: `uploaded`, `processing`, `completed`, `failed`)
- `processing_status` (free text: `pending`, `processing`, `completed`, `failed`)

These two fields overlap significantly and are confusing. `status` is set to `'uploaded'` on creation and never updated anywhere in the current code. `processing_status` is the one actually used by the pipeline.

**Fix:** Either:
- Remove `status` and rename `processing_status` to `status`, or
- Clearly document the distinction: `status` = upload status, `processing_status` = pipeline status

---

## 🟡 Architectural Concern #6: `process_document` is a regular function, not a Celery task — but it's imported as if it were

**File:** [`src/backend/documents/views.py:30`](src/backend/documents/views.py:30)  
**Severity:** Low

```python
from documents.tasks import process_document
```

The import path suggests `process_document` is a Celery task (it's in `documents/tasks/`), but it's actually a regular Python function. This is misleading. The docstring in [`document_processing.py:364`](src/backend/documents/tasks/document_processing.py:364) explains this, but the import path is deceptive.

**Fix:** Either:
- Move `process_document` to a `services/` module (e.g., `documents/services/processing_service.py`), or
- Rename the `tasks/` directory to something like `pipeline/` to avoid confusion

---

## 🟡 Test Gap #1: No test for `DocumentProcessView` with already-processing document

**Severity:** Medium

The view returns `400 Bad Request` when `document.processing_status in ("processing", "completed")`, but there's no test verifying this behavior. Combined with Bug #2 (not checking `process_document()` return value), this gap means the error path is untested.

---

## 🟡 Test Gap #2: No test for `DocumentProcessingStatusView` with Celery `AsyncResult` healing

**Severity:** Medium

The healing logic (lines 215-233) is complex and involves Celery's `AsyncResult`. There are no tests verifying that:
- A stale `"running"` task gets healed to `"failed"` when Celery reports `FAILURE`
- A stale task gets healed to `"cancelled"` when Celery reports `REVOKED`
- The healing doesn't crash when Celery is unreachable (the `except Exception` catch at line 229)

---

## 🟡 Test Gap #3: No test for `ProcessingStatusSerializer` validation

**Severity:** Low

The serializer is used in the view to validate the response data:
```python
serializer = ProcessingStatusSerializer(data=response_data)
serializer.is_valid(raise_exception=True)
```

But there are no unit tests for this serializer. If the response format changes, the serializer won't catch it until runtime.

---

## 🟢 Positive Findings

1. **Excellent error handling** — The views properly return 404, 403, 400 with consistent error format (`{"error": "...", "message": "..."}`).
2. **Well-documented code** — Every class and method has clear docstrings.
3. **Good use of DRF** — `IsAuthenticated`, `APIView`, serializers for response validation.
4. **URL patterns use `<uuid:>` converter** — Proper type coercion for document IDs.
5. **Task-level tests are comprehensive** — 22 tests covering extraction, chunking, orchestration, and chain error handling.
6. **Bug #1 and Bug #2 from previous review are fixed** — `processing_status` is now set to `"completed"` on extraction success, and `chunk_document` preserves `"failed"` status.
7. **`link_error` callback** — Chain-level failures are caught and don't leave tasks stuck at `"pending"`.
8. **Retry mechanism** — Transient DB/storage errors are retried with exponential backoff.

---

## Summary of Issues

| # | Type | Severity | Description | File |
|---|------|----------|-------------|------|
| 1 | Bug | Medium | Redundant processing-status check + race condition | [`views.py:147`](src/backend/documents/views.py:147) |
| 2 | Bug | **High** | `process_document()` returning `None` not handled | [`views.py:156`](src/backend/documents/views.py:156) |
| 3 | Bug | Medium | `AsyncResult` healing doesn't update `document.processing_status` | [`views.py:264`](src/backend/documents/views.py:264) |
| 4 | Bug | Medium | Extraction sets `processing_status="completed"` before chain finishes | [`document_processing.py:152`](src/backend/documents/tasks/document_processing.py:152) |
| 5 | Concern | **High** | No view-layer tests for Task 5 endpoints | — |
| 6 | Concern | Medium | GET endpoint has write side-effect (CQS violation) | [`views.py:215-233`](src/backend/documents/views.py:215-233) |
| 7 | Concern | Low | Inconsistent `ProcessingTask` lifecycle management | [`document_processing.py:79`](src/backend/documents/tasks/document_processing.py:79) vs [line 218](src/backend/documents/tasks/document_processing.py:218) |
| 8 | Concern | Medium | Two overlapping status fields on `Document` model | [`models.py:33-37`](src/backend/documents/models.py:33-37) |
| 9 | Concern | Low | Misleading import path for `process_document` | [`views.py:30`](src/backend/documents/views.py:30) |
| 10 | Gap | Medium | No test for already-processing scenario in view | — |
| 11 | Gap | Medium | No test for `AsyncResult` healing logic | — |
| 12 | Gap | Low | No unit tests for processing status serializers | — |

---

## Proposed Refactoring Plan

### Phase 1: Critical Bug Fixes (High Priority)

1. **Fix Bug #2** — Check `process_document()` return value in `DocumentProcessView`
2. **Fix Bug #4** — Remove premature `processing_status = "completed"` from `extract_text_from_pdf`
3. **Fix Bug #1** — Remove redundant check from view, rely on `process_document()` return value
4. **Fix Bug #3** — Compute `display_status` from task states instead of `document.processing_status`

### Phase 2: Architectural Improvements (Medium Priority)

5. **Extract healing logic** — Move `AsyncResult` healing from view to a service function
6. **Add view-layer tests** — Comprehensive tests for both endpoints (see list above)
7. **Standardize `ProcessingTask` lifecycle** — Both tasks should follow the same pattern

### Phase 3: Cleanup (Low Priority)

8. **Document `status` vs `processing_status`** — Or consolidate into one field
9. **Rename/move `process_document`** — To avoid misleading import path
10. **Add serializer unit tests** — For `ProcessingStatusSerializer` and `ProcessingTaskSerializer`
