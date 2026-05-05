# WIP Context — Epic 4: Persian Legal Text Optimization

## Status: ✅ COMPLETED (2026-05-05)

All 10 steps of the Epic 4 refactoring plan have been implemented and are ready for testing.

---

## What Was Completed

### Step 1: Dependencies
- Added `hazm>=0.10.0`, `pdfplumber>=0.11.0`, `pytesseract>=0.3.10` to `src/backend/requirements.txt`

### Step 2: Persian Text Normalization Service
- Created `src/backend/documents/services/persian_normalizer.py`
  - `PersianNormalizer` class with multi-stage normalization pipeline
  - Processing order (CRITICAL): strip_tatweel → clean_control_chars → normalize_arabic_chars → fix_half_spaces → final cleanup
  - Uses `hazm.Normalizer` for character normalization
  - Custom regex patterns for Persian compound words (می‌, نمی‌, خواه, verb suffixes)
  - Documented limitation: Hazm does NOT fix RTL character reversal from PyMuPDF
- Created `src/backend/documents/tests/test_persian_normalizer.py` with 6 test classes

### Step 3: Legal Structure Detector
- Created `src/backend/documents/services/legal_structure_detector.py`
  - `LegalSegment` dataclass with segment_type, segment_number, content, metadata, start_pos, end_pos
  - `LegalStructureDetector` class with `detect_structure()` and `has_legal_structure()` methods
  - Flexible regex patterns handling Persian (۰۱۲۳۴۵۶۷۸۹), Arabic (٠١٢٣٤٥٦٧٨٩), and English (0123456789) numerals
  - Tatweel stripping and whitespace normalization before regex matching
  - Metadata attachment (parent article for notes/clauses)
- Created `src/backend/documents/tests/test_legal_structure_detector.py` with 6 test classes

### Step 4: Refactored Chunking Service
- Rewrote `src/backend/documents/services/chunking_service.py`
  - Extended `ChunkResult` with `legal_type`, `legal_number`, `parent_article` fields
  - New `ClauseBoundary` dataclass for clause-aware overlap
  - `ChunkingService.chunk_text()` auto-detects legal structure and delegates to `_chunk_legal()` or `_chunk_sentence()`
  - `_chunk_legal()`: Groups segments by article, creates chunks at article boundaries, splits long articles at clause boundaries
  - `_split_long_article()`: Clause-boundary-aware overlap where overlap is measured in clauses, not characters
  - `_chunk_sentence()`: Preserved original sentence-boundary chunking as fallback
- Created `src/backend/documents/tests/test_chunking_service.py` with 5 test classes

### Step 5: Pipeline Integration
- Rewrote `src/backend/documents/tasks/document_processing.py`
  - `_is_persian_text_garbled()` — Quality heuristic checking if >30% of Persian chars are isolated
  - `_extract_with_pymupdf_rtl()` — RTL-aware extraction with TEXT_PRESERVE_LIGATURES | TEXT_PRESERVE_WHITESPACE flags
  - `_extract_with_pdfplumber()` — Fallback extraction using pdfplumber
  - `_extract_with_tesseract()` — OCR fallback for scanned Persian PDFs
  - Three-layer extraction strategy with auto-fallback in `extract_text_from_pdf()`
  - Persian normalization applied after extraction using `PersianNormalizer`
  - Updated `chunk_document()` to use settings for legal chunking configuration

### Step 6: Model Update
- Added `legal_context` property to `DocumentChunk` model in `src/backend/documents/models.py`
  - Returns formatted Persian string like `"قانون: قانون مجازات اسلامی | فصل: اول | ماده: 1"`
  - Computed from `metadata` JSONB field (no DB migration needed)

### Step 7: Search Service Update
- Added `"legal_context": chunk.legal_context` to search result dicts in `src/backend/documents/services/search_service.py`

### Step 8: RAG Service Update
- Updated `build_context()` in `src/backend/conversations/rag_service.py` to include legal context in source headers
  - Format: `[Source 1 | Pages 1-3 | قانون: ... | فصل: ... | ماده: ...]`

### Step 9: Configuration Settings
- Added 7 new settings to `src/backend/config/settings.py`:
  - `PERSIAN_NORMALIZATION_ENABLED` (default: True)
  - `LEGAL_CHUNKING_ENABLED` (default: True)
  - `LEGAL_MAX_CHUNK_SIZE` (default: 2000)
  - `LEGAL_CHUNK_OVERLAP_CLAUSES` (default: 1)
  - `EXTRACTION_BACKEND` (default: 'pymupdf')
  - `EXTRACTION_AUTO_FALLBACK` (default: True)
  - `EXTRACTION_GARBLED_THRESHOLD` (default: 0.3)
- Added corresponding env vars to `.env.example`

### Step 10: Reference Documentation
- Updated `docs/references/database-schema.md` — Documented `metadata` JSONB field usage for legal context
- Updated `docs/references/api-registry.md` — Added `legal_context` field to search response example and implementation notes
- Updated this file (`docs/active-task/wip-context.md`)

---

## Files Changed Summary

| File | Action |
|------|--------|
| `src/backend/requirements.txt` | Modified (added 3 deps) |
| `src/backend/documents/services/persian_normalizer.py` | **NEW** |
| `src/backend/documents/tests/test_persian_normalizer.py` | **NEW** |
| `src/backend/documents/services/legal_structure_detector.py` | **NEW** |
| `src/backend/documents/tests/test_legal_structure_detector.py` | **NEW** |
| `src/backend/documents/services/chunking_service.py` | Rewritten |
| `src/backend/documents/tests/test_chunking_service.py` | **NEW** |
| `src/backend/documents/tasks/document_processing.py` | Rewritten |
| `src/backend/documents/models.py` | Modified (added `legal_context` property) |
| `src/backend/documents/services/search_service.py` | Modified (added `legal_context` to results) |
| `src/backend/conversations/rag_service.py` | Modified (legal context in source headers) |
| `src/backend/config/settings.py` | Modified (added 7 settings) |
| `.env.example` | Modified (added env vars) |
| `docs/references/database-schema.md` | Modified (Epic 4 section) |
| `docs/references/api-registry.md` | Modified (legal_context in search response) |
| `docs/active-task/wip-context.md` | Modified (this file) |

---

## Next Steps / Verification

1. **Build & restart containers:** `docker-compose up --build`
2. **Run backend tests:** `docker-compose exec backend pytest`
3. **Upload a Persian legal PDF** and verify:
   - Text extraction works (check for garbled characters)
   - Chunks respect article boundaries
   - Search results include `legal_context` field
   - RAG responses include legal provenance in source citations
4. **Toggle settings** via `.env` to verify:
   - `PERSIAN_NORMALIZATION_ENABLED=False` — disables normalization
   - `LEGAL_CHUNKING_ENABLED=False` — falls back to sentence-boundary chunking
   - `EXTRACTION_BACKEND=pdfplumber` — uses pdfplumber as primary extractor
