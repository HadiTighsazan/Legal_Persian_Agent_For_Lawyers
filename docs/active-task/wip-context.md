# WIP Context — Chunking Pipeline Refactor (OCR-Aware Hybrid)

## Status: ✅ COMPLETED — All 8 Phases Implemented

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
