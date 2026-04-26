# Code Review v2: Task 5 — Processing Status API

**Review Date:** 2026-04-26  
**Reviewer:** Roo (Architect)  
**Scope:** Full Task 5 implementation including views, serializers, urls, tasks, services, models, and tests.

---

## Executive Summary

The Task 5 implementation is in **good shape**. The previous code review plan (`plans/task5-code-review.md`) identified 4 bugs and several architectural concerns, but **all 4 bugs have already been fixed** in the current code. The remaining issues are architectural refinements, test gaps, and minor inconsistencies — not critical bugs.

---

## ✅ What Was Fixed (Bugs from Previous Plan)

| # | Previous Bug | Status | Evidence |
|---|-------------|--------|----------|
| 1 | Redundant `processing_status` check in view + race condition | ✅ **FIXED** | [`views.py:148-162`](src/backend/documents/views.py:148) — view delegates entirely to `process_document()` and checks its return value |
| 2 | `process_document()` returning `None` not handled | ✅ **FIXED** | [`views.py:154-162`](src/backend/documents/views.py:154) — `if task_id is None: return 400` |
| 3 | `display_status` read from stale `document.processing_status` | ✅ **FIXED** | [`views.py:221`](src/backend/documents/views.py:221) — uses `compute_display_status(task_data)` derived from actual task states |
| 4 | Extraction sets `processing_status="completed"` before chain finishes | ✅ **FIXED** | [`document_processing.py:158-165`](src/backend/documents/tasks/document_processing.py:158) — extraction no longer sets `processing_status` to `completed`; only `chunk_document` does |

---

## 🔍 Remaining Issues

### 🔴 Issue #1: `process_document` import path is misleading

**File:** [`src/backend/documents/views.py:32`](src/backend/documents/views.py:32)  
**Severity:** Low  
**Type:** Architectural / Readability

```python
from documents.tasks import process_document
```

`process_document` is a **regular Python function** (not a Celery task), but it's imported from `documents.tasks`. The actual implementation lives in [`documents/services/processing_service.py:174`](src/backend/documents/services/processing_service.py:174). The `tasks/__init__.py` re-exports it for backward compatibility.

**Impact:** Developers reading the view will assume `process_document` is a Celery task, which could lead to confusion about how it behaves (synchronous vs async).

**Fix:** Change the import to point to the actual location:
```python
from documents.services.processing_service import process_document
```

---

### 🔴 Issue #2: `extract_text_from_pdf` has a fragile `ProcessingTask` lookup

**File:** [`src/backend/documents/tasks/document_processing.py:84-88`](src/backend/documents/tasks/document_processing.py:84)  
**Severity:** Medium  
**Type:** Robustness

```python
processing_task = ProcessingTask.objects.filter(
    document=document,
    task_type="extract",
    status="pending",
).order_by("-created_at").first()
```

If the task is **retried by Celery** (due to `autoretry_for`), the original task will already be marked `"running"` (set at line 101-104). On retry, this query won't find it, and the fallback at line 90-98 creates a **duplicate** `ProcessingTask`.

**Impact:** Multiple `ProcessingTask` records for the same `task_type="extract"` could accumulate on retries.

**Fix:** Change the lookup to also match `"running"` status:
```python
processing_task = ProcessingTask.objects.filter(
    document=document,
    task_type="extract",
    status__in=("pending", "running"),
).order_by("-created_at").first()
```

---

### 🔴 Issue #3: Inconsistent `ProcessingTask` lifecycle between tasks

**File:** [`src/backend/documents/tasks/document_processing.py:84`](src/backend/documents/tasks/document_processing.py:84) vs [`line 230`](src/backend/documents/tasks/document_processing.py:230)  
**Severity:** Low  
**Type:** Consistency

- `extract_text_from_pdf` tries to **find an existing** `ProcessingTask` (created by `process_document()`), then updates it.
- `chunk_document` **always creates a new** `ProcessingTask` with `task_type="chunk"`.

This inconsistency is confusing. Both should follow the same pattern.

**Fix:** Make `chunk_document` also check for an existing "chunk" task before creating one, OR make `process_document()` also pre-create the "chunk" task (like it does for "extract").

---

### 🔴 Issue #4: `Document` model has two overlapping status fields

**File:** [`src/backend/documents/models.py:55-59`](src/backend/documents/models.py:55)  
**Severity:** Medium  
**Type:** Architectural / Data Model

The `Document` model has:
- `status` (choices: `uploaded`, `processing`, `completed`, `failed`) — set to `'uploaded'` on creation, **never updated** by the pipeline
- `processing_status` (free text: `pending`, `processing`, `completed`, `failed`) — used by the pipeline

**Impact:** 
1. `status` is effectively dead code — it's set once and never changes.
2. Confusion for future developers about which field to use.
3. The `ProcessingStatusView` response uses `compute_display_status()` which is correct, but the `Document` model itself has stale `status`.

**Fix:** Either:
- **Option A (recommended):** Remove `status`, rename `processing_status` to `status`, and add proper `choices`.
- **Option B:** Update `status` in sync with `processing_status` in the pipeline tasks.

---

### 🔴 Issue #5: GET endpoint has write side-effect (CQS violation)

**File:** [`src/backend/documents/views.py:218`](src/backend/documents/views.py:218)  
**Severity:** Medium  
**Type:** Architectural

```python
task_data = build_task_data(list(tasks))
```

This calls `heal_task_from_celery()` for each task, which **writes to the database** (updating stale task states). This is a side-effect inside a GET (read) endpoint, violating Command-Query Separation.

**Impact:** 
1. Every status-check GET request could trigger DB writes.
2. If Celery is slow/unreachable, the `except Exception` catch in `heal_task_from_celery` swallows errors silently.
3. Makes the endpoint non-idempotent in terms of side-effects.

**Fix:** Move healing to a separate periodic Celery Beat task, or at minimum make it opt-in via a query parameter (`?heal=true`).

---

### 🔴 Issue #6: No `select_related` / `prefetch_related` on document queries

**File:** [`src/backend/documents/views.py:134`](src/backend/documents/views.py:134), [`views.py:198`](src/backend/documents/views.py:198)  
**Severity:** Low  
**Type:** Performance

```python
document = Document.objects.get(id=document_id)
```

This is a simple `get()` without `select_related('user')`. Since the view checks `document.user != request.user`, Django will execute a **second query** to fetch the user if it's not already cached.

**Impact:** N+1 query pattern — each status check executes 2 queries instead of 1 (or 3 with the `ProcessingTask` filter).

**Fix:** Use `select_related('user')`:
```python
document = Document.objects.select_related('user').get(id=document_id)
```

---

### 🟡 Test Gap #1: No test for Celery retry scenario on `extract_text_from_pdf`

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py)  
**Severity:** Low

The `extract_text_from_pdf` task has `autoretry_for` configured, but there's no test verifying that a retry correctly finds and updates the existing `ProcessingTask` (rather than creating a duplicate).

---

### 🟡 Test Gap #2: No test for `heal_task_from_celery` with unreachable Celery

**File:** [`src/backend/documents/tests/test_views.py:434`](src/backend/documents/tests/test_views.py:434)  
**Severity:** Low

The `heal_task_from_celery` function has an `except Exception` catch for when Celery is unreachable. There's no test verifying this graceful degradation.

---

### 🟡 Test Gap #3: No integration test for full pipeline (upload → process → status)

**Severity:** Medium

There's no end-to-end test that:
1. Uploads a document
2. Triggers processing
3. Polls the status endpoint
4. Verifies the final status is "completed"

---

## 📊 Summary

| # | Type | Severity | Description | File | Effort |
|---|------|----------|-------------|------|--------|
| 1 | Import | Low | Misleading `process_document` import path | [`views.py:32`](src/backend/documents/views.py:32) | Trivial |
| 2 | Bug | Medium | Fragile `ProcessingTask` lookup on Celery retry | [`document_processing.py:84`](src/backend/documents/tasks/document_processing.py:84) | Small |
| 3 | Consistency | Low | Inconsistent task lifecycle management | [`document_processing.py:84`](src/backend/documents/tasks/document_processing.py:84) vs [line 230](src/backend/documents/tasks/document_processing.py:230) | Small |
| 4 | Data Model | Medium | Two overlapping status fields on `Document` | [`models.py:55-59`](src/backend/documents/models.py:55) | Medium |
| 5 | Architecture | Medium | GET endpoint has write side-effect (CQS) | [`views.py:218`](src/backend/documents/views.py:218) | Medium |
| 6 | Performance | Low | Missing `select_related` on document queries | [`views.py:134`](src/backend/documents/views.py:134) | Trivial |
| 7 | Test Gap | Low | No retry scenario test for extraction task | `test_tasks.py` | Small |
| 8 | Test Gap | Low | No test for Celery-unreachable graceful degradation | `test_views.py` | Small |
| 9 | Test Gap | Medium | No end-to-end pipeline integration test | — | Medium |

---

## 🎯 Refactoring Plan

### Phase 1: Quick Wins (Trivial/Small Effort)

1. **Fix import path** — Change [`views.py:32`](src/backend/documents/views.py:32) to import from `documents.services.processing_service` instead of `documents.tasks`.
2. **Fix `select_related`** — Add `.select_related('user')` to document queries in both views.
3. **Fix fragile retry lookup** — Change `status="pending"` to `status__in=("pending", "running")` in [`document_processing.py:87`](src/backend/documents/tasks/document_processing.py:87).

### Phase 2: Consistency & Robustness (Small/Medium Effort)

4. **Standardize `ProcessingTask` lifecycle** — Make `chunk_document` follow the same pattern as `extract_text_from_pdf` (find existing or create). Or better, have `process_document()` pre-create both "extract" and "chunk" tasks.
5. **Add retry scenario test** — Test that Celery retry doesn't create duplicate `ProcessingTask` records.
6. **Add Celery-unreachable test** — Test `heal_task_from_celery` graceful degradation.

### Phase 3: Architectural Improvements (Medium Effort)

7. **Consolidate status fields** — Remove `status` from `Document` model, rename `processing_status` to `status`, add proper `choices`. Requires a migration.
8. **Move healing to background task** — Create a Celery Beat periodic task for `AsyncResult` healing instead of doing it in the GET endpoint. Or add `?heal=true` query parameter opt-in.

### Phase 4: Integration Testing (Medium Effort)

9. **Add end-to-end pipeline test** — Upload → process → poll status → verify completion.

---

## 📝 Notes

- The existing tests in `test_views.py` and `test_tasks.py` are **well-written** with good coverage of the core logic.
- The `ProcessingStatusSerializer` and `ProcessingTaskSerializer` have **comprehensive unit tests** in `test_serializers.py`.
- The code is **well-documented** with clear docstrings and inline comments.
- The `link_error` callback mechanism is a **good pattern** for catching chain-level failures.
