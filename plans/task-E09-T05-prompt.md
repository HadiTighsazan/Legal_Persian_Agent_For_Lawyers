# T05 — Navigation Wiring & Route Registration

## Goal

Register all document routes and enable the Documents nav link in the sidebar.

## Files to Modify

1. [`src/frontend/src/App.tsx`](../src/frontend/src/App.tsx) — Add document routes under `PrivateRoute` + `AppShell`
2. [`src/frontend/src/components/layout/Sidebar.tsx`](../src/frontend/src/components/layout/Sidebar.tsx) — Enable "Documents" nav link, add active-state detection for `/documents/*`

## Files to Create

3. [`src/frontend/src/pages/DocumentListPage.tsx`](../src/frontend/src/pages/DocumentListPage.tsx) — Placeholder component
4. [`src/frontend/src/pages/UploadPage.tsx`](../src/frontend/src/pages/UploadPage.tsx) — Placeholder component
5. [`src/frontend/src/pages/DocumentDetailPage.tsx`](../src/frontend/src/pages/DocumentDetailPage.tsx) — Placeholder component

---

## Step-by-Step Implementation

### Step 1: Create Placeholder Page Components

Create three minimal placeholder components so the app compiles. These will be replaced by T01, T02, and T03 later.

**File: `src/frontend/src/pages/DocumentListPage.tsx`**

```tsx
export default function DocumentListPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
        <p className="mt-1 text-muted-foreground">
          Browse and manage your uploaded documents.
        </p>
      </div>
    </div>
  );
}
```

**File: `src/frontend/src/pages/UploadPage.tsx`**

```tsx
export default function UploadPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Upload Document</h1>
        <p className="mt-1 text-muted-foreground">
          Upload a new document to your knowledge base.
        </p>
      </div>
    </div>
  );
}
```

**File: `src/frontend/src/pages/DocumentDetailPage.tsx`**

```tsx
import { useParams } from 'react-router-dom';

export default function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Document Detail</h1>
        <p className="mt-1 text-muted-foreground">
          Viewing document: <span className="font-mono">{documentId}</span>
        </p>
      </div>
    </div>
  );
}
```

### Step 2: Register Routes in App.tsx

Import the three new page components and add their routes under the existing `PrivateRoute` > `AppShell` children.

**Changes to `src/frontend/src/App.tsx`:**

1. Add imports for the three page components (after the existing `DashboardPage` import on line 5):

```tsx
import DocumentListPage from '@/pages/DocumentListPage';
import UploadPage from '@/pages/UploadPage';
import DocumentDetailPage from '@/pages/DocumentDetailPage';
```

2. Add routes inside the `AppShell` children array (after the `/dashboard` route on line 27):

```tsx
{ path: '/documents', element: <DocumentListPage /> },
{ path: '/documents/upload', element: <UploadPage /> },
{ path: '/documents/:documentId', element: <DocumentDetailPage /> },
```

### Step 3: Update Sidebar.tsx

Two changes needed:

1. **Remove `disabled: true`** from the "Documents" nav item (line 29).
2. **Change active-state detection** for the Documents item from exact match (`location.pathname === item.href`) to prefix match (`location.pathname.startsWith('/documents')`).

**Changes to `src/frontend/src/components/layout/Sidebar.tsx`:**

1. On line 29, change from:
   ```tsx
   disabled: true,
   ```
   to:
   ```tsx
   // disabled: true,  // removed — Documents nav is now active
   ```

2. On line 87, change the active-state logic from:
   ```tsx
   const isActive = location.pathname === item.href;
   ```
   to:
   ```tsx
   const isActive =
     item.href === '/documents'
       ? location.pathname.startsWith('/documents')
       : location.pathname === item.href;
   ```

---

## Acceptance Criteria

- ✅ All 3 document routes accessible when authenticated
- ✅ Redirect to `/login` when not authenticated (handled by existing `PrivateRoute`)
- ✅ "Documents" nav link highlights on any `/documents/*` path (list, upload, detail)
- ✅ Placeholder pages render without crashing
- ✅ App compiles without TypeScript or build errors

---

## Architecture Diagram

```mermaid
flowchart TD
    A[App.tsx Router] --> B[PublicRoute]
    A --> C[PrivateRoute]
    C --> D[AppShell]
    D --> E[/dashboard - DashboardPage]
    D --> F[/documents - DocumentListPage]
    D --> G[/documents/upload - UploadPage]
    D --> H[/documents/:documentId - DocumentDetailPage]
    B --> I[/login - LoginPage]
    B --> J[/register - RegisterPage]

    K[Sidebar.tsx] --> L{Documents link}
    L -->|startsWith /documents| M[Active highlight]
    L -->|exact match| N[No highlight for sub-routes]
```

## Route Table

| Path | Component | Auth Required | Nav Highlight |
|------|-----------|---------------|---------------|
| `/dashboard` | `DashboardPage` | Yes | Dashboard |
| `/documents` | `DocumentListPage` | Yes | Documents |
| `/documents/upload` | `UploadPage` | Yes | Documents |
| `/documents/:documentId` | `DocumentDetailPage` | Yes | Documents |
| `/login` | `LoginPage` | No (PublicRoute) | — |
| `/register` | `RegisterPage` | No (PublicRoute) | — |
