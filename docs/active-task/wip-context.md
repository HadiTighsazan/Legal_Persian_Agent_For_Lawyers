# WIP Context — Phase 3: Bidi Parenthesis Fix

## Status: ✅ COMPLETED — Phase 3 Fully Implemented and Tested

## Latest: Phase 3 — Bidi Parenthesis Fix (2026-05-14)

### Changes Made

#### 3.1 Safe Bracket Balancing — `_fix_bidi_brackets()` (`document_processing.py`)

**Problem:** PyMuPDF doesn't handle RTL/LTR bracket direction. Using `python-bidi`'s `get_display()` for storage is dangerous because it performs visual reordering that corrupts logical order.

**Solution:** Added `_fix_bidi_brackets()` function that performs **local bracket balancing** — detects and fixes misplaced brackets without full bidi reordering. The function uses three patterns:

1. **Pattern 1** (weight: position fix): Closing bracket `)` NOT preceded by Persian text, followed by Persian text → moves `)` after the Persian word. Uses negative lookbehind to avoid matching correctly-placed brackets (e.g., `سلام)` where `)` correctly follows Persian text in RTL context).

2. **Pattern 2** (weight: position fix): Persian text followed by opening bracket `(` NOT followed by Persian text → moves `(` before the Persian word. Uses negative lookahead to avoid matching correctly-placed brackets (e.g., `(سلام` where `(` correctly precedes Persian text in RTL context).

3. **Pattern 3** (weight: balance): Count-based balancing only when imbalance >= 3. A difference of 1 or 2 is assumed to be the result of Patterns 1 and 2 having moved brackets to correct positions. When difference >= 3, removes trailing `)` or leading `(` to balance.

**Order of operations:**
- Step 1: Fix bracket positions (Patterns 1 and 2) — move brackets relative to adjacent Persian text segments.
- Step 2: Balance bracket counts (Pattern 3) — remove truly unmatched brackets that position fixing could not resolve.

**Why this is safe:** It only moves brackets relative to adjacent Persian text segments. It does NOT reorder characters, change word order, or apply visual-to-logical transformation. The embedding model sees the same semantic content.

**Files modified:**
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:310) — Added `_fix_bidi_brackets()` function (lines 310-390)
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py:1020) — Applied `_fix_bidi_brackets()` in `extract_text_from_pdf` after Persian normalization, gated by `BIDI_BRACKET_FIX_ENABLED` setting (default `True`)
- [`test_tasks.py`](src/backend/documents/tests/test_tasks.py:1167) — Added `FixBidiBracketsTests` class with 18 tests covering all patterns

### Test Results
```
100 passed in 31.71s
```
All 100 tests pass, including 18 new tests for Phase 3 features (covering Pattern 1, Pattern 2, Pattern 3 balancing, edge cases, mixed Persian/English, real-world legal text, nested brackets, and multiline text).

### Key Design Decisions

1. **Pattern order: position fix first, then balance** — Patterns 1 and 2 run before Pattern 3. This ensures that brackets moved to correct positions by Patterns 1 and 2 are not subsequently removed by Pattern 3 as "unbalanced."

2. **Pattern 3 threshold >= 3** — A difference of 1 or 2 between `(` and `)` counts is assumed to be the result of Patterns 1 and 2 having moved brackets. For example, `)سلام` → `سلام)` creates a single trailing `)` (diff=1), and `))سلام` → `)سلام)` creates a single leading `)` and trailing `)` (diff=0 after position fix). Only when diff >= 3 are there truly extra brackets that position fixing could not resolve.

3. **Negative lookbehind/lookahead guards** — Pattern 1 uses `(?<![\u0600-...])` to avoid matching `)` that already correctly follows Persian text. Pattern 2 uses `(?![{_PERSIAN}])` to avoid matching `(` that already correctly precedes Persian text. This prevents false positives on correctly-placed brackets.

4. **Configurable via settings** — The bidi bracket fix is gated by `BIDI_BRACKET_FIX_ENABLED` setting (default `True`), allowing easy disable if issues are discovered.

### Next Steps
Phase 4+ as defined in the remediation plan (not yet started).

### Reference Docs
- [`document_processing.py`](src/backend/documents/tasks/document_processing.py) — Added `_fix_bidi_brackets()` function and integration in extraction pipeline
- [`test_tasks.py`](src/backend/documents/tests/test_tasks.py) — 18 new tests for Phase 3 features
