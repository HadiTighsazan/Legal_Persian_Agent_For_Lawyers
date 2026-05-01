# PRD: E09 — Frontend Document Management

**Status:** Ready for Implementation  
**Epic:** E09  
**Depends On:** E08 (Auth & Layout shell ✅), E03 (Upload API ✅), E04 (Processing API ✅), E05 (Embed API ✅)  
**Output Path:** `src/frontend/`  
**Stack:** React + Vite + TailwindCSS + shadcn/ui (already bootstrapped in E08)

---

## Objective

Build the complete Document Management UI: upload flow, document list with status badges, detail view, processing status polling, and delete confirmation. The UI consumes existing backend APIs exclusively — no new backend work required.

---

## API Contracts Used (Read-Only Reference)

| Method | Endpoint | Used In |
|--------|----------|---------|
| `POST` | `/documents/upload` | T01 — Upload flow |
| `GET` | `/documents` | T02 — Document list |
| `GET` | `/documents/{id}` | T03 — Detail view |
| `DELETE` | `/documents/{id}` | T04 — Delete flow |
| `GET` | `/documents/{id}/processing-status/` | T03 — Status polling |
| `POST` | `/documents/{document_id}/process/` | T03 — Trigger processing |
| `POST` | `/documents/{document_id}/embed/` | T03 — Trigger embedding |

---

## Database Tables Referenced (Read-Only — No Migrations Required)

- `documents` — `id`, `title`, `original_filename`, `file_size`, `total_pages`, `status`, `processing_status`, `created_at`
- `processing_tasks` — `task_type`, `status`, `progress`, `error_message` (consumed via API response, not direct DB access)

---

## Global Frontend Rules (apply to ALL tasks)

1. **API client:** All HTTP calls go through `src/frontend/src/lib/api.ts` (Axios or fetch wrapper already created in E08). Use the `Authorization: Bearer <token>` header from the auth store.
2. **Error handling:** Every API call must handle `401` (redirect to `/login`), `403` (show toast "Access denied"), `4xx` (show field or toast error), `5xx` (show generic toast "Server error, try again").
3. **Loading states:** Every async operation must have a visible loading skeleton or spinner — never a blank screen.
4. **TypeScript:** Strict mode. All API response shapes must have a corresponding `interface` or `type` in `src/frontend/src/types/`.
5. **No inline styles.** Use Tailwind utility classes only.
6. **shadcn/ui components:** Prefer existing shadcn primitives (`Dialog`, `Button`, `Badge`, `Progress`, `Toast`, `Table`, `Skeleton`) over custom implementations.
7. **Route structure:** All document pages live under the `/documents` protected route already defined in E08's router.
8. **Test files:** Each component gets a `.test.tsx` co-located test using Vitest + React Testing Library. Minimum: render smoke test + one interaction test.

---

## Micro-Tasks

---

### T01 — Document Upload Page & Flow

**File targets:**
- `src/frontend/src/pages/documents/UploadPage.tsx` ← new
- `src/frontend/src/components/documents/DropZone.tsx` ← new
- `src/frontend/src/lib/api/documents.ts` ← new (document API functions)
- `src/frontend/src/types/document.ts` ← new
- `src/frontend/src/pages/documents/UploadPage.test.tsx` ← new
- `src/frontend/src/components/documents/DropZone.test.tsx` ← new

**Route:** `/documents/upload`

**Types to define in `document.ts`:**
```ts
export type DocumentStatus = 'uploaded' | 'processing' | 'completed' | 'failed';
export type ProcessingStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface Document {
  id: string;
  title: string;
  original_filename: string;
  file_size: number;
  total_pages: number | null;
  status: DocumentStatus;
  processing_status: ProcessingStatus;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  id: string;
  title: string;
  original_filename: string;
  file_size: number;
  total_pages: null;
  status: 'uploaded';
  created_at: string;
}
```

**API function to implement in `documents.ts`:**
```ts
uploadDocument(file: File, title?: string): Promise<UploadResponse>
// POST /documents/upload — multipart/form-data with fields: file, title (optional)
```

**DropZone component behavior:**
- Accept drag-and-drop and click-to-browse
- Validate: only `application/pdf`, max `500MB` — show inline error if violated (do NOT call the API)
- Show file name + size preview after file is selected
- Single file only (replace on re-drop)

**UploadPage behavior:**
- Title field (optional `<input>`, defaults to filename without extension if left blank)
- Upload button triggers `uploadDocument()`
- During upload: show a `<Progress>` bar driven by `XMLHttpRequest.upload.onprogress` (percentage)
- On `201 Created`: show success toast "Document uploaded!" and navigate to `/documents/{id}` (the new document's detail page)
- On error: show toast with appropriate message per error code (see Global Rules)

**Acceptance Criteria:**
- [ ] PDF-only validation fires before any network request
- [ ] 500MB size limit enforced client-side
- [ ] Progress bar reflects real upload progress (not fake)
- [ ] On success, user is redirected to the new document's detail page
- [ ] Smoke test renders DropZone without crashing
- [ ] Interaction test: dropping a non-PDF file shows an error message

---

### T02 — Document List Page

**File targets:**
- `src/frontend/src/pages/documents/DocumentListPage.tsx` ← new
- `src/frontend/src/components/documents/DocumentCard.tsx` ← new
- `src/frontend/src/components/documents/StatusBadge.tsx` ← new
- `src/frontend/src/lib/api/documents.ts` ← extend (add `listDocuments`)
- `src/frontend/src/pages/documents/DocumentListPage.test.tsx` ← new

**Route:** `/documents` (the index route for the documents section)

**API function to add:**
```ts
listDocuments(params?: {
  page?: number;
  page_size?: number;
  status?: DocumentStatus;
  search?: string;
}): Promise<PaginatedResponse<Document>>

// PaginatedResponse shape:
interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
```

**StatusBadge component:**
- Maps `processing_status` → colored badge:
  - `pending` → gray "Pending"
  - `processing` → blue (animated pulse) "Processing"
  - `completed` → green "Ready"
  - `failed` → red "Failed"
- Maps `status` (upload status) → badge only if `processing_status` is not the primary signal

**DocumentCard component:**
- Shows: `title`, `original_filename`, `file_size` (formatted: KB/MB/GB), `total_pages` (or "—" if null), `created_at` (formatted: "Apr 22, 2026"), `StatusBadge`
- Full card is clickable → navigates to `/documents/{id}`
- Must NOT include delete button (delete lives on detail page only)

**DocumentListPage behavior:**
- On mount: fetch `GET /documents?page=1&page_size=20`
- While loading: show 3× `<Skeleton>` cards
- Empty state: if `count === 0`, show centered message "No documents yet" with a "Upload your first document" button linking to `/documents/upload`
- Pagination: show "Previous / Next" buttons if `next` or `previous` is not null. Page number displayed as "Page X".
- Search bar: debounced (300ms) `search` query param — re-fetches on change
- Filter dropdown: filter by `status` (All / Ready / Processing / Failed)

**Acceptance Criteria:**
- [ ] Skeleton shown during initial load
- [ ] Empty state rendered when API returns `count: 0`
- [ ] StatusBadge renders correct color and label for each `processing_status` value
- [ ] Search input is debounced (no request fires on every keystroke)
- [ ] Clicking a card navigates to correct detail page
- [ ] Smoke test: renders list with mocked API response
- [ ] Interaction test: empty state renders "Upload your first document" button

---

### T03 — Document Detail Page & Processing Status Polling

**File targets:**
- `src/frontend/src/pages/documents/DocumentDetailPage.tsx` ← new
- `src/frontend/src/components/documents/ProcessingStatusPanel.tsx` ← new
- `src/frontend/src/hooks/useProcessingStatus.ts` ← new
- `src/frontend/src/lib/api/documents.ts` ← extend (add `getDocument`, `getProcessingStatus`, `triggerProcessing`, `triggerEmbedding`)
- `src/frontend/src/pages/documents/DocumentDetailPage.test.tsx` ← new

**Route:** `/documents/:documentId`

**API functions to add:**
```ts
getDocument(id: string): Promise<Document>
// GET /documents/{id}

getProcessingStatus(id: string): Promise<ProcessingStatusResponse>
// GET /documents/{id}/processing-status/

triggerProcessing(id: string): Promise<{ task_id: string; status: string; document_id: string }>
// POST /documents/{id}/process/

triggerEmbedding(id: string): Promise<{ task_id: string; task_type: string; status: string; document_id: string; total_chunks: number }>
// POST /documents/{id}/embed/
```

**Types to add:**
```ts
export interface ProcessingTask {
  task_type: 'extract' | 'chunk' | 'embed';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  error_message: string | null;
}

export interface ProcessingStatusResponse {
  document_id: string;
  status: ProcessingStatus;
  progress: number;
  tasks: ProcessingTask[];
}
```

**`useProcessingStatus` hook:**
```ts
// Polls GET /documents/{id}/processing-status/ every 3 seconds
// STOPS polling when status === 'completed' or status === 'failed'
// Returns: { statusData, isPolling, error }
// Must clean up interval on unmount
useProcessingStatus(documentId: string, enabled: boolean): { ... }
```

**DocumentDetailPage layout (top to bottom):**
1. Back button → `/documents`
2. Document title (h1) + `original_filename` (muted subtitle)
3. Metadata row: file size, total pages, created date
4. `ProcessingStatusPanel` (conditional — see below)
5. Action buttons row: "Start Chat" (→ `/conversations/new?documentId=X`) | "Delete" (opens confirm dialog)

**ProcessingStatusPanel component:**
- Rendered when `processing_status !== 'completed'`
- Shows per-task rows using the `tasks` array from `ProcessingStatusResponse`:
  - Task type label (`Extract` / `Chunk` / `Embed`)
  - `<Progress value={task.progress} />` bar
  - Status badge
  - Error message (if `status === 'failed'`)
- If `processing_status === 'uploaded'` (not yet triggered): show "Start Processing" button → calls `triggerProcessing(id)` then starts polling
- If `processing_status === 'completed'`: panel is hidden; "Start Chat" button becomes active
- If `processing_status === 'failed'`: show "Retry" button (calls `triggerProcessing` again, resets polling)
- After processing completes, if embedding hasn't started: show "Generate Embeddings" button → calls `triggerEmbedding(id)`

**Acceptance Criteria:**
- [ ] Polling starts automatically when document is in `processing` state
- [ ] Polling stops when `status` reaches `completed` or `failed`
- [ ] Interval is cleared on component unmount (no memory leak)
- [ ] "Start Chat" button is disabled/hidden until `processing_status === 'completed'`
- [ ] Each task row shows correct progress bar value and status badge
- [ ] Smoke test renders detail page with mocked completed document
- [ ] Hook test: polling stops after status becomes `completed`

---

### T04 — Delete Document Flow

**File targets:**
- `src/frontend/src/components/documents/DeleteDocumentDialog.tsx` ← new
- `src/frontend/src/lib/api/documents.ts` ← extend (add `deleteDocument`)
- `src/frontend/src/components/documents/DeleteDocumentDialog.test.tsx` ← new

**API function to add:**
```ts
deleteDocument(id: string): Promise<void>
// DELETE /documents/{id} — expects 204 No Content
```

**DeleteDocumentDialog component (shadcn `<Dialog>`):**
- Trigger: "Delete" button on `DocumentDetailPage`
- Dialog content: "Are you sure you want to delete **{title}**? This will permanently remove all chunks, embeddings, and conversation history."
- Two buttons: "Cancel" (closes dialog, no action) | "Delete" (red/destructive variant)
- While deleting: "Delete" button shows spinner and is disabled; "Cancel" is also disabled
- On `204`: close dialog, show success toast "Document deleted", navigate to `/documents`
- On error: close dialog, show error toast with message

**Acceptance Criteria:**
- [ ] Dialog does not close on outside click while deletion is in progress
- [ ] Cancel button closes dialog without any API call
- [ ] On success, user is redirected to `/documents` with a success toast
- [ ] On API error, toast shows without navigating away
- [ ] Smoke test: dialog renders with title in confirmation text
- [ ] Interaction test: clicking Cancel closes dialog; clicking Delete calls `deleteDocument` once

---

### T05 — Navigation Wiring & Route Registration

**File targets:**
- `src/frontend/src/router.tsx` (or equivalent router file from E08) ← modify
- `src/frontend/src/components/layout/Sidebar.tsx` (or nav component from E08) ← modify

**Tasks:**
1. Register routes in the router under the existing authenticated route guard:
   ```
   /documents           → DocumentListPage
   /documents/upload    → UploadPage
   /documents/:documentId → DocumentDetailPage
   ```
2. Add "Documents" nav link to Sidebar/NavBar (with active state highlight when path starts with `/documents`)
3. Add a floating "Upload" button or CTA on the `/documents` list page that links to `/documents/upload`
4. Ensure the authenticated route guard (from E08) wraps all three routes — unauthenticated users are redirected to `/login`

**Acceptance Criteria:**
- [ ] All three routes are accessible when authenticated
- [ ] Visiting any `/documents/*` route while logged out redirects to `/login`
- [ ] "Documents" nav item is highlighted when on any documents page
- [ ] No TypeScript errors (`tsc --noEmit` passes)
- [ ] No console errors on any route

---

## Definition of Done (Epic E09)

The epic is complete when ALL of the following pass:

- [ ] All 5 micro-tasks are merged
- [ ] `tsc --noEmit` exits with code 0
- [ ] All `.test.tsx` files pass (`vitest run` exits with code 0)
- [ ] Upload → List → Detail → Delete round-trip works end-to-end against the running backend
- [ ] Processing status polling stops correctly and does not cause React memory leak warnings
- [ ] No hardcoded API base URLs — all use the env var `VITE_API_BASE_URL`
- [ ] No `any` types in TypeScript (ESLint `@typescript-eslint/no-explicit-any` passes)

---

## Task Execution Order

```
T05 (routes) → T01 (upload) → T02 (list) → T03 (detail + polling) → T04 (delete)
```

Register routes first (T05) so each subsequent task can be immediately tested in the browser as it lands. T04 (delete) depends on T03's detail page existing, so it goes last.

---

## Out of Scope for E09

- Chat/conversation UI (E10)
- Message streaming (E10)
- API key management (E12)
- Retry failed processing tasks via UI (can be added in E11/E12)
- Mobile responsiveness beyond basic Tailwind breakpoints