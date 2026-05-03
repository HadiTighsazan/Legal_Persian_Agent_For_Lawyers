# T03 — Document Detail Page & Processing Status Polling

## Overview

Implement a full document detail page with real-time processing status polling, action buttons (Start Chat, Delete), and a custom hook for polling. This task builds on existing types, API layer, and UI components.

---

## Files to Create

### 1. [`src/frontend/src/hooks/useProcessingStatus.ts`](src/frontend/src/hooks/useProcessingStatus.ts)

**Purpose:** Custom React hook that polls `GET /documents/{id}/processing-status/` every 3 seconds.

**Signature:**
```ts
function useProcessingStatus(
  documentId: string | undefined,
  enabled: boolean,
): {
  statusData: ProcessingStatusResponse | null;
  isPolling: boolean;
  error: string | null;
}
```

**Implementation details:**
- Uses `useState` for `statusData`, `isPolling`, `error`
- Uses `useRef` for interval ID (cleanup)
- `useEffect` with dependencies `[documentId, enabled]`:
  - If `!documentId || !enabled` → return early (no polling)
  - Define an `async function poll()` that calls `getProcessingStatus(documentId)`
  - Call `poll()` immediately (don't wait 3s for first poll)
  - Set up `setInterval(poll, 3000)`
  - **Stop polling** when `statusData.status === 'completed'` or `'failed'` — clear interval
  - Cleanup: `clearInterval(intervalId)` on unmount or when deps change
- Error handling: catch errors, set `error` state, continue polling (don't stop on transient errors)

### 2. [`src/frontend/src/components/documents/ProcessingStatusPanel.tsx`](src/frontend/src/components/documents/ProcessingStatusPanel.tsx)

**Purpose:** Per-task progress rows with status badges, action buttons.

**Props:**
```ts
interface ProcessingStatusPanelProps {
  documentId: string;
  processingStatus: string;       // document.processing_status
  statusData: ProcessingStatusResponse | null;
  isPolling: boolean;
  onStartProcessing: () => void;
  onRetry: (taskId: string) => void;
  onGenerateEmbeddings: () => void;
}
```

**Layout:**
- **Hidden** when `processingStatus === 'completed'` — return `null`
- **Loading state:** Show a "Checking processing status..." message when `isPolling && !statusData`
- **Per-task rows** (when `statusData?.tasks` exists):
  - Each row shows:
    - Task type label (e.g., "Extract Text", "Chunk Document", "Generate Embeddings") — map `task_type` to human-readable label
    - `<Progress>` bar with `value={task.progress}`
    - Status badge (reuse `StatusBadge` component, map task status: `pending`, `running`, `completed`, `failed`)
    - Error message if `task.error_message` is not null (red text below the row)
- **Action buttons** (shown based on `processingStatus`):
  - `processingStatus === 'uploaded'` → "Start Processing" button → calls `onStartProcessing`
  - `processingStatus === 'failed'` → "Retry" button → calls `onRetry` (needs task ID)
  - `processingStatus === 'completed'` (but only for tasks) → "Generate Embeddings" button → calls `onGenerateEmbeddings`

### 3. [`src/frontend/src/pages/documents/DocumentDetailPage.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.tsx)

**Purpose:** Full detail page layout replacing the existing stub at [`src/frontend/src/pages/DocumentDetailPage.tsx`](src/frontend/src/pages/DocumentDetailPage.tsx).

**Layout (top to bottom):**
1. **Back button** → navigates to `/documents`
2. **Title** (`h1`) + **filename** (subtitle in `text-muted-foreground`)
3. **Metadata section:**
   - File size (formatted using existing `formatFileSize` logic from `DocumentCard`)
   - Total pages
   - Created date (formatted using existing `formatDate` logic from `DocumentCard`)
   - Processing status badge (reuse `StatusBadge`)
4. **`ProcessingStatusPanel`** (conditional — only shown when document is not completed)
5. **Action buttons:**
   - "Start Chat" button → navigates to `/conversations/new?documentId={id}`
   - "Delete" button → opens a confirmation dialog (use `AlertDialog` or a simple `window.confirm`), calls `deleteDocument(id)`, navigates back to `/documents` on success

**Data flow:**
- On mount, fetch document details via `getDocument(documentId)` from URL params
- Pass `documentId` and `enabled=true` to `useProcessingStatus` hook
- Show loading skeleton while fetching document
- Show error state if fetch fails

**States to handle:**
- **Loading:** Skeleton layout (similar to `DocumentListPage` pattern)
- **Error:** Alert with retry button
- **Not found:** 404 message
- **Data:** Full detail layout as described above

### 4. [`src/frontend/src/pages/documents/DocumentDetailPage.test.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.test.tsx)

**Purpose:** Smoke test + hook test.

**Test plan:**
1. **Smoke test:** Renders detail page with mocked completed document
   - Mock `getDocument` to return a completed document
   - Mock `getProcessingStatus` to return completed status
   - Verify: title, filename, metadata, "Start Chat" button visible
   - Verify: `ProcessingStatusPanel` is hidden (status is completed)
2. **Hook test:** Polling stops after status becomes `completed`
   - Mock `getProcessingStatus` to return `processing` on first call, then `completed` on second call
   - Render the hook in a test component
   - Wait for polling to stop
   - Verify: `isPolling` becomes `false`, `statusData.status === 'completed'`

---

## Files to Modify

### 5. [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts)

**Add these API functions:**

```ts
// GET /documents/{id}/
export async function getDocument(id: string): Promise<Document>

// GET /documents/{id}/processing-status/
export async function getProcessingStatus(id: string): Promise<ProcessingStatusResponse>

// POST /documents/{id}/process/
export async function triggerProcessing(id: string): Promise<{ task_id: string; status: string; document_id: string }>

// POST /documents/{id}/embed/
export async function triggerEmbedding(id: string): Promise<{ task_id: string; task_type: string; status: string; document_id: string; total_chunks: number }>

// DELETE /documents/{id}/
export async function deleteDocument(id: string): Promise<void>
```

**Implementation notes:**
- All use `apiClient` from `@/api/axios`
- `getDocument` returns `Document` type (note: the API response includes `mime_type`, `error_message`, `chunks_count` — these may need to be added to the `Document` interface)
- `deleteDocument` returns `void` (204 No Content)
- `triggerProcessing` and `triggerEmbedding` return their respective response types

### 6. [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts)

**Add/update interfaces:**

The `ProcessingTask` and `ProcessingStatusResponse` interfaces already exist (lines 22-34). Verify they match the API response:

```ts
// Already exists — verify:
export interface ProcessingTask {
  task_type: string;       // "extract" | "chunk" | "embed"
  status: string;          // "pending" | "running" | "completed" | "failed"
  progress: number;        // 0-100
  error_message: string | null;
}

export interface ProcessingStatusResponse {
  document_id: string;
  status: string;          // overall processing status
  progress: number;        // 0-100
  tasks: ProcessingTask[];
}
```

**Add to `Document` interface** (if not already present):
- `mime_type?: string`
- `error_message?: string | null`
- `processing_status?: string`
- `chunks_count?: number`

These fields are returned by `GET /documents/{id}/` but may not be in the list response.

### 7. [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx)

**Update import:**
- Change `import DocumentDetailPage from '@/pages/DocumentDetailPage'` → `import DocumentDetailPage from '@/pages/documents/DocumentDetailPage'`
- Delete the old stub file [`src/frontend/src/pages/DocumentDetailPage.tsx`](src/frontend/src/pages/DocumentDetailPage.tsx)

---

## Implementation Order

| Step | File | Action | Description |
|------|------|--------|-------------|
| 1 | [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts) | Modify | Add missing fields to `Document` interface (mime_type, error_message, processing_status, chunks_count). Verify `ProcessingTask` and `ProcessingStatusResponse` are correct. |
| 2 | [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts) | Modify | Add `getDocument()`, `getProcessingStatus()`, `triggerProcessing()`, `triggerEmbedding()`, `deleteDocument()` |
| 3 | [`src/frontend/src/hooks/useProcessingStatus.ts`](src/frontend/src/hooks/useProcessingStatus.ts) | Create | Custom polling hook with 3s interval, auto-stop on completed/failed, cleanup on unmount |
| 4 | [`src/frontend/src/components/documents/ProcessingStatusPanel.tsx`](src/frontend/src/components/documents/ProcessingStatusPanel.tsx) | Create | Per-task progress rows with status badges and action buttons |
| 5 | [`src/frontend/src/pages/documents/DocumentDetailPage.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.tsx) | Create | Full detail page layout with all sections |
| 6 | [`src/frontend/src/pages/documents/DocumentDetailPage.test.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.test.tsx) | Create | Smoke test + hook test |
| 7 | [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) | Modify | Update import path for `DocumentDetailPage` |
| 8 | [`src/frontend/src/pages/DocumentDetailPage.tsx`](src/frontend/src/pages/DocumentDetailPage.tsx) | Delete | Old stub file |

---

## Key Implementation Details

### useProcessingStatus Hook

```mermaid
flowchart TD
    A[Component mounts] --> B{enabled && documentId?}
    B -- No --> C[Return: statusData=null, isPolling=false]
    B -- Yes --> D[Call poll immediately]
    D --> E[fetch GET /documents/{id}/processing-status/]
    E --> F{status === completed/failed?}
    F -- Yes --> G[Clear interval, isPolling=false]
    F -- No --> H[Set 3s interval for next poll]
    H --> E
    G --> I[Return: statusData, isPolling=false]
    D -- Error --> J[Catch error, set error state, continue polling]
    J --> H
```

### ProcessingStatusPanel Layout

```
┌─────────────────────────────────────────┐
│  Processing Status                      │
│                                         │
│  ┌─ Extract Text ────────────────────┐  │
│  │  [████████████████░░░░░░] 80%     │  │
│  │  Status: [Completed]              │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌─ Chunk Document ──────────────────┐  │
│  │  [████████████░░░░░░░░░░] 50%     │  │
│  │  Status: [Processing]             │  │
│  └───────────────────────────────────┘  │
│                                         │
│  [Start Processing] [Retry]             │
│  [Generate Embeddings]                  │
└─────────────────────────────────────────┘
```

### DocumentDetailPage Layout

```
┌─────────────────────────────────────────┐
│  ← Back to Documents                    │
│                                         │
│  # Document Title                       │
│  filename.pdf                           │
│                                         │
│  ┌─ Metadata ────────────────────────┐  │
│  │  Size: 1.2 MB  Pages: 42          │  │
│  │  Uploaded: Apr 18, 2026           │  │
│  │  Status: [Completed]              │  │
│  └───────────────────────────────────┘  │
│                                         │
│  ┌─ ProcessingStatusPanel ───────────┐  │
│  │  (conditional, see above)         │  │
│  └───────────────────────────────────┘  │
│                                         │
│  [Start Chat]  [Delete]                 │
└─────────────────────────────────────────┘
```

### API Endpoints Used

| Method | Endpoint | Function | Purpose |
|--------|----------|----------|---------|
| `GET` | `/documents/{id}/` | `getDocument()` | Fetch document details |
| `GET` | `/documents/{id}/processing-status/` | `getProcessingStatus()` | Poll processing status |
| `POST` | `/documents/{id}/process/` | `triggerProcessing()` | Start document processing |
| `POST` | `/documents/{id}/embed/` | `triggerEmbedding()` | Generate embeddings |
| `DELETE` | `/documents/{id}/` | `deleteDocument()` | Delete document |

### Testing

Run tests inside the Docker container:
```bash
docker-compose exec frontend npm test
```

Or for a specific test file:
```bash
docker-compose exec frontend npx vitest run src/pages/documents/DocumentDetailPage.test.tsx
```

### Notes

- The `Document` type in [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts) already has `ProcessingTask` and `ProcessingStatusResponse` — verify they match the API response format from [`docs/references/api-registry.md`](docs/references/api-registry.md) (lines 446-483)
- The `Progress` component from shadcn/ui is already available at [`src/frontend/src/components/ui/progress.tsx`](src/frontend/src/components/ui/progress.tsx)
- No `AlertDialog` component exists yet — use `window.confirm()` for the delete confirmation, or create a simple modal
- The existing [`src/frontend/src/pages/DocumentDetailPage.tsx`](src/frontend/src/pages/DocumentDetailPage.tsx) is a stub that needs to be replaced
- Route is already configured in [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) at line 33: `path: '/documents/:documentId'`
