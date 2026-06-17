# WIP Context — Phase 1 Extraction Pipeline Refactoring

## What Was Just Completed

### Phase 1 Refactoring: Extraction Pipeline Overhaul

Replaced the heavy, multi-branch Persian PDF extraction pipeline with a lightweight, page-level approach using Qwen3 VL via OpenRouter for garbled CMap fonts.

**Core Problem Solved:**
Persian PDFs with broken /ToUnicode CMap tables produced garbled text from PyMuPDF. The old 3-layer fallback chain (pdfplumber → Tesseract → EasyOCR) was heavy, complex, and unreliable. The new approach renders only garbled pages to images via PyMuPDF's native `get_pixmap()` and sends them to Qwen3 VL for vision-based text extraction — elegantly solving the CMap problem.

### Files Created

1. [`src/backend/documents/services/vision_extraction_service.py`](src/backend/documents/services/vision_extraction_service.py) — **NEW**: Page-level VLM OCR service using OpenRouter + Qwen3 VL. Includes:
   - `extract_page()` — Single page extraction with verification
   - `extract_document()` — Multi-page batch extraction
   - Post-extraction verification (article sequence, digit consistency, repetition detection)
   - Cross-page article number coherence checking
   - Configurable model, DPI, retries

### Files Modified

2. [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py) — **Removed hazm dependency**. All normalization now uses pure Python:
   - Character translation table (Arabic → Persian) replaces hazm's `Normalizer.normalize()`
   - Arabic diacritic removal via regex replaces hazm's `remove_diacritics`
   - Extended half-space (ZWNJ) regex patterns replace hazm's built-in rules

3. [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) — **Major refactoring**:
   - Added 5th quality signal: `_compute_lexicon_validity()` — checks what % of tokens exist in Persian/legal lexicon
   - Updated `_compute_persian_quality_score()` weights: `[0.30, 0.25, 0.15, 0.20, 0.10]`
   - Replaced whole-document extraction with per-page loop
   - Removed `_extract_with_pdfplumber()` function
   - Removed `_extract_with_tesseract()` function
   - Removed EasyOCR / scanned PDF detection block
   - Removed `is_scanned_pdf` import
   - Added `VisionExtractionService` integration for garbled pages
   - Added `vision_verification` metadata tracking

4. [`src/backend/documents/utils/table_extractor.py`](src/backend/documents/utils/table_extractor.py) — **Replaced pdfplumber with PyMuPDF**:
   - `fitz.open()` + `page.find_tables()` replaces `pdfplumber.open()` + `page.find_tables()`
   - Output format (ExtractedTable dataclass) unchanged

5. [`src/backend/config/settings.py`](src/backend/config/settings.py) — **Cleaned up settings**:
   - Removed: `EXTRACTION_BACKEND`, `EXTRACTION_AUTO_FALLBACK`, `EXTRACTION_GARBLED_THRESHOLD_PERSIAN_LEGAL`, `OCR_EASYOCR_ENABLED`, `OCR_EASYOCR_USE_GPU`, `OCR_CONFIDENCE_THRESHOLD`, `OCR_CONTRAST_ENABLED`, `OCR_DESKEW_ENABLED`
   - Added: `VISION_EXTRACTION_ENABLED`, `VISION_EXTRACTION_MODEL`, `VISION_EXTRACTION_DPI`, `VISION_EXTRACTION_MAX_RETRIES`

6. [`docker/backend/Dockerfile`](docker/backend/Dockerfile) — **Removed system dependencies**:
   - `libgl1-mesa-glx`, `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender-dev`, `libgomp1`, `poppler-utils`

7. [`src/backend/requirements.txt`](src/backend/requirements.txt) — **Removed 8 packages**:
   - `easyocr`, `opencv-python-headless`, `pdf2image`, `pytesseract`, `pdfplumber`, `arabic_reshaper`, `python-bidi`, `hazm`

8. [`docs/references/database-schema.md`](docs/references/database-schema.md) — Updated extraction_method docs, dependency notes

### Files Deleted

9. [`src/backend/documents/services/ocr_service.py`](src/backend/documents/services/ocr_service.py) — EasyOCR + Tesseract replaced by VisionExtractionService
10. [`src/backend/documents/utils/scanned_pdf_detector.py`](src/backend/documents/utils/scanned_pdf_detector.py) — Replaced by inline per-page check in extract_text_from_pdf
11. [`src/backend/documents/tests/test_ocr_service.py`](src/backend/documents/tests/test_ocr_service.py) — Obsolete
12. [`src/backend/documents/tests/test_scanned_pdf_detector.py`](src/backend/documents/tests/test_scanned_pdf_detector.py) — Obsolete

### Test Files Updated

13. [`src/backend/documents/tests/test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py) — Updated for hazm removal:
    - `test_arabic_teh_marbuta`: Updated assertion — our custom implementation converts ة → ه (hazm preserved it)
    - `test_hazm_does_not_fix_reversal`: Renamed to `test_normalizer_does_not_fix_reversal`, docstring updated

### Key Design Decisions

- **Page-level extraction**: Each page is extracted independently, checked for quality (5 signals), and only garbled pages are sent to VLM. This prevents both false positives (sending entire doc for a few bad pages) and false negatives (missing garbled pages).
- **5-signal quality score**: Stopwords (0.30) + Lexicon validity (0.25, NEW) + Bigrams (0.15) + RTL consistency (0.20) + Entropy (0.10). The lexicon validity signal is the most reliable for CMap corruption.
- **VLM fidelity safeguards**: Strict Persian prompt, post-extraction verification (article sequence, digit consistency), confidence flagging for unverified pages.
- **Weight reduction**: ~8 Python packages + 7 system packages removed. Docker image estimated to shrink from ~1.5GB to ~300MB.

### Current State

- **All Phase 1 extraction pipeline changes complete**
- **Phase 2 (Global RAG) and Phase 3 (Strategist) untouched** — all conversation services, providers, search logic unchanged
- **API endpoints unchanged** — same interface, different internals
- Database schema unchanged (extraction_method values may now be `pymupdf` or `pymupdf+vision(N/M pages)`)

## Next Steps

1. Build the Docker image: `docker-compose build backend`
2. Run tests: `docker-compose exec backend pytest`
3. Verify with real Persian PDFs that have broken CMap tables

## Reference Doc Changes

- [`docs/references/database-schema.md`](docs/references/database-schema.md):
  - Updated `extraction_method` column description (new values: `pymupdf` or `pymupdf+vision(N/M pages)`)
  - Updated Epic 4 dependencies section (hazm/pdfplumber/pytesseract removed)
