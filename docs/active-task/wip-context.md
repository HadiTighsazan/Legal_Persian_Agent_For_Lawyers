# WIP Context — T02 Document List Page Implementation

## What was just completed

### T02 — Document List Page (Full Implementation)

**Backend:**
- Added [`DocumentListView`](src/backend/documents/views.py:62) — a new API view at `GET /documents/` that returns a paginated, searchable, filterable list of the authenticated user's documents
- Supports query params: `page`, `page_size`, `search` (title contains), `status` (exact match)
- Uses Django's `Paginator` with clamped values (`page >= 1`, `page_size` 1–100)
- Results ordered by `-created_at` (newest first)
- Added route at [`src/backend/documents/urls.py`](src/backend/documents/urls.py:26) — `path("", DocumentListView.as_view(), name="document-list")` placed **before** `upload/` to avoid UUID routing conflicts

**Frontend — API Layer:**
- Added [`listDocuments()`](src/frontend/src/lib/api/documents.ts:20) function with `ListDocumentsParams` interface
- Uses existing `apiClient` from `@/api/axios`
- Builds query params dynamically, skipping undefined values

**Frontend — Components:**
- [`StatusBadge`](src/frontend/src/components/documents/StatusBadge.tsx) — Maps `status` field values (`uploaded`, `pending`, `processing`, `completed`, `failed`) to colored badges with appropriate Tailwind classes. `processing` gets `animate-pulse`.
- [`DocumentCard`](src/frontend/src/components/documents/DocumentCard.tsx) — Clickable card showing title, filename, file size (formatted), total pages, created date, and `StatusBadge`. Navigates to `/documents/:id` on click.

**Frontend — Page:**
- [`DocumentListPage`](src/frontend/src/pages/documents/DocumentListPage.tsx) — Full implementation with:
  - Search input with 300ms debounce (resets to page 1 on search)
  - Native `<select>` status filter dropdown (All, Completed, Processing, Failed, Uploaded)
  - Loading state: 3× skeleton cards with `animate-pulse`
  - Error state: `Alert` with `variant="destructive"` + retry button
  - Empty state: "No documents yet" + "Upload your first document" button
  - Data state: responsive grid (`grid-cols-1 md:grid-cols-2 lg:grid-cols-3`)
  - Pagination: Previous/Next buttons with "Page X of Y" indicator

**Frontend — Routing:**
- Updated [`App.tsx`](src/frontend/src/App.tsx:6) import from `@/pages/DocumentListPage` to `@/pages/documents/DocumentListPage`
- Deleted old stub file [`src/frontend/src/pages/DocumentListPage.tsx`](src/frontend/src/pages/DocumentListPage.tsx)

**Frontend — Tests:**
- [`DocumentListPage.test.tsx`](src/frontend/src/pages/documents/DocumentListPage.test.tsx) — 4 tests:
  1. Smoke test: renders cards when API returns 2 documents + verifies permanent Upload button in header
  2. Empty state: shows "Upload your first document" button + verifies permanent Upload button in header
  3. Loading state: skeleton cards visible (`.animate-pulse` elements)
  4. Error state: error alert + retry button visible

**Reference Docs:**
- Updated [`api-registry.md`](docs/references/api-registry.md) — marked `GET /documents` as ✅ Implemented with implementation date 2026-05-03 and notes

## Current state of the code

- **All 22 Vitest tests pass** (4 test files, including 4 new tests) ✅
- Backend `DocumentListView` is ready at `GET /documents/`
- Frontend `DocumentListPage` is fully functional with all states:
  - Header has permanent "Upload" button (always visible, links to `/documents/upload`)
  - Search with 300ms debounce, status filter dropdown, pagination
  - Loading, error, empty, and data states all handled
- Old stub file deleted, routing updated

## Files created/modified

| File | Change |
|------|--------|
| [`src/backend/documents/views.py`](src/backend/documents/views.py) | Added `DocumentListView` class with pagination, search, and status filtering |
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | Added `path("", DocumentListView.as_view(), name="document-list")` |
| [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts) | Added `listDocuments()` function and `ListDocumentsParams` interface |
| [`src/frontend/src/components/documents/StatusBadge.tsx`](src/frontend/src/components/documents/StatusBadge.tsx) | **NEW** — Status badge component with color mapping |
| [`src/frontend/src/components/documents/DocumentCard.tsx`](src/frontend/src/components/documents/DocumentCard.tsx) | **NEW** — Clickable document card with metadata |
| [`src/frontend/src/pages/documents/DocumentListPage.tsx`](src/frontend/src/pages/documents/DocumentListPage.tsx) | **NEW** — Full document list page with all states |
| [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) | Updated import path for `DocumentListPage` |
| [`src/frontend/src/pages/DocumentListPage.tsx`](src/frontend/src/pages/DocumentListPage.tsx) | **DELETED** — Old stub file |
| [`src/frontend/src/pages/documents/DocumentListPage.test.tsx`](src/frontend/src/pages/documents/DocumentListPage.test.tsx) | **NEW** — 4 tests (smoke, empty, loading, error) |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | Marked `GET /documents` as ✅ Implemented |

## Next step

N/A — Task complete. All tests pass (22/22). Ready for review.

## Latest update (2026-05-03)

- Added permanent "Upload" button to the page header (always visible, not just in empty state)
- Updated tests to verify the permanent Upload button is present in both data state and empty state
- **Fixed backend upload pipeline** to accept and store the user-provided `title` from the upload form (previously `title` was set to the UUID-based filename)
  - [`DocumentUploadSerializer`](src/backend/documents/serializers.py:13) — Added required `title` field
  - [`upload_document()`](src/backend/documents/services/upload_service.py:38) — Accepts `title` parameter, falls back to `unique_filename` if empty
  - [`create_document()`](src/backend/documents/repositories/document_repository.py:11) — Uses `title` parameter instead of `filename` for the `title` column
  - [`DocumentUploadView.post()`](src/backend/documents/views.py:155) — Extracts `title` from validated data and passes it to `upload_document`
- Updated serializer tests to cover the new `title` field
- Backend container restarted to pick up changes
- All 116 backend tests (serializer + views) and all 22 frontend tests pass ✅
