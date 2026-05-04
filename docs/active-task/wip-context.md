# WIP Context — Fix: Documents Stuck in "Pending" State After Upload ✅

## What Was Just Completed

**Root cause identified and fixed across frontend AND backend.** Documents uploaded via the frontend remained stuck in "pending" state because of three separate issues:

### Issue 1 (Frontend) — "Start Processing" Button Logic ✅ FIXED

**Root Cause:** The `Document` model has **two status fields**:
- `status` — upload lifecycle (`'uploaded'` → `'processing'` → `'completed'` / `'failed'`)
- `processing_status` — pipeline granular status (`'pending'` → `'processing'` → `'completed'` / `'failed'`)

After upload, `status='uploaded'` but `processing_status='pending'`. The code in `DocumentDetailPage.tsx` used `processing_status` first (`document.processing_status ?? document.status`), resulting in `'pending'`. Then `ProcessingStatusPanel` checked `processingStatus === "uploaded"` to show the "Start Processing" button — which was `false` because the value was `'pending'`, not `'uploaded'`. The button never rendered, so users had no way to trigger the Celery processing pipeline.

**Fix:** Separated the two status concepts. `ProcessingStatusPanel` now receives `documentStatus` as a separate prop and checks `documentStatus === "uploaded"` for the button. Also added guard to hide the button when `processingStatus === "processing"` or `processingStatus === "completed"`.

### Issue 2 (Backend) — Pipeline Never Updates `document.status` ✅ FIXED

**Root Cause:** The Celery pipeline tasks (`extract_text_from_pdf` → `chunk_document`) only updated `document.processing_status` (the pipeline-granular field) but **never updated `document.status`** (the upload lifecycle field). This meant:
- `document.status` stayed `'uploaded'` forever
- The "Chat with Document" button (which checks `document.status === 'completed'`) never appeared
- The frontend status badge showed "Uploaded" even after the pipeline completed

**Fix:** Updated all 4 places where `document.processing_status` is modified to also update `document.status`:
1. `extract_text_from_pdf` — now sets `document.status = "processing"` when extraction starts
2. `chunk_document` (normal path) — now sets `document.status = "completed"` when chunking succeeds
3. `chunk_document` (empty text path) — now sets `document.status = "completed"` for empty documents
4. `fail_processing_task` (error_handler.py) — now sets `document.status = "failed"` on pipeline failure
5. `_handle_chain_error` — now sets `document.status = "failed"` on chain-level failure

### Issue 3 (Frontend) — Document Not Re-fetched After Processing Completes ✅ FIXED

**Root Cause:** `DocumentDetailPage.tsx` fetched the document **once** on mount via `fetchDocument()` and never re-fetched it. The `useProcessingStatus` hook polled `GET /documents/{id}/processing-status/` (which returns the pipeline-granular `processing_status`), but when that reached `"completed"`, the hook stopped polling — yet `fetchDocument()` was never called again to get the updated `document.status`. So the UI still showed the old `document.status = 'uploaded'`, and the "Chat with Document" button never appeared until a manual page refresh.

**Fix:** Added a `useEffect` in [`DocumentDetailPage.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.tsx:111) that watches `statusData` and calls `fetchDocument()` whenever the processing pipeline reaches a terminal state (`"completed"` or `"failed"`):
```typescript
useEffect(() => {
  if (
    statusData &&
    (statusData.status === "completed" || statusData.status === "failed")
  ) {
    fetchDocument();
  }
}, [statusData, fetchDocument]);
```

### Changes Made

**Frontend:**

1. **`src/frontend/src/pages/documents/DocumentDetailPage.tsx`**
   - Separated the two status concepts with clear comments
   - `processingStatus` now uses only `document.processing_status ?? 'pending'` (for display in the panel)
   - "Chat with Document" button now checks `document.status === 'completed'` (the authoritative upload lifecycle field)
   - Passes new `documentStatus={document.status}` prop to `ProcessingStatusPanel`
   - **NEW:** Added `useEffect` to re-fetch document when `statusData.status` reaches `"completed"` or `"failed"`

2. **`src/frontend/src/components/documents/ProcessingStatusPanel.tsx`**
   - Added new `documentStatus: string` prop to the component interface
   - `showStartProcessing` now checks `documentStatus === "uploaded"` AND `processingStatus !== "processing"` AND `processingStatus !== "completed"`
   - Added JSDoc comments explaining the distinction

3. **`src/frontend/src/pages/documents/UploadPage.tsx`**
   - After successful upload, `triggerProcessing(response.id)` is called automatically
   - If auto-trigger fails, a non-fatal toast is shown and the user can manually trigger from the detail page

4. **`src/frontend/src/pages/documents/DocumentDetailPage.test.tsx`**
   - Fixed button name regex from `/start chat/i` to `/chat with document/i` (pre-existing bug)

**Backend:**

5. **`src/backend/documents/tasks/document_processing.py`**
   - `extract_text_from_pdf`: Added `document.status = "processing"` alongside `document.processing_status = "processing"`
   - `chunk_document` (normal path): Added `document.status = "completed"` alongside `document.processing_status = "completed"`
   - `chunk_document` (empty text path): Added `document.status = "completed"` alongside `document.processing_status = "completed"`
   - `_handle_chain_error`: Added `document.status = "failed"` alongside `document.processing_status = "failed"`

6. **`src/backend/documents/services/error_handler.py`**
   - `fail_processing_task`: Added `document.status = "failed"` alongside `document.processing_status = "failed"`

## Current State of Code

- All fixes are implemented and tested
- **211 backend tests pass** (0 failures)
- **93 frontend tests pass** (9 test files, 0 failures)
- Document processing is auto-triggered after upload
- "Start Processing" button correctly appears only when `document.status === 'uploaded'` AND document is not already processing/completed
- "Chat with Document" button correctly appears when `document.status === 'completed'`
- Processing status panel correctly shows per-task progress
- **NEW:** Document is automatically re-fetched when processing completes, so the "Chat with Document" button appears without manual refresh
- Pipeline lifecycle is now fully consistent: `uploaded` → `processing` → `completed`/`failed`

## Next Step

**WAITING** — User to:
1. Run `docker-compose up` to ensure all services are running (Celery worker + Redis are required for processing)
2. Upload a document via the frontend
3. Verify the document automatically starts processing
4. Wait for processing to complete (extract → chunk)
5. Verify the "Chat with Document" button appears **automatically** without page refresh
6. Verify chat functionality works end-to-end
