# Plan: Monitoring Page — PDF Text Extraction & Chunking Visualization

## Overview

Add a **developer-only** monitoring page at `/monitoring` that visualizes the full text extraction and chunking pipeline for a given document. This is a **dev tool**, not a production feature — no auth enforcement, no polish required, just functional utility.

The page shows:
1. The **extracted raw text** (with `[PAGE N]` markers) from the PDF
2. How that text was **split into chunks** — each chunk displayed with its index, page range, token count, and content
3. **Extraction metadata** — which extraction method was used, garbled detection scores
4. Visual separation between chunks so the developer can easily inspect chunk boundaries

---

## Architecture

### Data Flow

```
Frontend (/monitoring/:documentId)
    │
    ├── GET /api/documents/{id}/  →  Document metadata (title, pages, status)
    │
    ├── GET /api/documents/{id}/extracted-text/  →  Raw extracted text + extraction metadata
    │
    └── GET /api/documents/{id}/chunks/?page_size=9999  →  All chunks with content
```

### Backend Changes Needed

The existing [`GET /documents/{document_id}/chunks/`](src/backend/documents/views.py:508) endpoint already returns paginated chunks. We need:

1. **Store extracted text** on the Document model (currently not persisted)
2. **Store extraction metadata** (which method succeeded, garbled scores)
3. **New API endpoint** to return the extracted text + metadata

---

## Data Model Changes

**File:** [`src/backend/documents/models.py`](src/backend/documents/models.py)

| New Field | Type | Purpose |
|-----------|------|---------|
| `extracted_text` | `TextField(blank=True, default="")` | Store the full extracted PDF text for monitoring/debug |
| `extraction_method` | `CharField(max_length=20, null=True, blank=True)` | Which extractor succeeded: `pymupdf`, `pdfplumber`, `tesseract` |
| `garbled_score` | `FloatField(null=True, blank=True)` | The garbled detection ratio (0.0–1.0) from `_is_persian_text_garbled()` |

**Migration:** `0009_add_extracted_text_and_extraction_metadata.py`

---

## API Changes

### New Endpoint: `GET /documents/{id}/extracted-text/`

**Response:**
```json
{
  "document_id": "uuid",
  "extracted_text": "full extracted text with [PAGE N] markers...",
  "extracted_text_length": 50000,
  "total_pages": 42,
  "extraction_method": "pymupdf",
  "garbled_score": 0.12
}
```

**Auth Required:** Yes (IsAuthenticated)
**Ownership Check:** Yes (403 if wrong user)

---

## UI Layout (Three-Panel)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ← Back to Documents    Monitoring: "قانون مجازات اسلامی"           │
│  Method: PyMuPDF  |  Garbled Score: 0.12  |  Chunks: 42  |  Pages: 200 │
├───────────────────┬───────────────────────┬─────────────────────────┤
│  Raw Extracted    │  Chunk Visualization  │  Chunk Details          │
│  Text             │  (with boundaries)    │                         │
│                   │                       │  ┌─ Chunk #0 ────────┐ │
│  [PAGE 1]         │  [PAGE 1]             │  │ Pages: 1-3        │ │
│  بسم الله الرحمن   │  بسم الله الرحمن      │  │ Tokens: 512       │ │
│  الرحیم            │  الرحیم               │  │ Type: article     │ │
│                   │  ─── CHUNK 0 ───      │  │ ماده 1            │ │
│  قانون مجازات     │  قانون مجازات         │  │                   │ │
│  اسلامی           │  اسلامی               │  │ بسم الله الرحمن   │ │
│  ماده 1 - ...     │  ماده 1 - ...        │  │ الرحیم            │ │
│                   │  ─── CHUNK 1 ───      │  └───────────────────┘ │
│  [PAGE 2]         │  [PAGE 2]             │                         │
│  ماده 2 - ...     │  ماده 2 - ...        │  ┌─ Chunk #1 ────────┐ │
│                   │                       │  │ Pages: 3-5        │ │
│                   │                       │  │ Tokens: 480       │ │
│                   │                       │  │ ماده 2 - ...     │ │
│                   │                       │  └───────────────────┘ │
└───────────────────┴───────────────────────┴─────────────────────────┘
```

### Panel Descriptions

1. **Left Panel — Raw Extracted Text:**
   - Shows the exact output of the extraction step (with `[PAGE N]` markers)
   - Read-only, scrollable
   - Monospace font for precise inspection

2. **Center Panel — Chunk Visualization:**
   - Same extracted text but with **chunk boundary annotations** injected
   - Each chunk is separated by a colored horizontal rule: `─── CHUNK N [Pages X-Y] ───`
   - Different background colors for adjacent chunks (alternating)
   - This is the **key panel** for debugging chunk boundaries

3. **Right Panel — Chunk Details:**
   - Scrollable list of chunk cards
   - Each card shows: chunk index, page range, token count, legal type (if any), and expandable content
   - Clicking a chunk card scrolls the center panel to that chunk's position
   - Search/filter box to find chunks by content

---

## Implementation Steps

### Step 1: Backend — Add fields to Document model

**File:** [`src/backend/documents/models.py`](src/backend/documents/models.py)

Add three new fields:
```python
extracted_text = models.TextField(blank=True, default="")
extraction_method = models.CharField(max_length=20, null=True, blank=True)
garbled_score = models.FloatField(null=True, blank=True)
```

Create migration:
```bash
docker-compose exec backend python manage.py makemigrations documents
docker-compose exec backend python manage.py migrate
```

### Step 2: Backend — Save extraction metadata during processing

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)

In `extract_text_from_pdf`, after extraction succeeds:

1. Track which extraction method was used (pymupdf / pdfplumber / tesseract)
2. Calculate and store the garbled score
3. Save the extracted text

Key changes around lines 416-487:

```python
# Track which method succeeded
extraction_method = "pymupdf"  # default

# After Stage 1 (PyMuPDF)
extracted_text = _extract_with_pymupdf_rtl(...)
extraction_method = "pymupdf"

# After Stage 2 (pdfplumber fallback)
if auto_fallback and _is_garbled(extracted_text):
    extracted_text = _extract_with_pdfplumber(...)
    extraction_method = "pdfplumber"
    
    # After Stage 3 (Tesseract fallback)
    if _is_garbled(extracted_text):
        extracted_text = _extract_with_tesseract(...)
        extraction_method = "tesseract"

# Calculate garbled score on final text
garbled_ratio = None
if extracted_text:
    garbled_ratio = _is_persian_text_garbled(extracted_text)  # returns bool
    # Actually we need the ratio, not just bool
    # We should refactor _is_persian_text_garbled to return the ratio

# Save to document
document.extracted_text = extracted_text
document.extraction_method = extraction_method
document.garbled_score = garbled_score_value  # the actual ratio
document.extracted_text_length = len(extracted_text)
document.total_pages = num_pages
document.save(update_fields=["extracted_text", "extraction_method", 
                              "garbled_score", "extracted_text_length", "total_pages"])
```

**Note:** We need to refactor `_is_persian_text_garbled()` to also return the ratio, or create a helper that computes the ratio without the boolean comparison.

### Step 3: Backend — Add extracted-text API endpoint

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py)

Add `DocumentExtractedTextView`:

```python
class DocumentExtractedTextView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, document_id: str) -> Response:
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if document.user != request.user:
            return Response(
                {"error": "permission_denied", "message": "..."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response({
            "document_id": str(document.id),
            "extracted_text": document.extracted_text or "",
            "extracted_text_length": document.extracted_text_length,
            "total_pages": document.total_pages,
            "extraction_method": document.extraction_method,
            "garbled_score": document.garbled_score,
        })
```

### Step 4: Backend — Add URL route

**File:** [`src/backend/documents/urls.py`](src/backend/documents/urls.py)

```python
path(
    "<uuid:document_id>/extracted-text/",
    DocumentExtractedTextView.as_view(),
    name="document-extracted-text",
),
```

### Step 5: Frontend — Add API functions

**File:** [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts)

Add types and functions:

```typescript
export interface ExtractedTextResponse {
  document_id: string;
  extracted_text: string;
  extracted_text_length: number;
  total_pages: number | null;
  extraction_method: string | null;
  garbled_score: number | null;
}

export interface DocumentChunk {
  id: string;
  chunk_index: number;
  page_start: number;
  page_end: number;
  content: string;
  token_count: number | null;
  metadata: Record<string, unknown>;
}

export interface ChunksResponse {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  next: number | null;
  previous: number | null;
  results: DocumentChunk[];
}

export async function getExtractedText(id: string): Promise<ExtractedTextResponse> {
  const response = await apiClient.get<ExtractedTextResponse>(
    `documents/${id}/extracted-text/`,
  );
  return response.data;
}

export async function getDocumentChunks(
  id: string,
  pageSize: number = 9999,
): Promise<ChunksResponse> {
  const response = await apiClient.get<ChunksResponse>(
    `documents/${id}/chunks/`,
    { params: { page_size: pageSize } },
  );
  return response.data;
}
```

### Step 6: Frontend — Create MonitoringPage component

**File:** [`src/frontend/src/pages/MonitoringPage.tsx`](src/frontend/src/pages/MonitoringPage.tsx)

Main component with three-panel layout:

```tsx
// State
const [document, setDocument] = useState<Document | null>(null);
const [extractedText, setExtractedText] = useState<string>("");
const [chunks, setChunks] = useState<DocumentChunk[]>([]);
const [extractionMeta, setExtractionMeta] = useState<{...} | null>(null);
const [selectedChunk, setSelectedChunk] = useState<number | null>(null);
const [searchFilter, setSearchFilter] = useState<string>("");

// Effects
// 1. Fetch document details
// 2. Fetch extracted text
// 3. Fetch all chunks

// Render
<div className="flex flex-col h-[calc(100vh-8rem)]">
  {/* Header bar with metadata */}
  <HeaderBar document={document} extractionMeta={extractionMeta} />

  {/* Three-panel layout */}
  <div className="flex flex-1 gap-4 overflow-hidden">
    {/* Panel 1: Raw Text */}
    <RawTextPanel text={extractedText} />

    {/* Panel 2: Chunk Visualization */}
    <ChunkVisualizationPanel
      text={extractedText}
      chunks={chunks}
      selectedChunk={selectedChunk}
      onChunkClick={setSelectedChunk}
    />

    {/* Panel 3: Chunk Details */}
    <ChunkDetailsPanel
      chunks={chunks}
      selectedChunk={selectedChunk}
      searchFilter={searchFilter}
      onSearchChange={setSearchFilter}
    />
  </div>
</div>
```

### Step 7: Frontend — Add route

**File:** [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx)

Add route inside `PrivateRoute`, outside `AppShell` (for full-height layout):

```typescript
// Alongside other routes:
{ path: '/monitoring/:documentId', element: <MonitoringPage /> },
```

Also add a document picker at `/monitoring`:
```typescript
{ path: '/monitoring', element: <MonitoringDocumentPicker /> },
```

### Step 8: Frontend — Add sidebar navigation

**File:** [`src/frontend/src/components/layout/Sidebar.tsx`](src/frontend/src/components/layout/Sidebar.tsx)

```typescript
import { Activity } from 'lucide-react';

// In navItems array:
{
  label: 'Monitoring',
  icon: <Activity className="h-5 w-5" />,
  href: '/monitoring',
},
```

### Step 9: Frontend — Add types

**File:** [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts)

Add chunk-related types (or keep them in the API file).

### Step 10: Update reference docs

- [`docs/references/database-schema.md`](docs/references/database-schema.md) — Document new fields
- [`docs/references/api-registry.md`](docs/references/api-registry.md) — Document new endpoint
- [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) — Track progress

---

## Component Tree

```
MonitoringPage
├── MonitoringHeader
│   ├── BackButton
│   ├── DocumentTitle
│   └── ExtractionMetadata (method, garbled score, chunks count, pages)
├── RawTextPanel (left)
│   └── Scrollable pre/code block with monospace font
├── ChunkVisualizationPanel (center)
│   ├── TextWithChunkAnnotations
│   │   └── For each chunk: alternating background + boundary marker
│   └── ChunkBoundaryMarker (colored hr with chunk index label)
└── ChunkDetailsPanel (right)
    ├── SearchFilter (input to filter chunks by content)
    └── ChunkCardList
        └── ChunkCard (for each chunk)
            ├── ChunkHeader (index, pages, tokens, legal type)
            └── ChunkContent (expandable, truncated preview)
```

---

## Files to Create/Modify

### New Files
| # | File | Purpose |
|---|------|---------|
| 1 | [`src/frontend/src/pages/MonitoringPage.tsx`](src/frontend/src/pages/MonitoringPage.tsx) | Main monitoring page component |
| 2 | [`src/backend/documents/migrations/0009_add_extracted_text_and_extraction_metadata.py`](src/backend/documents/migrations/0009_add_extracted_text_and_extraction_metadata.py) | Migration for new fields |

### Modified Files
| # | File | Change |
|---|------|--------|
| 1 | [`src/backend/documents/models.py`](src/backend/documents/models.py) | Add `extracted_text`, `extraction_method`, `garbled_score` fields |
| 2 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) | Save extracted text + metadata after extraction; refactor `_is_persian_text_garbled` to expose ratio |
| 3 | [`src/backend/documents/views.py`](src/backend/documents/views.py) | Add `DocumentExtractedTextView` |
| 4 | [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | Add route for extracted-text endpoint |
| 5 | [`src/frontend/src/lib/api/documents.ts`](src/frontend/src/lib/api/documents.ts) | Add `getExtractedText()` and `getDocumentChunks()` + types |
| 6 | [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) | Add monitoring routes |
| 7 | [`src/frontend/src/components/layout/Sidebar.tsx`](src/frontend/src/components/layout/Sidebar.tsx) | Add Monitoring nav item with `Activity` icon |
| 8 | [`src/frontend/src/types/document.ts`](src/frontend/src/types/document.ts) | Add chunk-related TypeScript types |
| 9 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | Document new fields |
| 10 | [`docs/references/api-registry.md`](docs/references/api-registry.md) | Document new endpoint |
| 11 | [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Track progress |

---

## Implementation Order

1. **Backend model + migration** — Add 3 fields, run migration
2. **Backend save metadata** — Modify `extract_text_from_pdf` to persist text + method + garbled score
3. **Backend API endpoint** — Add `DocumentExtractedTextView` + URL route
4. **Frontend API layer** — Add `getExtractedText()` and `getDocumentChunks()` functions + types
5. **Frontend MonitoringPage** — Create the main page component with three-panel layout
6. **Frontend routing** — Add route in `App.tsx`
7. **Frontend sidebar** — Add nav item
8. **Reference docs** — Update `database-schema.md` and `api-registry.md`
9. **WIP context** — Update `wip-context.md`

---

## Notes

- This is a **developer tool** — no need for extensive error handling, loading states, or responsive design
- The page does NOT need to be pixel-perfect; functional utility is the priority
- Persian/RTL text should render correctly — use `direction: rtl` and appropriate CSS
- No tests are required for this feature (dev tool)
- The `extracted_text` field stores potentially large text (entire PDF content) — this is acceptable for a dev tool
- The `garbled_score` refactoring: `_is_persian_text_garbled()` currently returns `bool`. We need to either:
  - Create a separate function `_compute_garbled_ratio()` that returns the float ratio
  - Or refactor `_is_persian_text_garbled()` to return `tuple[bool, float]`
  - Recommendation: create `_compute_garbled_ratio(text) -> float` and have `_is_persian_text_garbled` call it
