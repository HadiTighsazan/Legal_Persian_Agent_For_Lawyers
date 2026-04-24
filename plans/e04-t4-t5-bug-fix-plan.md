# Bug Fix Plan: Epic E-04 Tasks 4 & 5

## Overview

This document catalogs all bugs, bug-prone areas, and design issues found in the implementation of Task 4 (Celery Tasks) and Task 5 (Processing Status API) of Epic E-04. Each issue is categorized by severity and includes a recommended fix.

---

## Bug #1 (CRITICAL): `chunk_document` has inverted argument order in the Celery chain

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:308-311)

**The Problem:**

In a Celery chain, the **output of the first task** is passed as the **first argument** to the second task. The chain is built as:

```python
chain(
    extract_text_from_pdf.s(document_id),   # returns extracted_text (str)
    chunk_document.s(document_id),           # receives (extracted_text, document_id)
)
```

But the signature of `chunk_document` is:

```python
def chunk_document(self, extracted_text: str, document_id: str) -> None:
```

This means the chain passes `(extracted_text, document_id)` — which is correct **only if** the chain passes arguments in the right order. Let's verify:

- `extract_text_from_pdf.s(document_id)` → returns `extracted_text` (str)
- Celery chain feeds the return value as the **first positional arg** to the next task
- `chunk_document.s(document_id)` → Celery merges: `(extracted_text, document_id)`

So the call becomes `chunk_document(extracted_text, document_id)`.

**But look at the function signature:** `def chunk_document(self, extracted_text: str, document_id: str)` — the `self` is the Celery task instance (bound task). So the actual positional args received are `(extracted_text, document_id)`. This is **correct**.

**Wait — let me re-examine.** The test at line 272 calls:
```python
chunk_document(str(self.document.id), extracted_text)
```

But the function signature is:
```python
def chunk_document(self, extracted_text: str, document_id: str) -> None:
```

**THIS IS A BUG!** The test calls `chunk_document(document_id, extracted_text)` but the function expects `(extracted_text, document_id)`. The test would fail with a type error or wrong argument assignment.

**Severity:** CRITICAL — The test itself is wrong, OR the function signature is wrong. Either way, the chain will silently pass arguments in the wrong order.

**Fix:** Change the function signature to match the chain's argument passing order. Since the chain passes `(extracted_text, document_id)`, the signature should be:

```python
def chunk_document(self, extracted_text: str, document_id: str) -> None:
```

And the test call should be:
```python
chunk_document(extracted_text, str(self.document.id))
```

---

## Bug #2 (CRITICAL): `process_document` is a Celery task that calls `chain().apply_async()` — deadlock risk

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:268-326)

**The Problem:**

`process_document` is itself a `@shared_task(bind=True)` Celery task. When the API view calls `process_document.delay(document_id)`, it submits this task to the Celery worker. Inside this task, it calls `chain().apply_async()` to submit **more** tasks.

This means:
1. A Celery worker picks up `process_document`
2. Inside that worker, it submits a chain of 2 more tasks
3. If there's only 1 Celery worker (or concurrency=1), this can cause a **deadlock** — the worker is busy running `process_document` and can't pick up the chain tasks

**Severity:** HIGH — Risk of task starvation in single-worker setups.

**Fix:** Change `process_document` to NOT be a Celery task itself. Instead, make it a regular Python function that the API view calls directly. The API view should call `process_document(document_id)` (synchronously), which creates the chain and calls `apply_async()`.

Alternatively, if it must remain a Celery task, use `apply_async()` with a different queue or ensure `CELERY_TASK_ACKS_LATE` handles it.

**Recommended approach:** Remove `@shared_task(bind=True)` from `process_document` and call it directly from the view.

---

## Bug #3 (HIGH): `chunk_document` updates the **extract** task status instead of creating a **chunk** task

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:186-203, 235-239)

**The Problem:**

The `chunk_document` task looks up the `ProcessingTask` with `task_type="extract"` and updates **its** status to "completed". But according to the design:

- `process_document` creates a `ProcessingTask` with `task_type="extract"` and `status="pending"`
- `extract_text_from_pdf` updates that extract task to "running" → "completed"
- `chunk_document` should create its **own** `ProcessingTask` with `task_type="chunk"` and manage its own lifecycle

Currently, `chunk_document` never creates a "chunk" ProcessingTask. It just reuses the "extract" one. This means:
1. The status API will never show a "chunk" task
2. If chunking fails, the extract task gets marked as "failed" — losing the distinction between which step failed

**Severity:** HIGH — Breaks the task tracking model and status API response.

**Fix:** In `chunk_document`:
1. Create a new `ProcessingTask` with `task_type="chunk"` and `status="running"`
2. Update its own status to "completed" or "failed"
3. Do NOT touch the extract task's status (the extract task already marked itself as completed)

---

## Bug #4 (HIGH): `DocumentProcessView.post()` returns `task_id` as the Celery `AsyncResult` object, not a string

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py:146-161)

**The Problem:**

```python
task_id = process_document.delay(str(document.id))
```

`process_document` is a `@shared_task`. Calling `.delay()` on a shared task returns an `AsyncResult` object, **not** a string. So `str(task_id)` converts the `AsyncResult` object to a string representation, not the actual Celery task ID.

The actual task ID is `task_id.id` (the `.id` attribute of `AsyncResult`).

**Severity:** HIGH — The API returns a garbage string instead of a real Celery task ID.

**Fix:** 
```python
result = process_document.delay(str(document.id))
task_id = result.id
```

---

## Bug #5 (MEDIUM): `DocumentProcessView` doesn't check if document processing has already **completed**

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py:138-143)

**The Problem:**

The view only prevents re-processing when `processing_status == "processing"`. But what if the document has already been processed successfully (`processing_status == "completed"`)? The current code would allow re-triggering, which would:
1. Create duplicate chunks
2. Reset the document status incorrectly

**Severity:** MEDIUM — Allows duplicate processing of already-completed documents.

**Fix:** Add a check for `processing_status in ("processing", "completed")`:

```python
if document.processing_status in ("processing", "completed"):
    return Response(
        {"error": "Document is already being processed or has been processed"},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

---

## Bug #6 (MEDIUM): `extract_text_from_pdf` constructs PDF path incorrectly for S3 storage

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:91)

**The Problem:**

```python
pdf_path = os.path.join(settings.MEDIA_ROOT, document.file_path)
```

This assumes the file is always stored locally under `MEDIA_ROOT`. But:
- `document.file_path` is the **absolute path** returned by `LocalStorageBackend.save_file()` (see [`local.py:91`](src/backend/documents/storage/local.py:91))
- `MEDIA_ROOT` is `BASE_DIR / 'media'`
- `LOCAL_STORAGE_PATH` is `BASE_DIR / 'media/documents'`

So `file_path` might already be an absolute path like `/app/media/documents/uuid.pdf`, and joining it with `MEDIA_ROOT` would produce `/app/media/app/media/documents/uuid.pdf` — a **nonexistent path**.

**Severity:** MEDIUM — PDF file won't be found for reading, causing silent failures.

**Fix:** Check if `file_path` is already absolute. If so, use it directly. Otherwise, join with `MEDIA_ROOT`. Better yet, use the storage backend to resolve the path:

```python
from documents.storage import get_storage_backend
storage = get_storage_backend()
pdf_path = storage.get_file_url(document.file_path)  # returns absolute path
```

---

## Bug #7 (MEDIUM): `DocumentProcessingStatusView` doesn't check Celery `AsyncResult` for real-time state

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py:164-233)

**The Problem:**

The implementation plan explicitly says:
> "Optionally check Celery `AsyncResult` for real-time state"

But the current code only queries the database. If a Celery worker crashes or the task is revoked, the DB status will be stale ("running" forever). The view has no mechanism to detect this.

**Severity:** MEDIUM — Status can be stuck at "running" indefinitely if worker dies.

**Fix:** For tasks with a `celery_task_id`, check `AsyncResult.state`:
- If `AsyncResult.state == 'FAILURE'` but DB says "running" → mark as failed
- If `AsyncResult.state == 'REVOKED'` → mark as cancelled
- This is a "healing" mechanism

---

## Bug #8 (MEDIUM): No `processing_status` update when document uploads — initial status mismatch

**File:** [`src/backend/documents/models.py`](src/backend/documents/models.py:37)

**The Problem:**

The `Document` model has two status fields:
- `status` (choices: uploaded, processing, completed, failed) — defaults to `'uploaded'`
- `processing_status` (free text) — defaults to `'pending'`

When a document is uploaded, `status='uploaded'` but `processing_status='pending'`. The API response for `GET /documents/{id}/processing-status/` returns `document.processing_status` as the top-level `status` field. So a freshly uploaded document shows `status: "pending"` instead of `status: "uploaded"`.

This is inconsistent — the user sees "pending" for a document that hasn't even started processing.

**Severity:** MEDIUM — Inconsistent status reporting.

**Fix:** Either:
1. Change the default of `processing_status` to `'uploaded'` to match `status`, OR
2. In the status view, return `'pending'` only when processing has been explicitly triggered, otherwise return `'uploaded'`

---

## Bug #9 (LOW): `ProcessingTask.celery_task_id` has `unique=True` constraint — breaks when chain has multiple tasks

**File:** [`src/backend/tasks/models.py`](src/backend/tasks/models.py:33)

**The Problem:**

```python
celery_task_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
```

The `unique=True` constraint means you cannot have two `ProcessingTask` records with the same `celery_task_id`. But:
- The chain (`process_document`) creates one `ProcessingTask` for "extract" and stores the **chain's** task ID
- If we later create a "chunk" ProcessingTask (see Bug #3), it would need a different `celery_task_id`
- In a Celery chain, each subtask has its own `task_id`, but the chain itself has one ID

If two documents are processed, each gets a unique chain ID, so this works for now. But if we ever want to store individual subtask IDs, this constraint will cause issues.

**Severity:** LOW — Works for current implementation but is fragile.

**Fix:** Remove `unique=True` from `celery_task_id` and rely on application-level uniqueness checks instead.

---

## Bug #10 (LOW): `DocumentProcessView` uses `get_object_or_404` which returns 404 HTML, not JSON

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py:129)

**The Problem:**

```python
document = get_object_or_404(Document, id=document_id)
```

`get_object_or_404` raises `Http404`, which Django renders as an HTML page by default. In an API context, this should return a JSON error response matching the API registry format:

```json
{"error": "not_found", "message": "Resource not found"}
```

**Severity:** LOW — Works but returns HTML instead of JSON for 404s.

**Fix:** Use a custom DRF-style 404 handler or catch `Http404` and return a proper JSON response.

---

## Bug #11 (LOW): `DocumentProcessView` error responses don't follow API registry format

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py:133-136, 140-143)

**The Problem:**

The API registry specifies a consistent error format:
```json
{"error": "permission_denied", "message": "You don't have permission..."}
```

But the current code returns:
```json
{"error": "You do not have permission to process this document."}
```

The `error` field is a human-readable string instead of a machine-readable error code.

**Severity:** LOW — Inconsistent with API contract.

**Fix:** Change to:
```python
return Response(
    {"error": "permission_denied", "message": "You do not have permission to process this document."},
    status=status.HTTP_403_FORBIDDEN,
)
```

---

## Bug #12 (LOW): `extract_text_from_pdf` doesn't handle `fitz.FileDataError` for password-protected PDFs properly

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:93-105)

**The Problem:**

The code catches `fitz.FileDataError` separately for corrupted PDFs, and then catches a generic `Exception` for password-protected PDFs. However, PyMuPDF (`fitz`) raises `fitz.FileDataError` for **both** corrupted and password-protected PDFs in many versions. The password-protected case may never reach the generic `Exception` handler.

**Severity:** LOW — Password detection may not work depending on PyMuPDF version.

**Fix:** Check for password protection inside the `fitz.FileDataError` handler by examining the error message, or attempt `pdf_document.authenticate()` after opening.

---

## Summary Table

| # | Severity | Category | File | Description |
|---|----------|----------|------|-------------|
| 1 | **CRITICAL** | Argument Order | `document_processing.py:167` | `chunk_document` args inverted between function sig and test call |
| 2 | **CRITICAL** | Architecture | `document_processing.py:268` | `process_document` as Celery task calling `apply_async()` — deadlock risk |
| 3 | **HIGH** | Missing Logic | `document_processing.py:186-203` | `chunk_document` never creates its own "chunk" ProcessingTask |
| 4 | **HIGH** | Wrong Type | `views.py:146` | `.delay()` returns `AsyncResult`, not string ID |
| 5 | **MEDIUM** | Missing Guard | `views.py:139` | Doesn't prevent re-processing completed documents |
| 6 | **MEDIUM** | Path Resolution | `document_processing.py:91` | PDF path constructed incorrectly for absolute paths |
| 7 | **MEDIUM** | Stale Status | `views.py:164-233` | No Celery `AsyncResult` check for stale tasks |
| 8 | **MEDIUM** | Status Inconsistency | `models.py:37` | `processing_status` default "pending" vs `status` default "uploaded" |
| 9 | **LOW** | DB Constraint | `tasks/models.py:33` | `unique=True` on `celery_task_id` is fragile |
| 10 | **LOW** | API Format | `views.py:129` | `get_object_or_404` returns HTML, not JSON |
| 11 | **LOW** | Error Format | `views.py:133-136` | Error responses don't follow API registry format |
| 12 | **LOW** | Error Handling | `document_processing.py:93-105` | Password detection may not work in all PyMuPDF versions |

---

## Recommended Fix Order

### Phase 1 — Critical & High (Must Fix)

1. **Bug #2**: Refactor `process_document` to be a regular function (not a Celery task). Update the view to call it directly.
2. **Bug #4**: Fix `AsyncResult` handling in `DocumentProcessView`.
3. **Bug #1**: Fix `chunk_document` argument order — ensure the test matches the function signature and the chain passes args correctly.
4. **Bug #3**: Make `chunk_document` create and manage its own "chunk" `ProcessingTask`.

### Phase 2 — Medium (Should Fix)

5. **Bug #5**: Add guard against re-processing completed documents.
6. **Bug #6**: Fix PDF path resolution for both local and S3 storage.
7. **Bug #7**: Add Celery `AsyncResult` check in status view.
8. **Bug #8**: Fix `processing_status` default or status view logic.

### Phase 3 — Low (Nice to Have)

9. **Bug #9**: Remove `unique=True` from `celery_task_id`.
10. **Bug #10**: Return JSON 404 responses.
11. **Bug #11**: Standardize error response format.
12. **Bug #12**: Improve password-protected PDF detection.

---

## Detailed Fix Specifications

### Fix for Bug #2: Refactor `process_document`

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)

Remove `@shared_task(bind=True)` decorator and `self` parameter. The function becomes a regular Python function:

```python
def process_document(document_id: str) -> str | None:
    """Orchestrate the full document processing pipeline via a Celery chain.
    
    This is NOT a Celery task itself — it's a helper that creates and submits
    a Celery chain. Called directly from the API view.
    """
    # ... same logic, but no @shared_task, no `self` parameter
```

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py)

Change the view to call `process_document` directly (not via `.delay()`):

```python
from documents.tasks import process_document  # already imported

class DocumentProcessView(APIView):
    def post(self, request, document_id):
        # ... ownership check ...
        # ... duplicate check ...
        
        # Call directly (not .delay())
        task_id = process_document(str(document.id))
        
        return Response(
            {
                "task_id": task_id,
                "status": "pending",
                "document_id": str(document.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )
```

### Fix for Bug #3: Create "chunk" ProcessingTask in `chunk_document`

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)

In `chunk_document`, instead of looking up the "extract" task, create a new "chunk" task:

```python
@shared_task(bind=True)
def chunk_document(self, extracted_text: str, document_id: str) -> None:
    # ... fetch document ...
    
    # Create a new ProcessingTask for chunking
    chunk_task = ProcessingTask.objects.create(
        document=document,
        task_type="chunk",
        celery_task_id=self.request.id,
        status="running",
        started_at=timezone.now(),
    )
    
    # ... chunking logic ...
    
    # Update chunk_task status on success/failure
    chunk_task.status = "completed"
    chunk_task.completed_at = timezone.now()
    chunk_task.save(update_fields=["status", "completed_at"])
```

### Fix for Bug #6: PDF Path Resolution

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)

```python
# Use storage backend to resolve the path
from documents.storage import get_storage_backend

storage = get_storage_backend()
pdf_path = storage.get_file_url(document.file_path)
pdf_document = fitz.open(pdf_path)
```

Or simpler — check if path is absolute:

```python
if os.path.isabs(document.file_path):
    pdf_path = document.file_path
else:
    pdf_path = os.path.join(settings.MEDIA_ROOT, document.file_path)
pdf_document = fitz.open(pdf_path)
```

---

## Files to Modify

| # | File | Changes |
|---|------|---------|
| 1 | `src/backend/documents/tasks/document_processing.py` | Fix Bugs #1, #2, #3, #6, #12 |
| 2 | `src/backend/documents/views.py` | Fix Bugs #4, #5, #7, #10, #11 |
| 3 | `src/backend/tasks/models.py` | Fix Bug #9 (optional) |
| 4 | `src/backend/documents/tests/test_tasks.py` | Fix test argument order (Bug #1), update tests for new behavior |
| 5 | `docs/references/api-registry.md` | Update if error response format changes |
