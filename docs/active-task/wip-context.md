# WIP Context — T03 Document Detail Page & Processing Status Polling

## What was just completed

### T03 — Document Detail Page & Processing Status Polling (Full Implementation)

**Types:**
- [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts) — Added missing fields to `Document` interface: `mime_type?`, `error_message?`, `processing_status?`, `chunks_count?`. Verified `ProcessingTask` and `ProcessingStatusResponse` are correct.

**API Layer:**
- [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts) — Added 5 new API functions:
  - `getDocument(id)` — `GET /documents/{id}/`
  - `getProcessingStatus(id)` — `GET /documents/{id}/processing-status/`
  - `triggerProcessing(id)` — `POST /documents/{id}/process/`
  - `triggerEmbedding(id)` — `POST /documents/{id}/embed/`
  - `deleteDocument(id)` — `DELETE /documents/{id}/`

**Custom Hook:**
- [`src/frontend/src/hooks/useProcessingStatus.ts`](src/frontend/src/hooks/useProcessingStatus.ts) — **NEW** — Custom React hook that polls `GET /documents/{id}/processing-status/` every 3 seconds:
  - Uses `useState` for `statusData`, `isPolling`, `error`
  - Uses `useRef` for interval ID (cleanup)
  - `useEffect` with `[documentId, enabled]` dependencies
  - Calls `poll()` immediately (no 3s wait for first poll)
  - **Stops polling** when `statusData.status === 'completed'` or `'failed'`
  - Error handling: catches errors, sets `error` state, continues polling on transient errors
  - Cleanup: `clearInterval(intervalId)` on unmount or deps change

**Components:**
- [`src/frontend/src/components/documents/ProcessingStatusPanel.tsx`](src/frontend/src/components/documents/ProcessingStatusPanel.tsx) — **NEW** — Per-task progress rows:
  - Hidden when `processingStatus === 'completed'`
  - Loading state: "Checking processing status..." with spinner
  - Per-task rows: task type label (mapped to human-readable), `<Progress>` bar, `StatusBadge`, error message
  - Action buttons: "Start Processing" (uploaded), "Retry" (failed), "Generate Embeddings" (completed tasks)

**Page:**
- [`src/frontend/src/pages/documents/DocumentDetailPage.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.tsx) — **NEW** — Full detail page layout:
  - Back button → navigates to `/documents`
  - Title (`h1`) + filename subtitle
  - Metadata section: file size (formatted), total pages, created date, status badge
  - Error message display if `document.error_message` is set
  - `ProcessingStatusPanel` (conditional — hidden when completed)
  - Action buttons: "Start Chat" → `/conversations/new?documentId={id}`, "Delete" → `window.confirm` + `deleteDocument` + navigate back
  - Loading state: skeleton layout with `animate-pulse`
  - Error state: `Alert` with retry button
  - Not found state: 404 message with "Go to Documents" button
  - Data state: full detail layout

**Routing:**
- [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) — Updated import from `@/pages/DocumentDetailPage` to `@/pages/documents/DocumentDetailPage`
- Deleted old stub file [`src/frontend/src/pages/DocumentDetailPage.tsx`](src/frontend/src/pages/DocumentDetailPage.tsx)

**Tests:**
- [`src/frontend/src/pages/documents/DocumentDetailPage.test.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.test.tsx) — **NEW** — 5 tests:
  1. Smoke test: renders completed document with title, filename, metadata, Start Chat/Delete buttons, ProcessingStatusPanel hidden
  2. Loading state: skeleton visible while fetching
  3. Error state: error alert + retry button
  4. Not found: "Document not found" message
  5. Processing state: ProcessingStatusPanel visible when document is processing
- [`src/frontend/src/hooks/useProcessingStatus.test.tsx`](src/frontend/src/hooks/useProcessingStatus.test.tsx) — **NEW** — 3 tests:
  1. Polling stops after status becomes completed (uses `vi.useFakeTimers`)
  2. Does not poll when `documentId` is undefined
  3. Does not poll when `enabled` is false

### DEBUG FIX — Backend missing DocumentDetailView (404 error)

**Problem:** Clicking a document in the Documents list resulted in `Page not found at /documents/{uuid}/` (404). The backend had no route for `GET /documents/{id}/`.

**Root Cause:** The backend [`src/backend/documents/urls.py`](src/backend/documents/urls.py) had routes for `process/`, `processing-status/`, `chunks/`, `embed/`, `search/`, `query/` but NO route for just `"<uuid:document_id>/"` (a simple document detail view).

**Fix Applied:**
- Created `DocumentDetailView` in [`src/backend/documents/views.py`](src/backend/documents/views.py) with:
  - `get()`: Returns full document details including `mime_type`, `processing_status`, `error_message`, `chunks_count` (mapped from `total_chunks`). Verifies ownership (403) and existence (404).
  - `delete()`: Deletes document, returns `204 No Content`. Verifies ownership (403) and existence (404).
- Added route `path("<uuid:document_id>/", DocumentDetailView.as_view(), name="document-detail")` in [`src/backend/documents/urls.py`](src/backend/documents/urls.py) — placed after `upload/` but before sub-routes like `process/` to avoid conflicts.
- Restarted backend container via `docker-compose restart backend`.

**Verification:**
- Backend `manage.py check` passes (0 issues)
- All 56 backend view tests pass
- The 1 failing test (`test_tasks.py`) is a pre-existing network issue (tiktoken can't download encoding data) — unrelated to changes

## Current state of the code

- **All 30 Vitest tests pass** (6 test files) ✅
- **All 56 backend view tests pass** ✅
- **Backend checks pass** (0 issues) ✅
- Frontend `DocumentDetailPage` is fully functional with all states:
  - Loading, error, not found, and data states all handled
  - Processing status polling via `useProcessingStatus` hook
  - Action buttons: Start Chat, Delete (with confirmation), Start Processing, Retry, Generate Embeddings
- Backend `DocumentDetailView` handles both GET (full details) and DELETE (204 No Content) for `/documents/{id}/`
- Old stub file deleted, routing updated

## Files created/modified

| File | Change |
|------|--------|
| [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts) | Added `mime_type`, `error_message`, `processing_status`, `chunks_count` to `Document` |
| [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts) | Added `getDocument`, `getProcessingStatus`, `triggerProcessing`, `triggerEmbedding`, `deleteDocument` |
| [`src/frontend/src/hooks/useProcessingStatus.ts`](src/frontend/src/hooks/useProcessingStatus.ts) | **NEW** — Custom polling hook with 3s interval, auto-stop on completed/failed |
| [`src/frontend/src/components/documents/ProcessingStatusPanel.tsx`](src/frontend/src/components/documents/ProcessingStatusPanel.tsx) | **NEW** — Per-task progress rows with status badges and action buttons |
| [`src/frontend/src/pages/documents/DocumentDetailPage.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.tsx) | **NEW** — Full detail page with all sections |
| [`src/frontend/src/pages/documents/DocumentDetailPage.test.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.test.tsx) | **NEW** — 5 tests (smoke, loading, error, not found, processing) |
| [`src/frontend/src/hooks/useProcessingStatus.test.tsx`](src/frontend/src/hooks/useProcessingStatus.test.tsx) | **NEW** — 3 hook tests (polling stop, disabled states) |
| [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) | Updated import path for `DocumentDetailPage` |
| [`src/frontend/src/pages/DocumentDetailPage.tsx`](src/frontend/src/pages/DocumentDetailPage.tsx) | **DELETED** — Old stub file |
| [`src/backend/documents/views.py`](src/backend/documents/views.py) | **NEW** `DocumentDetailView` class with `get()` and `delete()` methods |
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | Added route `"<uuid:document_id>/"` for document detail/delete |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | Marked `GET /documents/{id}/` and `DELETE /documents/{id}/` as implemented |

## Next step

N/A — Task complete. All frontend tests pass (30/30), all backend view tests pass (56/56). Ready for review.
