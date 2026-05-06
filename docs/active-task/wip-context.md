# WIP Context — Persian Keyword Search Fix (Arabic Presentation Forms)

## Status: ✅ COMPLETED (2026-05-06) — All 372 tests passing

The Persian Keyword Search Fix has been fully implemented. See [`plans/plan-persian-keyword-search-fix.md`](plans/plan-persian-keyword-search-fix.md) for the full root cause analysis and rationale.

---

## Root Cause Summary

The user reported that Persian keyword search fails to find obvious matches (e.g., `"تفاوت بین عقد جایز و عقد لازم چیست؟"` returns zero results). Even Ctrl+F in the PDF viewer couldn't find `"لازم"`.

**Primary cause:** PDF extractors (PyMuPDF, pdfplumber) preserve **Arabic Presentation Forms-B** (U+FE70–U+FEFF) — positional glyph variants — instead of converting them to standard Unicode codepoints. For example, `"لازم"` might be stored as:
- `ل` (U+FEDF — Lam initial form) instead of standard `ل` (U+0644)
- `ا` (U+FE8D — Alef isolated form) instead of standard `ا` (U+0627)
- `ز` (U+FEAF — Zain isolated form) instead of standard `ز` (U+0632)
- `م` (U+FEE1 — Meem isolated form) instead of standard `م` (U+0645)

These presentation forms look identical on screen but have completely different byte sequences, causing both Ctrl+F and PostgreSQL FTS to fail.

**Secondary defense:** Added trigram fallback in `keyword_search()` so that when FTS returns zero results, `pg_trgm` similarity search can still find matches (e.g., for OCR typos or Persian digit normalization).

---

## Changes Made

### 1. [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py)

**Added `unicodedata` import** (line 26).

**Added `_nfkc_normalize()` static method** — Applies `unicodedata.normalize("NFKC", text)` to convert Arabic Presentation Forms-B to standard Unicode codepoints.

**Updated `normalize()` pipeline** — Added NFKC normalization as Stage 0 (before Tatweel stripping), since NFKC may affect how certain characters are represented.

**Updated `normalize_for_fts()`** — Added `unicodedata.normalize("NFKC", text)` as Step 0 (before Arabic→Persian char conversion). This ensures:
- `ل` (U+FEDF — Lam initial form) → `ل` (U+0644 — standard Lam)
- `لا` (U+FEFB — Lam-Alef ligature) → `لا` (U+0644 U+0627 — two standard chars)
- All ~70 Arabic Presentation Forms-B → standard forms

Why NFKC and not NFC or NFKD:
- **NFC** (Canonical Composition) does NOT handle presentation forms
- **NFKD** (Compatibility Decomposition) decomposes them but leaves multi-codepoint sequences
- **NFKC** (Compatibility Composition) decomposes then recomposes, giving standard single-codepoint forms

### 2. [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py)

**Updated `keyword_search()` signature** — Added `enable_trigram_fallback: bool = True` parameter.

**Added trigram fallback logic** — When FTS returns zero results and `enable_trigram_fallback=True`, automatically falls back to `trigram_search()` with `min_similarity=0.1` (lower threshold for fallback). This catches cases where OCR typos or digit normalization issues prevent exact FTS matching.

### 3. [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py)

**Added `unicodedata` import** (line 33).

**Added NFKC normalization** to user query preprocessing (after Arabic→Persian char translation). This is defense-in-depth: even if the user copies text directly from a PDF that uses presentation forms, the query will be normalized before being sent to the LLM or used in FTS.

### 4. [`src/backend/documents/migrations/0011_normalize_presentation_forms.py`](src/backend/documents/migrations/0011_normalize_presentation_forms.py) — **NEW**

Re-normalizes all existing `DocumentChunk` content with the updated `normalize_for_fts()` (which now includes NFKC normalization). Processes in batches of 500 (same pattern as migration 0009). Each save triggers the `trg_chunk_search_vector` trigger to regenerate the `search_vector` with standard-Unicode tokens.

### 5. [`src/backend/documents/tests/test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py)

Added 12 new test cases in `TestNormalizeForFts` class:

| Test | Description |
|------|-------------|
| `test_nfkc_lam_initial_form` | Lam initial form (U+FEDF) → standard Lam (U+0644) |
| `test_nfkc_alef_isolated_form` | Alef isolated form (U+FE8D) → standard Alef (U+0627) |
| `test_nfkc_zain_isolated_form` | Zain isolated form (U+FEAF) → standard Zain (U+0632) |
| `test_nfkc_meem_initial_form` | Meem isolated form (U+FEE1) → standard Meem (U+0645) |
| `test_nfkc_lam_alef_ligature` | Lam-Alef ligature (U+FEFB) → standard Lam + Alef (U+0644 U+0627) |
| `test_nfkc_whole_word_presentation_forms` | Whole word "لازم" with all presentation forms → standard Unicode |
| `test_nfkc_mixed_presentation_and_standard` | Mixed presentation forms and standard chars |
| `test_nfkc_idempotent` | NFKC normalization is idempotent |
| `test_nfkc_standard_text_unchanged` | Standard Persian text is not affected |
| `test_nfkc_english_text_unchanged` | English/Latin text is not affected |
| `test_nfkc_persian_digits_still_normalized` | Persian digits still normalized after NFKC step |

### 6. [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py)

Added 3 new test cases in `KeywordSearchTest` class:

| Test | Description |
|------|-------------|
| `test_keyword_search_trigram_fallback_on_no_results` | When FTS returns zero results, trigram fallback kicks in |
| `test_keyword_search_trigram_fallback_disabled` | When trigram fallback is disabled, FTS zero results returns empty |
| `test_keyword_search_trigram_fallback_with_persian_digits` | Trigram fallback works with Persian digits in the query |

### 7. [`src/backend/documents/tests/test_search_integration.py`](src/backend/documents/tests/test_search_integration.py)

**Fixed expected keys** — Added `"trigram_score"` to the `expected_keys` set in `test_search_integration_end_to_end` to match the hybrid search result schema.

### 8. [`docs/references/database-schema.md`](docs/references/database-schema.md)

Documented migration 0011 in the Migrations section.

---

## Files Changed (Complete List)

| # | File | Action | Description |
|---|------|--------|-------------|
| 1 | [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py) | Modified | Added `unicodedata` import, `_nfkc_normalize()` method, NFKC as Stage 0 in `normalize()`, NFKC as Step 0 in `normalize_for_fts()` |
| 2 | [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) | Modified | Added `enable_trigram_fallback` parameter + trigram fallback logic in `keyword_search()` |
| 3 | [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py) | Modified | Added `unicodedata` import + NFKC normalization to user query preprocessing |
| 4 | [`src/backend/documents/migrations/0011_normalize_presentation_forms.py`](src/backend/documents/migrations/0011_normalize_presentation_forms.py) | **NEW** | Re-normalize all existing chunks with NFKC normalization |
| 5 | [`src/backend/documents/tests/test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py) | Modified | Added 12 test cases for NFKC normalization of Arabic Presentation Forms |
| 6 | [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) | Modified | Added 3 test cases for trigram fallback |
| 7 | [`src/backend/documents/tests/test_search_integration.py`](src/backend/documents/tests/test_search_integration.py) | Modified | Added `trigram_score` to expected result keys |
| 8 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | Modified | Documented migration 0011 |
| 9 | [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Modified | This file |

---

## Bug Fixes Applied After Initial Implementation

During test execution, 6 failures were identified and fixed:

| # | Test | Root Cause | Fix |
|---|------|------------|-----|
| 1 | `test_nfkc_zain_isolated_form` | Used `U+FEB1` (SEEN isolated form) instead of `U+FEAF` (ZAIN isolated form) | Changed codepoint to `U+FEAF` |
| 2 | `test_nfkc_whole_word_presentation_forms` | Same wrong codepoint in test data | Changed `\uFEB1` → `\uFEAF` |
| 3 | `test_nfkc_mixed_presentation_and_standard` | Same wrong codepoint in test data | Changed `\uFEB1` → `\uFEAF` |
| 4 | `test_nfkc_persian_digits_still_normalized` | Same wrong codepoint in test data | Changed `\uFEB1` → `\uFEAF` |
| 5 | `test_keyword_search_trigram_fallback_with_presentation_forms` | Trigram on raw presentation-form content cannot match standard query (different byte sequences) | Replaced with `test_keyword_search_trigram_fallback_with_persian_digits` — tests a realistic scenario where trigram CAN help |
| 6 | `test_search_integration_end_to_end` | Missing `trigram_score` key in expected result set | Added `"trigram_score"` to `expected_keys` |

---

## Next Steps / Verification

1. **Run the migration** to re-normalize existing chunks:
   ```
   docker-compose exec backend python manage.py migrate
   ```

2. **Verify the migration** was applied:
   ```
   docker-compose exec backend python manage.py showmigrations documents
   ```

3. **Run all tests** to confirm everything works (✅ 372 passed as of 2026-05-06):
   ```
   docker-compose exec backend python -m pytest documents/tests/ -v
   ```

4. **Test the fix** with the failing queries:
   - Query: `"تفاوت بین عقد جایز و عقد لازم چیست؟"` — should return relevant chunks
   - Query: `"عقد لازم چیه"` — should return chunks containing "عقد لازم"
   - Query: `"عقد جایز چیه"` — should return chunks containing "عقد جایز"

5. **Manual verification**: Re-upload the problematic PDF document (or run migration 0011 on existing chunks) and verify that Ctrl+F in the PDF viewer can now find "لازم" and "جایز".
