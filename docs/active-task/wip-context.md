# WIP Context — Monitoring Page: PDF Text Extraction & Chunking Pipeline Visualizer

## Status: ✅ COMPLETED (2026-05-07) — Monitoring page implemented at `/monitoring`

All 9 steps from the implementation plan [`plans/plan-monitoring-page-chunk-visualization.md`](plans/plan-monitoring-page-chunk-visualization.md) have been implemented.

---

## What Changed

### Problem Summary

There was no developer-facing tool to inspect the PDF text extraction and chunking pipeline output. Debugging extraction quality (garbled text, extraction method selection) and chunk boundary placement required manual database queries. A monitoring page was needed to visualize the full pipeline: raw extracted text → chunk boundaries → chunk details/metadata.

### Changes Made

#### Backend — Model Changes (Step 1)

| # | File | Change | Description |
|---|------|--------|-------------|
| 1 | [`src/backend/documents/models.py`](src/backend/documents/models.py:88) | Added 3 fields to `Document` | `extracted_text` (TextField, blank=True, default=""), `extraction_method` (CharField max_length=20, null=True, blank=True), `garbled_score` (FloatField, null=True, blank=True) |
| 2 | [`src/backend/documents/migrations/0012_add_extracted_text_and_extraction_metadata.py`](src/backend/documents/migrations/0012_add_extracted_text_and_extraction_metadata.py) | New migration | Adds the 3 new fields, depends on `0011_normalize_presentation_forms` |

#### Backend — Processing Task (Step 2)

| # | File | Change | Description |
|---|------|--------|-------------|
| 3 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:56) | Extracted `_compute_garbled_ratio()` | Refactored from `_is_persian_text_garbled()` — returns float ratio (0.0–1.0) for reuse |
| 4 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:99) | `_is_persian_text_garbled()` now calls `_compute_garbled_ratio()` | Backward-compatible — existing callers unchanged |
| 5 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:487) | `extract_text_from_pdf` saves extraction metadata | After normalization, saves `extracted_text`, `extraction_method` (which fallback succeeded), `garbled_score`, `extracted_text_length`, `total_pages` to the document |

#### Backend — API Endpoint (Step 3)

| # | File | Change | Description |
|---|------|--------|-------------|
| 6 | [`src/backend/documents/views.py`](src/backend/documents/views.py:592) | Added `DocumentExtractedTextView` | `APIView` with `IsAuthenticated`, ownership check, returns JSON with document_id, extracted_text, extracted_text_length, total_pages, extraction_method, garbled_score |
| 7 | [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | Added URL route | `"<uuid:document_id>/extracted-text/"` → `DocumentExtractedTextView.as_view()` |

#### Frontend — API Layer (Step 4)

| # | File | Change | Description |
|---|------|--------|-------------|
| 8 | [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts:51) | Added TypeScript types | `ExtractedTextResponse`, `DocumentChunk`, `ChunksResponse` interfaces |
| 9 | [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts:278) | Added `getExtractedText()` | Fetches `GET /documents/{id}/extracted-text/` |
| 10 | [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts:294) | Added `getDocumentChunks()` | Fetches `GET /documents/{id}/chunks/` with `page_size=9999` |

#### Frontend — Monitoring Page UI (Step 5)

| # | File | Change | Description |
|---|------|--------|-------------|
| 11 | [`src/frontend/src/pages/MonitoringPage.tsx`](src/frontend/src/pages/MonitoringPage.tsx) | Created main monitoring page | Three-panel layout: RawTextPanel (monospace pre with `[PAGE N]` markers), ChunkVisualizationPanel (text with colored chunk boundary annotations), ChunkDetailsPanel (searchable chunk cards with metadata) |
| 12 | [`src/frontend/src/pages/MonitoringDocumentPicker.tsx`](src/frontend/src/pages/MonitoringDocumentPicker.tsx) | Created document picker | Searchable document list at `/monitoring` route, navigates to `/monitoring/:documentId` |

#### Frontend — Routing & Sidebar (Steps 6 & 7)

| # | File | Change | Description |
|---|------|--------|-------------|
| 13 | [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) | Added monitoring routes | `/monitoring` and `/monitoring/:documentId` inside `PrivateRoute`, outside `AppShell` (full-height layout) |
| 14 | [`src/frontend/src/components/layout/Sidebar.tsx`](src/frontend/src/components/layout/Sidebar.tsx) | Added Monitoring nav item | Uses `Activity` icon from lucide-react, href: `/monitoring` |

#### Reference Documentation (Step 8)

| # | File | Change | Description |
|---|------|--------|-------------|
| 15 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | Added 3 new columns | `extracted_text` (TEXT), `extraction_method` (varchar(20)), `garbled_score` (float8); documented Migration 0012 |
| 16 | [`docs/references/api-registry.md`](docs/references/api-registry.md) | Added endpoint docs | `GET /documents/{document_id}/extracted-text/` with response schema and example |

### Key Design Decisions

1. **`_compute_garbled_ratio()` extracted as standalone function** — The original `_is_persian_text_garbled()` only returned a boolean. We needed the raw float score for the monitoring page. The refactored function returns `float` (0.0–1.0), and `_is_persian_text_garbled()` now calls it internally with the default threshold, preserving backward compatibility.

2. **Three-panel layout outside AppShell** — The monitoring page uses its own full-height layout (not wrapped in `AppShell`) to maximize vertical space for code-like text display. The sidebar nav item still works via React Router navigation.

3. **Chunk boundary visualization** — The `ChunkVisualizationPanel` renders extracted text with colored `<mark>` tags at chunk boundaries, using a rotating palette of 10 colors. Each chunk is clickable to select it in the right panel.

4. **No auth enforcement beyond DRF permissions** — The `DocumentExtractedTextView` uses `IsAuthenticated` + ownership check, consistent with other document views. No additional monitoring-specific auth was added since this is a dev tool.

### Files Created
- `src/backend/documents/migrations/0012_add_extracted_text_and_extraction_metadata.py`
- `src/frontend/src/pages/MonitoringPage.tsx`
- `src/frontend/src/pages/MonitoringDocumentPicker.tsx`

### Files Modified
- `src/backend/documents/models.py` — Added 3 fields
- `src/backend/documents/tasks/document_processing.py` — Refactored garbled detection, save metadata
- `src/backend/documents/views.py` — Added `DocumentExtractedTextView`
- `src/backend/documents/urls.py` — Added URL route
- `src/frontend/src/types/document.ts` — Added TypeScript types
- `src/frontend/src/lib/api/documents.ts` — Added API functions
- `src/frontend/src/App.tsx` — Added monitoring routes
- `src/frontend/src/components/layout/Sidebar.tsx` — Added nav item
- `docs/references/database-schema.md` — Added new columns + migration
- `docs/references/api-registry.md` — Added endpoint documentation

---

## Rollback Plan

If any change causes regression:

1. **Model fields**: Revert `src/backend/documents/models.py` — remove `extracted_text`, `extraction_method`, `garbled_score` fields. Reverse migration 0012.
2. **Processing task**: Revert `_compute_garbled_ratio()` extraction and metadata saving in `document_processing.py`
3. **API endpoint**: Remove `DocumentExtractedTextView` from `views.py` and its URL route from `urls.py`
4. **Frontend types**: Remove `ExtractedTextResponse`, `DocumentChunk`, `ChunksResponse` from `types/document.ts`
5. **Frontend API**: Remove `getExtractedText()` and `getDocumentChunks()` from `lib/api/documents.ts`
6. **Frontend pages**: Delete `MonitoringPage.tsx` and `MonitoringDocumentPicker.tsx`
7. **Frontend routing**: Remove monitoring routes from `App.tsx`
8. **Frontend sidebar**: Remove Monitoring nav item from `Sidebar.tsx`
9. **Reference docs**: Revert `database-schema.md` and `api-registry.md` to previous state
