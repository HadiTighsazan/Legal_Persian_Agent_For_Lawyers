# WIP Context — Phase 2: Garbled Detection Enhancement

## Status: ✅ COMPLETED — Phase 2 (2.1 + 2.2) Fully Implemented and Tested

## Latest: Phase 2 — Persian Language Confidence Score (2026-05-14)

### Changes Made

#### 2.1 Persian Language Confidence Score — STRATEGIC (`document_processing.py`)

**Problem:** Current heuristics (`_compute_garbled_ratio`, `_has_shattered_persian_words`) miss RTL-reversed connected text like `رپونده` and `خوااهن`. The previously proposed bigram set approach was too fragile.

**Solution:** Replaced simple bigram checks with a **multi-signal Persian Language Confidence Score** that combines four signals:

1. **Stopword ratio** (weight 0.50) — Most reliable signal. Valid Persian text has frequent stopwords like `از`, `به`, `در`, `و`, `که`. RTL-reversed text loses these stopwords.
2. **Bigram plausibility** (weight 0.10) — Statistical bigram frequency. NOTE: Not reliable for RTL reversal (reversing preserves bigrams), but helps detect random corruption.
3. **RTL consistency** (weight 0.25) — Measures if Persian characters appear in contiguous runs vs isolated. Detects shattered text.
4. **Character entropy** (weight 0.15, inverted) — Garbled text often has higher entropy.

**Key insight confirmed:** The stopword ratio signal is the most powerful for RTL-reversed text detection. In reversed text like `رپونده خوااهن`, stopwords like `از`, `به`, `در` become unrecognizable, driving the quality score below threshold even when other signals are high.

**Files modified:**
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:58) — Added `_PERSIAN_STOPWORDS`, `_LEGAL_STOPWORDS`, `_ALL_PERSIAN_STOPWORDS` sets (lines 58-83)
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:85) — Added comprehensive `_VALID_PERSIAN_BIGRAMS` set (~400 entries covering all Arabic/Persian letter combinations)
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:104) — Added `_compute_stopword_ratio()` function
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:127) — Added `_compute_bigram_plausibility()` function
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:166) — Added `_compute_rtl_consistency()` function
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:220) — Added `_compute_character_entropy()` function
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:305) — Added `_compute_persian_quality_score()` function (combines all 4 signals with weights [0.50, 0.10, 0.25, 0.15])
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:353) — Updated `_compute_garbled_ratio()` with deprecation notice pointing to new quality score
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:395) — Updated `_is_persian_text_garbled()` to use quality score by default (with `use_quality_score=True` parameter, fallback to legacy mode)
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:880) — Updated `_is_garbled` helper in `extract_text_from_pdf` to use `EXTRACTION_GARBLED_THRESHOLD_PERSIAN_LEGAL` when configured
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:950) — Updated `garbled_score` computation to also compute and log `quality_score`

#### 2.2 Lower Garbled Threshold for Persian Legal Text

**Problem:** Current threshold of 0.3 is too permissive for the existing heuristic.

**Solution:** Added `EXTRACTION_GARBLED_THRESHOLD_PERSIAN_LEGAL` setting with a stricter default of 0.15 for documents detected as Persian legal text.

**Files modified:**
- [`settings.py`](src/backend/config/settings.py:306) — Added `EXTRACTION_GARBLED_THRESHOLD_PERSIAN_LEGAL` setting (default 0.15)

### Test Results
```
82 passed in 44.98s
```
All 82 tests pass, including all 50 new tests for Phase 2 features (7 test classes covering stopword ratio, bigram plausibility, RTL consistency, character entropy, quality score, legacy garbled ratio, and threshold detection).

### Key Design Decisions

1. **Stopword weight increased to 0.50** — During testing, we discovered that bigram plausibility is NOT a reliable signal for RTL-reversed text because reversing a word preserves its bigrams (e.g., `قانون` → `نوناق` has bigrams `نو`, `ون`, `نا`, `اق` which are all valid Persian bigrams). The stopword ratio is the only signal that reliably detects RTL reversal.

2. **Bigram weight reduced to 0.10** — Kept as a minor signal for detecting random character corruption (not RTL reversal).

3. **Comprehensive bigram set** — Expanded from ~50 entries to ~400 entries covering all Arabic/Persian letter combinations to ensure valid Persian text scores high on bigram plausibility.

4. **Backward compatibility** — `_compute_garbled_ratio()` is preserved with a deprecation notice. `_is_persian_text_garbled()` accepts `use_quality_score=False` to fall back to legacy behavior. The `garbled_score` field on the Document model still stores the legacy ratio for dashboard compatibility, while `quality_score` is logged.

5. **Threshold semantics** — Quality score < threshold → garbled (lower quality = more garbled). The Persian legal threshold of 0.15 is stricter (requires higher quality to pass) than the general threshold of 0.3.

### Next Steps
Phase 3+ as defined in the remediation plan (not yet started).

### Reference Docs
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py) — Updated with multi-signal quality score system
- [`settings.py`](src/backend/config/settings.py) — Added `EXTRACTION_GARBLED_THRESHOLD_PERSIAN_LEGAL`
- [`test_tasks.py`](src/backend/documents/tests/test_tasks.py) — 50 new tests for Phase 2 features
