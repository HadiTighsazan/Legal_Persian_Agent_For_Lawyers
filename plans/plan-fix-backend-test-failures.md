# Fix Plan: Backend Test Failures — Root Cause Analysis & Action Plan

## Overview

After running the backend test suite, **6 tests failed** and **26 tests errored** (all 26 errors are from the same root cause). This document analyzes each failure, identifies the root cause, and provides a step-by-step fix plan.

---

## Root Cause Analysis

### Category 1: `hazm` Library API Change — 26 ERRORs (all `test_persian_normalizer.py`)

**Error:** `TypeError: Normalizer.__init__() got an unexpected keyword argument 'token_based'`

**Root Cause:** The [`PersianNormalizer.__init__()`](src/backend/documents/services/persian_normalizer.py:75) passes `token_based=False` to `hazm.Normalizer()`. The installed version of `hazm` (>=0.10.0 per requirements.txt) does **not** accept a `token_based` parameter. This parameter was either removed or renamed in a newer hazm release.

**Impact:** All 26 tests in `test_persian_normalizer.py` fail with `ERROR` (not even `FAIL`) because the fixture `normalizer()` cannot instantiate `PersianNormalizer`.

**Fix:** Remove the `token_based` parameter from the `hazm.Normalizer()` constructor call. The default behavior (character-level normalization) is what we want anyway.

---

### Category 2: `test_article_with_chapter` — 1 FAILURE

**File:** [`test_chunking_service.py::TestLegalChunking::test_article_with_chapter`](src/backend/documents/tests/test_chunking_service.py:71)

**Assertion:** `assert len(chunks) == 1` — but `len(chunks) == 2`

**Root Cause:** The `_group_article_segments()` method in [`chunking_service.py`](src/backend/documents/services/chunking_service.py:314) treats **chapter** segments as group separators. When the input is:

```
فصل ۱: مقررات عمومی
ماده ۱: متن ماده اول.
```

The detector produces two segments: a `chapter` segment and an `article` segment. `_group_article_segments()` creates a **separate group** for the chapter (line 318-322), then another group for the article. This produces **2 groups** → **2 chunks** instead of the expected **1 chunk** with chapter metadata.

**Fix:** Modify `_group_article_segments()` so that a chapter segment does **not** create its own group. Instead, the chapter should be merged into the **next article group** as metadata. Alternatively, skip chapter-only groups that have no article content.

---

### Category 3: `test_note_without_number` — 1 FAILURE

**File:** [`test_legal_structure_detector.py::TestNoteDetection::test_note_without_number`](src/backend/documents/tests/test_legal_structure_detector.py:110)

**Assertion:** `assert len(notes) == 1` — but `len(notes) == 0`

**Root Cause:** The `_NOTE_PATTERN` regex is:

```python
_NOTE_PATTERN = re.compile(rf"تبصره\s*{_ANY_NUM}?", re.UNICODE)
```

Where `_ANY_NUM = f"(?:{_PERSIAN_NUM}|{_ARABIC_NUM}|{_ENGLISH_NUM})+"`. The `+` quantifier means **one or more** digits. The `?` after `_ANY_NUM` makes the entire number group optional. However, the regex engine still tries to match `_ANY_NUM` first (greedy), and since `_ANY_NUM` requires **at least one** digit, `تبصره` alone (without any number) does **not** match because the regex expects at least one digit after the optional space.

The issue is that `_ANY_NUM` uses `+` (one or more), so `_ANY_NUM?` means "optionally match one or more digits" — but the regex engine still tries to find digits. When there are no digits after `تبصره`, the match fails entirely because the pattern requires the space + digits to be present as a group.

**Fix:** Change `_NOTE_PATTERN` to make the number portion truly optional by restructuring the regex. The simplest fix:

```python
_NOTE_PATTERN = re.compile(rf"تبصره(?:\s*{_ANY_NUM})?", re.UNICODE)
```

This makes the entire `\s*{_ANY_NUM}` group optional, so `تبصره` alone matches, and `تبصره ۱` also matches.

---

### Category 4: `test_alphabetic_clause` — 1 FAILURE

**File:** [`test_legal_structure_detector.py::TestClauseDetection::test_alphabetic_clause`](src/backend/documents/tests/test_legal_structure_detector.py:143)

**Assertion:** `assert clauses[0].segment_number == "الف"` — but got `"ف"`

**Root Cause:** The `_PERSIAN_ALPHA` character class is:

```python
_PERSIAN_ALPHA = r"[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]"
```

This is a **single-character** class. The Persian letter **الف** is a single character `ا`. However, the test expects the clause number to be `"الف"` (three characters: ا + ل + ف). The regex `_CLAUSE_PATTERN` matches a **single** Persian alphabetic character followed by a dash/ZWNJ. So for `الف-`, it matches only the **last character** `ف` (because the regex engine finds `ف-` as a valid match), not the full word `الف`.

Wait — let me re-examine. The regex is:

```python
_CLAUSE_PATTERN = re.compile(
    rf"(?:{_ANY_NUM}|{_PERSIAN_ALPHA})\s*[\-\u200c]",
    re.UNICODE,
)
```

`_PERSIAN_ALPHA` is `[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]` — this is a character class matching **any single character** from that set. For input `الف-`, `finditer` will find `ف-` (the last character of `الف` followed by `-`) as a match. The `_extract_clause_number` strips the `-` and returns `ف`.

But the test expects `"الف"` — the full word. The issue is that `_PERSIAN_ALPHA` is designed as a single-character class, but Persian alphabetic clause markers can be multi-character words like `الف`, `ب`, `پ`, etc.

**Fix:** The `_PERSIAN_ALPHA` regex needs to match **one or more** Persian alphabetic characters, not just one. Change to:

```python
_PERSIAN_ALPHA = r"[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]+"
```

This ensures multi-character words like `الف` are matched as a whole.

---

### Category 5: `test_clause_with_zwnj` — 1 FAILURE

**File:** [`test_legal_structure_detector.py::TestClauseDetection::test_clause_with_zwnj`](src/backend/documents/tests/test_legal_structure_detector.py:152)

**Assertion:** `assert len(clauses) >= 1` — but `len(clauses) == 0`

**Root Cause:** The input text is `"ماده ۱:\n۱\u200cبند اول"`. The `_normalize_legal_whitespace()` method replaces ZWNJ with a space:

```python
text = re.sub(r"\s*\u200c\s*", " ", text)
```

So `۱\u200cبند` becomes `۱ بند`. After this normalization, the `_CLAUSE_PATTERN` looks for `\s*[\-\u200c]` after the number — but now there's a regular space instead of a dash or ZWNJ. The pattern requires a dash (`-`) or ZWNJ (`\u200c`), but after normalization, the ZWNJ has been replaced with a space, so the clause marker is no longer detectable.

**Fix:** The `_CLAUSE_PATTERN` should also accept a regular space as a valid clause delimiter, OR the clause detection should happen **before** ZWNJ normalization. The better approach is to add space as an alternative delimiter in `_CLAUSE_PATTERN`:

```python
_CLAUSE_PATTERN = re.compile(
    rf"(?:{_ANY_NUM}|{_PERSIAN_ALPHA})\s*[\-\u200c\s]",
    re.UNICODE,
)
```

But this could cause false positives. A more targeted fix: don't normalize ZWNJ to space in the clause context, or run clause detection before whitespace normalization.

Actually, the cleanest fix: the `_normalize_legal_whitespace` replaces ZWNJ with space, which destroys the clause delimiter. The clause pattern should be checked **before** this normalization, or the normalization should preserve ZWNJ when it's used as a clause delimiter.

**Better Fix:** Modify `_normalize_legal_whitespace` to not replace ZWNJ when it's used as a clause delimiter (i.e., when preceded by a numeral/alpha character). Or simpler: change the clause pattern to also match a plain space after the number/letter.

---

### Category 6: `test_chapter_with_ordinal` — 1 FAILURE

**File:** [`test_legal_structure_detector.py::TestChapterDetection::test_chapter_with_ordinal`](src/backend/documents/tests/test_legal_structure_detector.py:174)

**Assertion:** `assert chapters[0].segment_number == "اول"` — but got `None`

**Root Cause:** The `_PERSIAN_ORDINALS` character class is:

```python
_PERSIAN_ORDINALS = r"[اولدومسومچهارمپنجمششمهفتمهشتمنهمدهم]"
```

This is a **single-character** class matching any one character from that set. The word `اول` is three characters: `ا` + `و` + `ل`. The `_CHAPTER_PATTERN` regex:

```python
_CHAPTER_PATTERN = re.compile(
    rf"فصل\s*(?:{_ANY_NUM}|{_PERSIAN_ORDINALS})",
    re.UNICODE,
)
```

For input `فصل اول: مقررات عمومی`, the regex matches `فصل ا` (just the first character of `اول`). Then `_extract_number()` strips the prefix `فصل` and tries to find a number in the remainder ` ا`. The remainder is ` ا` (space + ا), and `_ANY_NUM` doesn't match `ا` because it's not a numeral. So `_extract_number` returns `None`.

**Fix:** The `_PERSIAN_ORDINALS` needs to match **full words**, not individual characters. Change to:

```python
_PERSIAN_ORDINALS = r"(?:اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم)"
```

This uses a non-capturing group with alternation to match complete Persian ordinal words.

---

### Category 7: `test_complete_legal_document` — 1 FAILURE

**File:** [`test_legal_structure_detector.py::TestFullDocumentStructure::test_complete_legal_document`](src/backend/documents/tests/test_legal_structure_detector.py:196)

**Assertion:** `assert len(notes) == 2` — but `len(notes) == 1`

**Root Cause:** This is a **compound failure** caused by the same `_NOTE_PATTERN` issue from Category 3. The test document has two notes:

1. `تبصره ۱: مقررات این ماده شامل موارد زیر نمی‌شود.` — This matches because it has a number.
2. `تبصره: قراردادهای کوچک از این قاعده مستثنی هستند.` — This does **NOT** match because `تبصره` without a number fails the regex (same root cause as Category 3).

So only 1 note is detected instead of 2.

**Fix:** Same fix as Category 3 — make the number portion of `_NOTE_PATTERN` truly optional.

---

## Summary of Root Causes

| # | Test | Root Cause | File to Fix |
|---|------|-----------|-------------|
| 1 | 26 tests in `test_persian_normalizer.py` | `hazm.Normalizer()` doesn't accept `token_based` param | [`persian_normalizer.py:85`](src/backend/documents/services/persian_normalizer.py:85) |
| 2 | `test_article_with_chapter` | `_group_article_segments()` creates separate group for chapter | [`chunking_service.py:314-340`](src/backend/documents/services/chunking_service.py:314) |
| 3 | `test_note_without_number` | `_NOTE_PATTERN` regex requires at least one digit | [`legal_structure_detector.py:51`](src/backend/documents/services/legal_structure_detector.py:51) |
| 4 | `test_alphabetic_clause` | `_PERSIAN_ALPHA` matches single char, not multi-char words | [`legal_structure_detector.py:43`](src/backend/documents/services/legal_structure_detector.py:43) |
| 5 | `test_clause_with_zwnj` | ZWNJ normalization destroys clause delimiter | [`legal_structure_detector.py:55-58`](src/backend/documents/services/legal_structure_detector.py:55) |
| 6 | `test_chapter_with_ordinal` | `_PERSIAN_ORDINALS` matches single char, not full words | [`legal_structure_detector.py:62`](src/backend/documents/services/legal_structure_detector.py:62) |
| 7 | `test_complete_legal_document` | Same root cause as #3 (compound failure) | [`legal_structure_detector.py:51`](src/backend/documents/services/legal_structure_detector.py:51) |

---

## Fix Plan — Actionable Steps

### Step 1: Fix `hazm` API incompatibility

**File:** [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py)

**Change:** Remove `token_based=False` from the `HazmNormalizer()` constructor call on line 85.

```python
# Before:
self._hazm = HazmNormalizer(
    persian_numbers=True,
    remove_diacritics=True,
    remove_specials_chars=False,
    token_based=False,  # ← REMOVE THIS LINE
)

# After:
self._hazm = HazmNormalizer(
    persian_numbers=True,
    remove_diacritics=True,
    remove_specials_chars=False,
)
```

**Verification:** All 26 tests in `test_persian_normalizer.py` should pass.

---

### Step 2: Fix `_NOTE_PATTERN` regex (fixes Categories 3 & 7)

**File:** [`src/backend/documents/services/legal_structure_detector.py`](src/backend/documents/services/legal_structure_detector.py)

**Change:** Line 51 — Make the entire number group optional by wrapping in a non-capturing group.

```python
# Before:
_NOTE_PATTERN = re.compile(rf"تبصره\s*{_ANY_NUM}?", re.UNICODE)

# After:
_NOTE_PATTERN = re.compile(rf"تبصره(?:\s*{_ANY_NUM})?", re.UNICODE)
```

**Verification:** `test_note_without_number` and `test_complete_legal_document` should pass.

---

### Step 3: Fix `_PERSIAN_ALPHA` for multi-character words (fixes Category 4)

**File:** [`src/backend/documents/services/legal_structure_detector.py`](src/backend/documents/services/legal_structure_detector.py)

**Change:** Line 43 — Add `+` quantifier to match one or more Persian alphabetic characters.

```python
# Before:
_PERSIAN_ALPHA = r"[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]"

# After:
_PERSIAN_ALPHA = r"[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]+"
```

**Verification:** `test_alphabetic_clause` should pass.

---

### Step 4: Fix `_PERSIAN_ORDINALS` for full-word matching (fixes Category 6)

**File:** [`src/backend/documents/services/legal_structure_detector.py`](src/backend/documents/services/legal_structure_detector.py)

**Change:** Line 62 — Replace single-character class with alternation of full words.

```python
# Before:
_PERSIAN_ORDINALS = r"[اولدومسومچهارمپنجمششمهفتمهشتمنهمدهم]"

# After:
_PERSIAN_ORDINALS = r"(?:اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم)"
```

**Verification:** `test_chapter_with_ordinal` should pass.

---

### Step 5: Fix `_CLAUSE_PATTERN` for ZWNJ normalization issue (fixes Category 5)

**File:** [`src/backend/documents/services/legal_structure_detector.py`](src/backend/documents/services/legal_structure_detector.py)

**Change:** Lines 55-58 — Add space as an alternative delimiter in the clause pattern, since `_normalize_legal_whitespace` converts ZWNJ to space.

```python
# Before:
_CLAUSE_PATTERN = re.compile(
    rf"(?:{_ANY_NUM}|{_PERSIAN_ALPHA})\s*[\-\u200c]",
    re.UNICODE,
)

# After:
_CLAUSE_PATTERN = re.compile(
    rf"(?:{_ANY_NUM}|{_PERSIAN_ALPHA})\s*[\-\u200c\s]",
    re.UNICODE,
)
```

**Verification:** `test_clause_with_zwnj` should pass.

---

### Step 6: Fix `_group_article_segments` for chapter handling (fixes Category 2)

**File:** [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py)

**Change:** Lines 317-322 — Instead of creating a separate group for chapter segments, merge the chapter into the next article group.

```python
# Before (lines 317-322):
for segment in segments:
    if segment.segment_type == "chapter":
        # Start a new group for the chapter
        if current_group:
            groups.append(current_group)
        current_group = [segment]
    elif segment.segment_type == "article":
        ...

# After:
for segment in segments:
    if segment.segment_type == "chapter":
        # Don't create a separate group for chapters.
        # If we have a current group, append chapter to it.
        # Otherwise, hold it for the next article group.
        if current_group:
            current_group.append(segment)
        else:
            current_group = [segment]
    elif segment.segment_type == "article":
        ...
```

**Verification:** `test_article_with_chapter` should pass. Also verify that `test_complete_legal_document` and `test_metadata_attachment` still pass (they rely on chapter metadata being correctly attached).

---

## Execution Order

The fixes should be applied in this order to minimize cascading issues:

1. **Step 1** — Fix `hazm` API (26 errors → 0 errors)
2. **Step 2** — Fix `_NOTE_PATTERN` (fixes 2 failures)
3. **Step 3** — Fix `_PERSIAN_ALPHA` (fixes 1 failure)
4. **Step 4** — Fix `_PERSIAN_ORDINALS` (fixes 1 failure)
5. **Step 5** — Fix `_CLAUSE_PATTERN` (fixes 1 failure)
6. **Step 6** — Fix `_group_article_segments` (fixes 1 failure)

After all fixes, re-run the full test suite to verify no regressions.

---

## Risk Assessment

- **Low risk:** Steps 1-5 are isolated regex/API changes with clear before/after behavior.
- **Medium risk:** Step 6 changes grouping logic that affects how chapters and articles are combined. Need to verify that `test_complete_legal_document` and `test_metadata_attachment` still produce correct results.
- **No database changes needed.** All fixes are in service-layer code.
- **No API contract changes.** All fixes are internal to the processing pipeline.
