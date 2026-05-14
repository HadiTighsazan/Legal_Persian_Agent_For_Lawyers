# WIP Context — Phase 4: Table Extraction with Dual Representation

## Status: ✅ COMPLETED — Phase 4 Fully Implemented and Tested

## Latest: Phase 4 — Table Extraction with Dual Representation (2026-05-14)

### Changes Made

#### 4.1 `ExtractedTable` Dataclass — [`table_extractor.py`](src/backend/documents/utils/table_extractor.py:39)

Created a `@dataclass` with fields:
- `page: int` — 1-based page number where the table was found
- `bbox: tuple[float, float, float, float]` — Bounding box (x0, y0, x1, y1) from pdfplumber
- `markdown: str` — GitHub-flavored Markdown representation (for display/LLM context)
- `semantic_text: str` — Key-value pair representation (for embedding)
- `raw_data: list[list[str | None]]` — Raw cell data from pdfplumber (default `field(default_factory=list)`)

#### 4.2 `_table_to_markdown()` — [`table_extractor.py`](src/backend/documents/utils/table_extractor.py:66)

Converts a `list[list[str | None]]` table to GitHub-flavored Markdown:
- First row becomes the header row
- Second row is a separator (`|---|---|`)
- Remaining rows become data rows
- `None` cells rendered as empty string `""`
- Empty cells rendered as empty string `""`

#### 4.3 `_table_to_semantic_text()` — [`table_extractor.py`](src/backend/documents/utils/table_extractor.py:123)

Converts a table to normalized key-value pairs for embedding:
- Uses the first row as headers (keys)
- Each subsequent row becomes a line of `"key1: value1 | key2: value2 | ..."`
- `None` cells rendered as empty string `""`
- Empty cells rendered as empty string `""`
- Empty tables return `""`
- Single-row tables (header only) return `""`

#### 4.4 `TableExtractor` Class — [`table_extractor.py`](src/backend/documents/utils/table_extractor.py:184)

Main extraction class with:
- `extract_tables(pdf_bytes: bytes) -> list[ExtractedTable]` — Extracts all tables from a PDF
- `_extract_tables_from_page(page, page_number: int) -> list[ExtractedTable]` — Extracts tables from a single page
- **Filters:** `min_rows=2`, `min_cols=2` to avoid false positives (single-row/column artifacts)
- **Graceful degradation:** If pdfplumber is not installed, logs a warning and returns empty list
- **Per-page error handling:** If `find_tables()` fails on a page, logs a warning and continues to next page

#### 4.5 Integration into `extract_text_from_pdf` — [`document_processing.py`](src/backend/documents/tasks/document_processing.py:1002)

Table extraction is performed during `extract_text_from_pdf`:
- Gated by `settings.TABLE_EXTRACTION_ENABLED` (default `True`)
- Runs after text extraction but before Persian normalization
- Extracted tables are stored on `Document.tables_data` as a list of dicts with keys: `page`, `bbox`, `markdown`, `semantic_text`
- If pdfplumber is unavailable or extraction fails, logs a warning and continues (non-blocking)
- `document.save(update_fields=[...])` updated to include `tables_data`

#### 4.6 Table-to-Chunk Attachment in `chunk_document` — [`document_processing.py`](src/backend/documents/tasks/document_processing.py:1298)

Tables are attached to chunks as metadata (not injected into content):
- Reads `document.tables_data` (list of dicts)
- `_get_tables_for_chunk(chunk_pages)` helper matches tables to chunks by page overlap
- Tables are stored in `chunk.metadata["tables"]` as a list of dicts with `page`, `markdown`, `semantic_text`
- If no tables overlap a chunk's pages, `metadata["tables"]` is an empty list `[]`
- This keeps `chunk.content` clean (no table text pollution in content)

#### 4.7 `_prepare_embedding_content()` — [`embedding_service.py`](src/backend/documents/services/embedding_service.py:47)

New function that prepares content for embedding:
- Takes a `DocumentChunk` object
- Returns `chunk.content` if no tables in metadata
- Appends `"\n\n" + "\n".join(table["semantic_text"])` if tables exist
- Skips tables with empty `semantic_text`
- Handles `None` metadata gracefully

Updated callers:
- `_process_chunk_batch()` — uses `_prepare_embedding_content(chunk)` instead of `chunk.content`
- `batch_embed_chunks()` — uses `_prepare_embedding_content(chunk)` instead of `chunk.content`

#### 4.8 Migration 0016 — Add `tables_data` Field — [`0016_add_tables_data_field.py`](src/backend/documents/migrations/0016_add_tables_data_field.py)

- Adds `tables_data` JSONField to `documents` table (default `list`, blank)
- No GIN index (JSONField is metadata-only, not queried directly)
- Dependencies: depends on migration `0015_document_hub_type_documentchunk_hub_type_and_more`

### Files Created/Modified

| File | Action | Description |
|------|--------|-------------|
| [`table_extractor.py`](src/backend/documents/utils/table_extractor.py) | **NEW** | Core utility: `ExtractedTable` dataclass, `_table_to_markdown()`, `_table_to_semantic_text()`, `TableExtractor` class |
| [`models.py`](src/backend/documents/models.py:113) | **MODIFIED** | Added `tables_data = JSONField(default=list, blank=True)` to Document model |
| [`0016_add_tables_data_field.py`](src/backend/documents/migrations/0016_add_tables_data_field.py) | **NEW** | Migration adding `tables_data` field |
| [`document_processing.py`](src/backend/documents/tasks/document_processing.py:1002) | **MODIFIED** | Table extraction in `extract_text_from_pdf` + table-to-chunk attachment in `chunk_document` |
| [`embedding_service.py`](src/backend/documents/services/embedding_service.py:47) | **MODIFIED** | Added `_prepare_embedding_content()` and updated `_process_chunk_batch()` / `batch_embed_chunks()` |
| [`test_table_extractor.py`](src/backend/documents/tests/test_table_extractor.py) | **NEW** | 27 tests covering all components |

### Test Results

```
100 passed in 31.71s
```

All 100 tests pass, including 27 new tests for Phase 4 features:
- **`TableToMarkdownTest`** (5 tests): empty table, single-row, basic, None cells, empty cells
- **`TableToSemanticTextTest`** (7 tests): empty, single-row, basic key-value, multiple rows, None cells, empty header, Persian legal table
- **`ExtractedTableTest`** (2 tests): dataclass creation, default raw_data
- **`TableExtractorTest`** (7 tests): pdfplumber not installed, import error, PDF open failure, min_rows filter, min_cols filter, successful extraction, multiple pages, find_tables failure on page
- **`PrepareEmbeddingContentTest`** (6 tests): no tables, with tables, multiple tables, empty semantic text skipped, metadata is None

### Key Design Decisions

1. **Dual representation (Markdown + Semantic text):** Markdown is for display/LLM context (human-readable). Semantic text (key-value pairs) is for embedding (machine-optimized). This prevents embedding pollution from Markdown formatting characters.

2. **Tables stored as chunk metadata, not injected into content:** Tables are attached to `chunk.metadata["tables"]` rather than appended to `chunk.content`. This keeps the content clean for display and search. The `_prepare_embedding_content()` function appends semantic text only at embedding time.

3. **Page-aware table-to-chunk mapping:** Tables are matched to chunks based on page overlap (`page_min <= table.page <= page_max`). This ensures each chunk gets only the tables that appear on its pages.

4. **Extraction during `extract_text_from_pdf`, not `chunk_document`:** Table extraction happens during the first task in the Celery chain because it requires access to the raw PDF bytes (which are available at extraction time). The extracted tables are stored on the Document model and read during chunking.

5. **Configurable via settings:** Gated by `TABLE_EXTRACTION_ENABLED` setting (default `True`), allowing easy disable if issues are discovered.

6. **Graceful degradation:** If pdfplumber is not installed or table extraction fails, the pipeline continues without tables (non-blocking). Per-page errors are caught and logged individually.

7. **Minimum table size filter:** `min_rows=2`, `min_cols=2` to avoid false positives from single-row/column artifacts that pdfplumber sometimes detects.

### Next Steps
Phase 5+ as defined in the remediation plan (not yet started).

### Reference Docs
- [`table_extractor.py`](src/backend/documents/utils/table_extractor.py) — Core table extraction utility
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py) — Table extraction integration in `extract_text_from_pdf` and `chunk_document`
- [`embedding_service.py`](src/backend/documents/services/embedding_service.py) — `_prepare_embedding_content()` for embedding with table context
- [`test_table_extractor.py`](src/backend/documents/tests/test_table_extractor.py) — 27 tests for Phase 4 features
- [`database-schema.md`](docs/references/database-schema.md) — Updated with `tables_data` field and migration 0016
