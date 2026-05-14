# WIP Context — Phase 1: Persian Normalizer Enhancement

## Status: ✅ COMPLETED — Phase 1 (1.1 + 1.2) Fully Implemented and Tested

## Latest: Phase 1 — Persian Normalizer Enhancement (2026-05-14)

### Changes Made

#### 1.1 Ligature-Reversal Dictionary — TACTICAL (`persian_normalizer.py`)

**Problem:** No post-NFKC correction for common `لا` reversal errors in Persian PDF extraction.

**Solution:** Added `_LIGATURE_FIXES` dictionary (19 entries) mapping known garbled patterns to correct forms, and a new `fix_ligature_reversals()` method.

**Files modified:**
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:99) — Added `_LIGATURE_FIXES` dict (lines 99-132)
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:265) — Added `fix_ligature_reversals()` method (lines 265-280)
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:200) — Updated `normalize()` pipeline to call `fix_ligature_reversals()` as Stage 1 (after NFKC, before Tatweel)

**Pipeline position:** Stage 1 — after NFKC normalization, before Tatweel stripping. This catches reversal patterns after NFKC decomposes ligatures but before further processing.

#### 1.2 Date Repair Logic — EXPANDED (`persian_normalizer.py`)

**Problem:** Dates like `1376/01/15` split across lines during PDF extraction.

**Solution:** Added `_DATE_BROKEN_RE` comprehensive regex and `repair_broken_dates()` method.

**Files modified:**
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:134) — Added `_DATE_BROKEN_RE` regex (lines 134-152)
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:282) — Added `repair_broken_dates()` method (lines 282-317)
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:228) — Updated `normalize()` pipeline to call `repair_broken_dates()` as Stage 6 (after Hazm, before final cleanup)

**Pipeline position:** Stage 6 — after `fix_half_spaces` (Hazm), before `_final_cleanup`. This is critical because Hazm adds spaces around `/` punctuation, which would break the regex if it ran earlier. The regex allows optional whitespace (`\s*`) around all separators to handle Hazm's space insertion.

**Bug fix during implementation:** The regex was initially placed between NFKC and Tatweel (as specified in the plan), but Hazm's normalization adds spaces around `/` (e.g., `1376/01/15` → `1376 / 01 / 15`), which broke the date after repair. Moved to after Hazm and made the regex whitespace-tolerant.

#### Test Files Modified
- [`test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py:425) — Added `TestFixLigatureReversals` class (20 tests)
- [`test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py:537) — Added `TestRepairBrokenDates` class (14 tests)

### Test Results
```
87 passed in 83.57s
```
All 87 tests pass, including all 34 new tests for ligature fixes and date repair.

### Key Design Decisions

1. **Ligature fixes use simple `str.replace()`** — No regex needed since these are exact word-level mappings. Applied as a single pass over the text.

2. **Date regex captures each component separately** — Instead of `(\d{1,2}/\d{1,2})` as a single group, we use `(\d{1,2})\s*/\s*(\d{1,2})` as two groups to allow whitespace around the inner separator (needed because Hazm adds spaces).

3. **Date repair runs after Hazm** — Hazm's `normalize()` adds spaces around punctuation. Running date repair after Hazm ensures the regex sees the final text with all Hazm-induced whitespace, and the `\s*` patterns in the regex handle it correctly.

### Next Steps
Phase 2+ as defined in the remediation plan (not yet started).

### Reference Docs
- [`persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py) — Updated with ligature fixes and date repair
- [`test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py) — 34 new tests for Phase 1 features
