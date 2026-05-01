# T01 — Document Upload Page & Flow

## Goal

Implement the full document upload flow: drag-and-drop zone, file validation, progress bar, and redirect on success.

## Files to Create / Modify

| Action | File | Purpose |
|--------|------|---------|
| **CREATE** | `src/frontend/src/types/document.ts` | TypeScript interfaces for Document, UploadResponse, etc. |
| **CREATE** | `src/frontend/src/components/ui/progress.tsx` | shadcn `<Progress>` component (missing from codebase) |
| **CREATE** | `src/frontend/src/hooks/use-toast.ts` | shadcn `useToast` hook + `<Toaster>` (missing from codebase) |
| **CREATE** | `src/frontend/src/components/documents/DropZone.tsx` | Drag-and-drop file input with PDF validation |
| **MODIFY** | `src/frontend/src/pages/UploadPage.tsx` | Full upload form with title input, DropZone, progress bar, submit |
| **MODIFY** | `src/frontend/src/main.tsx` | Add `<Toaster />` component |

> **Note:** `src/frontend/src/lib/api/documents.ts` already exists with the `uploadDocument()` function using `XMLHttpRequest`. No changes needed there.
>
> **Note:** `src/frontend/src/App.tsx` already has the route `/documents/upload` pointing to `UploadPage`. No changes needed there.

---

## Step-by-Step Implementation

### Step 1 — Create `src/frontend/src/types/document.ts`

Define the following interfaces:

```typescript
export interface Document {
  id: string;
  title: string;
  original_filename: string;
  file_size: number;
  total_pages: number | null;
  status: string;
  created_at: string;
  updated_at?: string;
}

export interface UploadResponse {
  id: string;
  title: string;
  original_filename: string;
  file_size: number;
  total_pages: number | null;
  status: string;
  created_at: string;
}

export interface ProcessingTask {
  task_type: string;
  status: string;
  progress: number;
  error_message: string | null;
}

export interface ProcessingStatusResponse {
  document_id: string;
  status: string;
  progress: number;
  tasks: ProcessingTask[];
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
```

### Step 2 — Create `src/frontend/src/components/ui/progress.tsx`

Standard shadcn/ui `Progress` component using `@radix-ui/react-progress`. Since `@radix-ui/react-progress` is not in `package.json`, add it:

```bash
docker-compose exec frontend npm install @radix-ui/react-progress
```

The component:

```tsx
import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"
import { cn } from "@/lib/utils"

const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, ...props }, ref) => (
  <ProgressPrimitive.Root
    ref={ref}
    className={cn(
      "relative h-4 w-full overflow-hidden rounded-full bg-secondary",
      className
    )}
    {...props}
  >
    <ProgressPrimitive.Indicator
      className="h-full w-full flex-1 bg-primary transition-all"
      style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
    />
  </ProgressPrimitive.Root>
))
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }
```

### Step 3 — Create `src/frontend/src/hooks/use-toast.ts`

Standard shadcn `useToast` hook + `Toaster` component. This is needed because the codebase only has the primitive `toast.tsx` components but no hook or `Toaster`.

Create the file with the standard shadcn `use-toast` implementation (the one that uses `ToastProvider`, creates a `toast` function, and exports `Toaster` + `useToast`).

**Key exports:**
- `Toaster` — a component that renders `ToastProvider`, `ToastViewport`, and maps over toasts
- `useToast` — a hook returning `{ toast, dismiss, toasts }`
- `toast` — a standalone function for imperative toast calls

### Step 4 — Create `src/frontend/src/components/documents/DropZone.tsx`

A drag-and-drop file input component with:

**Props:**
```typescript
interface DropZoneProps {
  onFileSelect: (file: File) => void;
  onError: (error: string) => void;
  disabled?: boolean;
  accept?: string;  // default: ".pdf"
  maxSize?: number; // default: 500 * 1024 * 1024 (500MB)
}
```

**Behavior:**
- Renders a dashed-border drop area with an upload icon (use `Upload` from `lucide-react`)
- Shows "Drag & drop your PDF here, or click to browse" text
- Hidden `<input type="file">` triggered by clicking the zone
- **Drag events:** `onDragOver` (prevent default, add highlight class), `onDragLeave` (remove highlight), `onDrop` (prevent default, validate file)
- **Validation (client-side, no API call):**
  - File type must be `application/pdf` (or check extension `.pdf`)
  - File size must be ≤ 500MB
  - On invalid: call `onError("Only PDF files are allowed.")` or `onError("File size must be under 500MB.")`
- **On valid file:** call `onFileSelect(file)`
- When a file is selected, show the filename in the drop zone
- `disabled` prop disables the input and shows muted styling

**Styling:**
- Use `cn()` for conditional classes
- Highlight state: `border-primary` + `bg-accent/50` when dragging over
- Default: `border-dashed border-muted-foreground/25`
- Use `Upload` icon from `lucide-react`

### Step 5 — Modify `src/frontend/src/pages/UploadPage.tsx`

Replace the placeholder with the full upload form:

**State:**
- `title: string` — document title input
- `file: File | null` — selected file
- `uploading: boolean` — whether upload is in progress
- `progress: number` — upload progress percentage (0–100)
- `error: string | null` — error message to display

**Form layout (inside `<Card>`):**
1. **Title input** — `<Label>` + `<Input>` for document title (required)
2. **DropZone** — the component from Step 4
3. **Error alert** — if `error` is set, show a `<div className="text-sm text-destructive">` with the error
4. **Progress bar** — if `uploading`, show `<Progress value={progress} />` with percentage text
5. **Submit button** — `<Button disabled={!file || !title.trim() || uploading}>Upload</Button>`

**Upload flow:**
1. User fills title and drops/selects a file
2. Clicks "Upload"
3. Call `uploadDocument(file, title, { onProgress, onSuccess, onError })`
4. `onProgress`: set `progress` state
5. `onSuccess`: call `toast({ title: "Document uploaded!", description: "Redirecting..." })` then `navigate(\`/documents/${response.id}\`)`
6. `onError`: based on `error.status`:
   - `401` → `toast({ variant: "destructive", title: "Session expired", description: "Please log in again." })` + redirect to `/login`
   - `403` → `toast({ variant: "destructive", title: "Access denied" })`
   - `4xx` → show field error in the form
   - `5xx` → `toast({ variant: "destructive", title: "Server error", description: "Please try again." })`
   - Network error → `toast({ variant: "destructive", title: "Network error", description: "Check your connection." })`

**Imports needed:**
```typescript
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import DropZone from '@/components/documents/DropZone';
import { uploadDocument } from '@/lib/api/documents';
import { useToast } from '@/hooks/use-toast';
```

### Step 6 — Modify `src/frontend/src/main.tsx`

Add `<Toaster />` inside the `<React.StrictMode>` wrapper, after `<App />`.

```tsx
import { Toaster } from '@/hooks/use-toast';

// Inside React.StrictMode:
<App />
<Toaster />
```

---

## Test Plan (Manual — Browser Testing)

Since you mentioned you'll test manually in the browser:

1. **Navigate to `/documents/upload`** — verify the page renders with title input, drop zone, and disabled submit button
2. **Try submitting without file** — button should be disabled
3. **Try submitting without title** — button should be disabled
4. **Drop a non-PDF file** (e.g., `.txt`, `.png`) — verify error message "Only PDF files are allowed."
5. **Drop a PDF file** — verify the filename appears in the drop zone
6. **Enter a title and click Upload** — verify progress bar appears and updates
7. **On success (201)** — verify toast "Document uploaded!" and redirect to `/documents/{id}`
8. **Test error scenarios** (if backend returns errors) — verify appropriate toast messages

---

## Architecture Diagram

```mermaid
flowchart TD
    User([User]) -->|Navigates to /documents/upload| UploadPage[UploadPage.tsx]
    
    subgraph UploadPage
        Title[Title Input] --> DropZone[DropZone.tsx]
        DropZone -->|onFileSelect| State[file state]
        DropZone -->|onError| ErrorMsg[Error Display]
        State --> SubmitBtn[Upload Button]
        SubmitBtn -->|onClick| UploadFn[uploadDocument from api/documents.ts]
        
        UploadFn -->|XMLHttpRequest| Backend[POST /api/documents/upload/]
        Backend -->|201 Created| onSuccess[onSuccess callback]
        Backend -->|4xx/5xx| onError[onError callback]
        
        UploadFn -->|onprogress| ProgressBar[Progress component]
        
        onSuccess --> Toast[toast: Document uploaded!]
        Toast --> Navigate[navigate to /documents/{id}]
        
        onError -->|401| LoginRedirect[redirect to /login]
        onError -->|403/5xx| ErrorToast[toast: error message]
        onError -->|4xx| FieldError[show field error]
    end
```

## Dependencies to Install

```bash
docker-compose exec frontend npm install @radix-ui/react-progress
```

> `@radix-ui/react-toast` is already in `package.json` (listed as dependency via `@radix-ui/react-toast`).

## Notes for the Developer

1. The `uploadDocument()` function in `src/frontend/src/lib/api/documents.ts` already exists and is complete. Do NOT modify it.
2. The route `/documents/upload` is already registered in `App.tsx`. Do NOT modify `App.tsx`.
3. The `useToast` hook and `Toaster` component need to be created — they are standard shadcn patterns. The `toast.tsx` primitives already exist.
4. The `Progress` component needs to be created — it's a standard shadcn component.
5. Use `lucide-react` icons: `Upload` for the drop zone, `FileText` for file indicator, `Loader2` for loading state.
6. All new files should follow the existing code style (camelCase, TypeScript, functional components).
7. No test files should be created — the user will test manually in the browser.
