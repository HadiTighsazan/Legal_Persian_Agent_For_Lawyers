# WIP Context — T05: Navigation Wiring & Route Registration

## What was just completed

Task T05 — Navigation Wiring & Route Registration has been fully implemented.

### Files Created
- [`src/frontend/src/pages/DocumentListPage.tsx`](../../src/frontend/src/pages/DocumentListPage.tsx) — Placeholder component for `/documents`
- [`src/frontend/src/pages/UploadPage.tsx`](../../src/frontend/src/pages/UploadPage.tsx) — Placeholder component for `/documents/upload`
- [`src/frontend/src/pages/DocumentDetailPage.tsx`](../../src/frontend/src/pages/DocumentDetailPage.tsx) — Placeholder component for `/documents/:documentId`

### Files Modified
- [`src/frontend/src/App.tsx`](../../src/frontend/src/App.tsx) — Added imports for the 3 new page components and registered their routes under `PrivateRoute` > `AppShell`
- [`src/frontend/src/components/layout/Sidebar.tsx`](../../src/frontend/src/components/layout/Sidebar.tsx) — Removed `disabled: true` from Documents nav item; changed active-state detection to `startsWith('/documents')` prefix match

### Verification
- `npx tsc --noEmit` passes with zero errors

## Current state of the code

- All 3 document routes (`/documents`, `/documents/upload`, `/documents/:documentId`) are registered and accessible when authenticated
- The "Documents" nav link in the sidebar is enabled and highlights on any `/documents/*` path
- Placeholder pages render without crashing
- Existing auth flow (PrivateRoute/PublicRoute) remains unchanged

## Next step

Proceed with T01, T02, or T03 to replace the placeholder pages with full implementations.
