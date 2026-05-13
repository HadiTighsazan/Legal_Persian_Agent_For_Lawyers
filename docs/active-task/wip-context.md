# WIP Context — Chunking Pipeline Refactor (OCR-Aware Hybrid)

## Status: ✅ COMPLETED — All 8 Phases + Post-Refactor Test Fixes

## Latest: Debug Plan — 14 Test Failures Fixed (2026-05-13)

All 14 post-refactor test failures have been resolved. See [`plans/plan-debug-test-failures.md`](plans/plan-debug-test-failures.md) for the full root cause analysis.

### Changes Made

#### Phase 1: Test File Fixes (11 changes)

**`test_scanned_pdf_detector.py`** (3 fixes):
1. [`_create_mixed_pdf`](src/backend/documents/tests/test_scanned_pdf_detector.py:85) — Increased page 1 text to exceed the 50-char `_TYPED_TEXT_THRESHOLD` (was 38 chars, now ~100 chars)
2. [`_create_empty_pdf` → `_create_blank_pdf`](src/backend/documents/tests/test_scanned_pdf_detector.py:118) — PyMuPDF v24+ rejects 0-page saves; replaced with 1-page blank PDF (no text). Test expectation `is_scanned_pdf(pdf_path) is True` remains correct.
3. [`test_invalid_path_raises_file_not_found`](src/backend/documents/tests/test_scanned_pdf_detector.py:188) — Changed expected exception from Python `FileNotFoundError` to `fitz.FileNotFoundError`

**`test_ocr_service.py`** (7 fixes):
4. [`test_tesseract_extraction`](src/backend/documents/tests/test_ocr_service.py:295) — Changed patch target from `"documents.services.ocr_service.pytesseract"` to `"pytesseract.image_to_data"`
5. [`test_tesseract_not_available`](src/backend/documents/tests/test_ocr_service.py:322) — Changed patch target from `"documents.services.ocr_service.pytesseract.get_tesseract_version"` to `"pytesseract.get_tesseract_version"`
6-9. [`test_extract_text_*` (4 tests)](src/backend/documents/tests/test_ocr_service.py:341-427) — Changed `@patch("documents.services.ocr_service.convert_from_bytes")` to `@patch("pdf2image.convert_from_bytes")`
10. [`test_tesseract_fallback_triggered`](src/backend/documents/tests/test_ocr_service.py:427) — Added `_check_tesseract` mock + `_tesseract_available = True` since Tesseract is not installed in the container

**`test_anchor_chunking_service.py`** (2 fixes):
11. [`test_single_anchor`](src/backend/documents/tests/test_anchor_chunking_service.py:243) — Changed assertion from `"رأی دادگاه"` to `"رای دادگاه"` (normalized form)
12. [`test_anchor_content_preserved`](src/backend/documents/tests/test_anchor_chunking_service.py:273) — Same normalized form fix

#### Phase 2: Source Code Fixes (3 changes in `anchor_chunking_service.py`)

13. [`_resolve_pages`](src/backend/documents/services/anchor_chunking_service.py:429) — Removed `if not pages:` guard; now **always adds `active_page`** to the pages set. This ensures ranges that start *after* a page marker but before the next one correctly include the containing page.

14. [`_extract_metadata_and_clean`](src/backend/documents/services/anchor_chunking_service.py:373) — New method that extracts metadata AND **removes metadata lines from text** using `str.splitlines` line-by-line checking. The old `_extract_metadata` only copied metadata to a dict but never removed it from text, causing metadata values to appear in BOTH `chunk.metadata` AND `chunk.content`. The `page_map` is now recomputed from the cleaned text since positions shift after metadata removal.

15. [`chunk_text` intro detection](src/backend/documents/services/anchor_chunking_service.py:253) — Before creating an intro chunk with `section_title = "مقدمه"`, the code now strips `[PAGE N]` markers from the intro text. If only page markers remain (no real content), no intro chunk is created. This prevents false intro sections when an anchor starts immediately after a page marker.

### Test Results
```
68 passed in 1.76s
```
All 68 tests across the 3 test files pass.

## Summary

Replaced the legacy dual-algorithm chunking system (`ChunkingService` + `LegalStructureDetector`) with a hybrid OCR-aware pipeline. The new system detects whether a PDF is scanned (image-based) or typed (selectable text), routes accordingly, and uses text anchor segmentation (لنگرهای متنی) for Persian legal document structure.

### Architecture Overview

```
PDF Upload
    │
    ▼
extract_text_from_pdf()
    │
    ├── is_scanned_pdf() == True ──► OcrService (EasyOCR → Tesseract fallback)
    │                                   │
    │                                   ▼
    │                              Layout-aware assembly
    │                              (CLAHE contrast + deskew + column detection)
    │                                   │
    │                                   ▼
    │                              Text with [PAGE N] markers
    │
    └── is_scanned_pdf() == False ──► PyMuPDF extraction (existing)
                                        │
                                        ▼
                                   Text with [PAGE N] markers
                                        │
                                        ▼
                              chunk_document()
                                   │
                                   ▼
                           AnchorChunkingService
                           (text anchor segmentation)
                                   │
                                   ▼
                           AnchorChunk[]
                           (content, pages, metadata, section_title)
                                   │
                                   ▼
                           DocumentChunk model
                           (page_start, page_end, metadata)
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **EasyOCR over PaddleOCR** | Better Persian/Farsi accuracy; native Persian support |
| **Tesseract fallback** | `--psm 6 --oem 3` config for robust OCR when EasyOCR fails |
| **CLAHE contrast + deskew** | OpenCV preprocessing significantly improves OCR quality on scanned legal docs |
| **Layout-aware assembly** | Column detection (x-span > 40% page width) + adaptive paragraph grouping (median line height × 1.5) |
| **Conservative scanned PDF detection** | If ANY page has >50 chars selectable text, treat as typed (avoid false positives) |
| **Text anchor segmentation** | Regex-based structural splitting using Persian legal markers (رأی دادگاه, گردشکار, ختم دادرسی, etc.) |
| **Token-based overlap splitting** | tiktoken (cl100k_base) instead of character-based splitting for accurate token budgets |
| **Metadata separation** | Metadata stored in `metadata` dict, NOT injected into `content` — prevents embedding pollution |
| **Page-aware chunks** | `pages: List[int]` tracks which pages each chunk spans for accurate citation |

---

## Changes Made

### Files Created (6 new files)

1. [`src/backend/documents/utils/scanned_pdf_detector.py`](src/backend/documents/utils/scanned_pdf_detector.py) — Utility to detect if PDF is scanned (image-based) or typed (selectable text). Uses PyMuPDF to sample each page; if ANY page has >50 chars selectable text, returns `False` (typed). Conservative approach: empty PDFs return `True` (scanned).

2. [`src/backend/documents/tests/test_scanned_pdf_detector.py`](src/backend/documents/tests/test_scanned_pdf_detector.py) — 8 test cases: typed PDF, scanned PDF, mixed PDF, empty PDF, invalid path, invalid PDF, single-page typed, single-page scanned.

3. [`src/backend/documents/services/ocr_service.py`](src/backend/documents/services/ocr_service.py) — `OcrService` class with EasyOCR primary + Tesseract fallback. Features:
   - `TextSegment` dataclass: text, page, bbox, confidence
   - OpenCV preprocessing: CLAHE contrast enhancement + deskew correction
   - Layout-aware assembly: column detection, adaptive paragraph grouping
   - Confidence filtering: skip results with confidence < 0.5
   - Page marker injection: `[PAGE N]` markers for downstream chunking

4. [`src/backend/documents/tests/test_ocr_service.py`](src/backend/documents/tests/test_ocr_service.py) — Tests for `TextSegment` dataclass, `OcrService` init, layout assembly, preprocessing, EasyOCR extraction (mocked), Tesseract fallback (mocked), full extraction pipeline (mocked).

5. [`src/backend/documents/services/anchor_chunking_service.py`](src/backend/documents/services/anchor_chunking_service.py) — `AnchorChunkingService` class replacing both `ChunkingService` and `LegalStructureDetector`. Features:
   - `AnchorChunk` dataclass: content, pages, char_count, token_count, metadata, section_title
   - Persian normalization: Arabic Yeh→Persian Yeh, Kaf→Kaf, Alef variants→Alef, diacritic removal, whitespace collapse
   - Metadata extraction patterns: case_number, date, plaintiff, defendant, branch
   - Text anchors: رأی دادگاه, رای دادگاه, در خصوص دعوی, گردشکار, ختم دادرسی, نظریه مشورتی, بسمه تعالی, ماده \d+, فصل \d+
   - Token-based overlap splitting via tiktoken (cl100k_base)
   - Page-aware chunking via `[PAGE N]` marker parsing

6. [`src/backend/documents/tests/test_anchor_chunking_service.py`](src/backend/documents/tests/test_anchor_chunking_service.py) — 20+ test methods across 7 test classes covering: Persian normalization, metadata extraction, page tracking, token overlap split, anchor segmentation, metadata separation, page-aware chunking, edge cases.

### Files Modified (3 existing files)

7. [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) — Major modifications:
   - **Imports**: Replaced `ChunkingService` with `AnchorChunkingService`; added `is_scanned_pdf` import; added `import os` and `import tempfile`
   - **`extract_text_from_pdf()`**: Added scanned PDF detection at the beginning of extraction strategy. If `OCR_EASYOCR_ENABLED` is True and PDF is scanned, routes to EasyOCR pipeline with layout-aware assembly. Falls back to standard PyMuPDF chain if EasyOCR fails.
   - **`chunk_document()`**: Replaced `ChunkingService` with `AnchorChunkingService`. Uses `ANCHOR_CHUNK_TOKENS` and `ANCHOR_OVERLAP_TOKENS` settings. Maps `AnchorChunk.pages` (List[int]) to `page_start` (min) and `page_end` (max) for `DocumentChunk` model compatibility.

8. [`src/backend/config/settings.py`](src/backend/config/settings.py) — Added at end of file:
   ```python
   # Anchor chunking settings
   ANCHOR_CHUNKING_ENABLED = True
   ANCHOR_CHUNK_TOKENS = 400
   ANCHOR_OVERLAP_TOKENS = 50

   # OCR settings (EasyOCR + Tesseract)
   OCR_EASYOCR_ENABLED = True
   OCR_EASYOCR_USE_GPU = False
   OCR_CONFIDENCE_THRESHOLD = 0.5
   OCR_CONTRAST_ENABLED = True
   OCR_DESKEW_ENABLED = True
   ```

9. [`src/backend/requirements.txt`](src/backend/requirements.txt) — Added:
   - `easyocr>=1.7.0`
   - `opencv-python-headless>=4.8.0`
   - `pdf2image>=1.16.0`

10. [`docker/backend/Dockerfile`](docker/backend/Dockerfile) — Added system dependencies for EasyOCR/OpenCV:
    - `libgl1-mesa-glx`, `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender-dev`, `libgomp1`, `poppler-utils`

### Files Deleted (4 old files)

11. `src/backend/documents/services/chunking_service.py` — Replaced by `AnchorChunkingService`
12. `src/backend/documents/services/legal_structure_detector.py` — Replaced by `AnchorChunkingService`
13. `src/backend/documents/tests/test_chunking_service.py` — Replaced by `test_anchor_chunking_service.py`
14. `src/backend/documents/tests/test_legal_structure_detector.py` — Replaced by `test_anchor_chunking_service.py`

---

## Reference Documentation Updates Required

### [`docs/references/database-schema.md`](docs/references/database-schema.md)
- No schema changes — `DocumentChunk` model unchanged (still uses `page_start`, `page_end`, `metadata` JSONB)
- The new `AnchorChunk.pages: List[int]` is mapped to `page_start=min(pages)` and `page_end=max(pages)` at the task layer

### [`docs/references/api-registry.md`](docs/references/api-registry.md)
- No API endpoint changes — all changes are internal to Celery tasks and services

---

## How to Rebuild & Test

### 1. Rebuild Docker images (to install new dependencies)

```bash
docker-compose down
docker-compose build --no-cache backend
docker-compose up -d
```

### 2. Run the new tests

```bash
docker-compose exec backend pytest documents/tests/test_scanned_pdf_detector.py -v
docker-compose exec backend pytest documents/tests/test_ocr_service.py -v
docker-compose exec backend pytest documents/tests/test_anchor_chunking_service.py -v
```

### 3. Run full test suite to verify no regressions

```bash
docker-compose exec backend pytest
```

---

## Next Steps (Future Work)

- [ ] Tune `ANCHOR_CHUNK_TOKENS` (currently 400) based on retrieval quality metrics
- [ ] Tune `OCR_CONFIDENCE_THRESHOLD` (currently 0.5) based on real scanned PDF samples
- [ ] Add GPU support for EasyOCR (`OCR_EASYOCR_USE_GPU = True`) if running on CUDA-capable hardware
- [ ] Consider adding `--psm` config option for Tesseract fallback in settings
