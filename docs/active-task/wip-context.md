# WIP Context — Fix Embedding Progress Bar Stuck on Pending & Empty Context in Chat

## What Was Just Completed

**Bug A (Progress Bar Never Updates) and Bug B (Empty Context in Chat) have been fixed.**

Additionally, **two Celery runtime errors** reported from worker logs have been fixed:
1. `TypeError: embed_document() takes 3 positional arguments but 4 were given`
2. `TypeError: _handle_chain_error() got multiple values for argument 'task_type'`

### Root Cause Analysis

**Bug A — Progress Bar Never Updates:**
The `chunk_document` task in [`document_processing.py`](src/backend/documents/tasks/document_processing.py:290-298) was prematurely setting `document.processing_status = "completed"` and `document.status = "completed"` **before** the `embed_document` task had finished. Since the Celery chain is `extract → chunk → embed`, setting these fields in `chunk_document` caused:

1. The frontend's polling (which checks `document.processing_status !== "completed"`) to **stop polling** prematurely
2. The `ProcessingStatusPanel` to be **hidden** (because `processingStatus === "completed"`)
3. The "Chat with Document" button to appear **before embeddings were ready**

**Bug B — Empty Context in Chat:**
A direct consequence of Bug A. The document appeared "completed" but embeddings hadn't been generated yet. When the user asked a question:
- `search_chunks()` filtered with `embedding__isnull=False`
- Since embeddings were NULL, it returned 0 results
- `build_context([])` returned an empty string
- The LLM responded "Based on the provided context, there is no information about the text."

**Celery Error 1 — `embed_document() takes 3 positional arguments but 4 were given`:**
The `chunk_document` task returns `None`. Celery passes the previous task's return value as the first positional argument to the next task in the chain. So `embed_document` received `(None, document_id, task_id)` = 3 positional args + `self` (from `bind=True`) = 4 total, but its signature only accepts `(self, document_id, task_id)` = 3 total.

**Fix:** Changed `embed_document.s()` to `embed_document.si()` (immutable signature) in [`processing_service.py`](src/backend/documents/services/processing_service.py:247). The `.si()` prevents Celery from passing the previous task's return value as an argument.

**Celery Error 2 — `_handle_chain_error() got multiple values for argument 'task_type'`:**
Celery's `link_error` callback passes `(request, exc, traceback)` as positional args **before** the `.s()` args. The old signature `(self, document_id, task_type="extract")` didn't account for these, causing `task_type` to be passed twice (once from `.s()` and once as a keyword).

**Fix:** Changed the signature in [`document_processing.py`](src/backend/documents/tasks/document_processing.py:325-332) to `(self, request, exc, traceback, document_id, task_type="extract")`.

### Changes Made

#### TASK 1 — Fix `chunk_document` to Not Set `processing_status = "completed"`

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:290-298)

**Change:** Removed the lines that set `document.processing_status = "completed"` and `document.status = "completed"` from `chunk_document`. Now it only saves `document.total_chunks`. The responsibility for marking the pipeline as complete has been moved to `embed_document` (the final link in the chain).

#### TASK 2 — Move Pipeline Completion to `embed_document`

**File:** [`src/backend/documents/tasks/embedding_tasks.py`](src/backend/documents/tasks/embedding_tasks.py:104-117, 139-153)

**Changes:**
1. After successful embedding (line 111-117): Sets `document.processing_status = "completed"` and `document.status = "completed"`
2. On failure (line 146-153): Sets `document.processing_status = "failed"` and `document.status = "failed"` with the error message
3. No-chunks case (line 90-96): Also marks the document as completed when there are no chunks to embed

#### TASK 3 — Fix Frontend Polling Logic

**File:** [`src/frontend/src/pages/documents/DocumentDetailPage.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.tsx:81-102)

**Change:** Simplified the polling condition. The `useProcessingStatus` hook now polls when `document.processing_status` is not `"completed"` or `"failed"`. Since the backend fix ensures `processing_status` is only set to `"completed"` after embedding finishes, the polling will correctly remain active throughout the entire pipeline (extract → chunk → embed).

#### TASK 4 — Add Logging to Ollama Embedding Provider

**File:** [`src/backend/providers/ollama_embedding.py`](src/backend/providers/ollama_embedding.py)

**Changes:** Added detailed error logging for all three methods (`embed`, `embed_batch`, `embed_query`):
- HTTP errors now log status code, URL, model, and response body (first 500 chars)
- Connection errors now include a hint about checking if Ollama is running
- Timeout errors now log the URL and timeout duration
- Unexpected errors now log the exception type

#### FIX — Celery Chain Signature Mismatch

**File:** [`src/backend/documents/services/processing_service.py`](src/backend/documents/services/processing_service.py:247)

**Change:** Changed `embed_document.s(document_id, str(embed_task.id))` to `embed_document.si(document_id, str(embed_task.id))`. The `.si()` (immutable signature) prevents Celery from passing `chunk_document`'s return value (`None`) as the first positional argument to `embed_document`.

#### FIX — `_handle_chain_error` Errback Signature

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:325-332)

**Change:** Changed signature from `(self, document_id, task_type="extract")` to `(self, request, exc, traceback, document_id, task_type="extract")` to accept Celery's errback positional args `(request, exc, traceback)` that are passed before the `.s()` args.

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py:710-723)

**Change:** Updated `_run_callback` test helper to pass mock `request`, `exc`, and `traceback` arguments to match the new `_handle_chain_error` signature.

## Current State of Code

- All 4 tasks + 2 Celery signature fixes are implemented and tested
- **Backend tests:** 32/32 in `test_tasks.py` passed, 11/11 in `test_processing.py` passed, 420/421 overall (1 pre-existing failure in `test_upload_integration.py` unrelated)
- **Frontend tests:** 93 passed across 9 test files (all green)
- The pipeline flow is now: `extract_text_from_pdf → chunk_document → embed_document`
- `processing_status` is only set to `"completed"` after the embed task finishes
- If embedding fails, the document is marked as `"failed"` with the error message
- Ollama embedding provider has detailed error logging for easier debugging
- Celery chain uses `.si()` for `embed_document` to prevent argument leakage
- `_handle_chain_error` accepts Celery's errback positional args correctly

## Next Step

1. Rebuild and restart the containers: `docker-compose up --build`
2. Upload a document and verify the processing pipeline shows real-time progress for all three steps
3. Verify the "Chat with Document" button appears only after embeddings are complete
4. Ask a question and verify the response contains actual content from the document
5. Test with a Persian PDF to ensure non-Latin text works
