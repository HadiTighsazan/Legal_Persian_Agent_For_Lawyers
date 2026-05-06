# WIP Context — Fix Persian PDF Text Extraction & Chunking Pipeline

## Status: ✅ COMPLETED (2026-05-06) — All 661 tests passing (2 pre-existing failures unrelated to this change)

All 7 changes from the action plan [`plans/plan-fix-persian-pdf-extraction-chunking.md`](plans/plan-fix-persian-pdf-extraction-chunking.md) have been implemented and verified.

---

## What Changed

### Problem Summary

Persian PDF text extraction had 4 issues:
1. **Shattered Persian words** (e.g., `"ق ا ن و ن"`) were not detected, so the fallback pipeline never triggered for this failure mode
2. **PyMuPDF flags** were missing `TEXT_PRESERVE_IMAGES` and `TEXT_DEHYPHENATE`, causing ligature/word-break artifacts
3. **pdfplumber fallback** lacked RTL reshaping (`arabic_reshaper` + `python-bidi`), producing visually reversed text
4. **Chunking** missed Persian sentence-ending punctuation (`؟`, `،`, `؛`) and had insufficient overlap (200 → 300)

### Changes Made

| # | File | Change | Description |
|---|------|--------|-------------|
| 1 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:115) | Added `_has_shattered_persian_words()` | New heuristic detects space-shattered Persian text (single-char token ratio > 0.4) |
| 2 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:176) | Integrated both heuristics | Combined `_is_persian_text_garbled()` OR `_has_shattered_persian_words()` via local `_is_garbled()` helper |
| 3 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:196) | Updated PyMuPDF flags | Added `TEXT_PRESERVE_IMAGES` and `TEXT_DEHYPHENATE` to extraction flags |
| 4 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:210) | Enhanced pdfplumber with RTL reshaping | Added `arabic_reshaper.reshape()` + `bidi.get_display()` with graceful `ImportError` fallback |
| 5 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:597) | Increased chunk overlap | Changed from 200 to 300 in `chunk_document()` |
| 6 | [`src/backend/requirements.txt`](src/backend/requirements.txt) | Added dependencies | `arabic_reshaper>=3.0.0` and `python-bidi>=0.4.2` |
| 7 | [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:764) | Added Persian sentence endings | `_SENTENCE_ENDINGS` now includes `؟` (U+061F), `،` (U+060C), `؛` (U+061B) |
| 8 | [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:785) | Updated `_find_split_point()` priority | Persian endings checked first, then standard endings, then paragraph breaks, then last space, then hard split |
| 9 | [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py:794) | Added `HasShatteredPersianWordsTests` | 13 test methods covering shattered detection, normal text, edge cases, custom threshold |
| 10 | [`src/backend/documents/tests/test_chunking_service.py`](src/backend/documents/tests/test_chunking_service.py:306) | Added `TestPersianSentenceEndings` | 5 test methods for Persian punctuation split points |
| 11 | [`src/backend/conftest.py`](src/backend/conftest.py) | Fixed Django bootstrap order | Moved `os.environ.setdefault` above module-level imports; converted imports to lazy inside fixtures |

### Test Results

- **661 tests passed** (full suite)
- **2 pre-existing failures** (unrelated — `test_default_top_k` in serializers and views, about `top_k` default value mismatch)
- **18 new tests added** (13 for shattered-word detection, 5 for Persian sentence endings)
- **0 regressions** from existing tests

### Reference Documentation Updates

- [`docs/references/database-schema.md`](docs/references/database-schema.md) — No changes needed (no schema modifications)
- [`docs/references/api-registry.md`](docs/references/api-registry.md) — No changes needed (no API endpoint modifications)

---

## Rollback Plan

If any change causes regression:

1. **Shattered-word heuristic**: Remove `_has_shattered_persian_words()` and revert `_is_garbled()` calls back to `_is_persian_text_garbled()` in [`document_processing.py`](src/backend/documents/tasks/document_processing.py)
2. **PyMuPDF flags**: Remove `TEXT_PRESERVE_IMAGES` and `TEXT_DEHYPHENATE` from the flags bitmask
3. **pdfplumber RTL reshaping**: Remove the `arabic_reshaper`/`bidi` import block and reshaping logic
4. **Chunk overlap**: Change back from 300 to 200
5. **Persian sentence endings**: Remove `"؟"`, `"،"`, `"؛"` from `_SENTENCE_ENDINGS` and revert `_find_split_point()` priority
6. **Dependencies**: Remove `arabic_reshaper` and `python-bidi` from `requirements.txt`
7. **Tests**: Revert `test_tasks.py` and `test_chunking_service.py` additions
8. **conftest.py**: Revert to module-level imports if lazy imports cause issues (though lazy imports are the correct pattern)
