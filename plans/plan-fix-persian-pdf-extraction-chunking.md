# Action Plan: Fix Persian PDF Text Extraction & Chunking Pipeline

## 1. Current Architecture Analysis

### 1.1 PDF Extraction Pipeline

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:208)

The extraction uses a **3-layer fallback strategy**:

| Layer | Library | Function | When Used |
|-------|---------|----------|-----------|
| 1 (Primary) | **PyMuPDF (fitz)** | [`_extract_with_pymupdf_rtl()`](src/backend/documents/tasks/document_processing.py:120) | Always first |
| 2 (Fallback 1) | **pdfplumber** | [`_extract_with_pdfplumber()`](src/backend/documents/tasks/document_processing.py:145) | If PyMuPDF output >30% isolated Persian chars |
| 3 (Fallback 2) | **Tesseract OCR** | [`_extract_with_tesseract()`](src/backend/documents/tasks/document_processing.py:167) | If pdfplumber also garbled |

**Current PyMuPDF flags used:**
```python
flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE
```

### 1.2 Persian Normalizer

**File:** [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:104)

The normalizer applies 6 stages in order:
1. **NFKC normalization** — converts Arabic Presentation Forms-B to standard Unicode
2. **Tatweel/Kashida stripping** — removes `U+0640`
3. **Control character cleanup** — removes PDF artifacts
4. **Arabic→Persian character normalization** — via `hazm`
5. **Half-space (ZWNJ) fixing** — via `hazm` + custom regex
6. **Final whitespace cleanup**

**Critical gap:** The normalizer has **NO logic to fix broken words** caused by RTL extraction issues. The docstring explicitly warns:
> "This normalizer handles character-level issues but **CANNOT fix structural RTL reversal**"

### 1.3 Chunking Service

**File:** [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:105)

Two strategies:

| Strategy | Trigger | Split Points | Overlap |
|----------|---------|--------------|---------|
| **Legal structural** | Detects `ماده`/`فصل` markers | Article boundaries, clause boundaries | Clause-aware (`legal_overlap_clauses=1`) |
| **Sentence-boundary** (fallback) | No legal markers | `.`, `!`, `?` or space | Character-based (`overlap=200` chars) |

**Current parameters (hardcoded in [`chunk_document()`](src/backend/documents/tasks/document_processing.py:489)):**
```python
chunk_size=1000,           # Sentence-boundary mode only
overlap=200,               # Sentence-boundary mode only (20% of chunk_size)
legal_max_chunk_size=2000, # From settings (default: 2000)
legal_overlap_clauses=1,   # From settings (default: 1)
```

---

## 2. Root Cause Analysis

### Problem 1: Persian Words Shattered During PDF Extraction

**Root Cause:** The current PyMuPDF flags (`TEXT_PRESERVE_LIGATURES | TEXT_PRESERVE_WHITESPACE`) are **insufficient** for complex Persian legal PDFs. PyMuPDF's default text extraction for RTL text can:

- Insert spurious spaces **between characters** of a single Persian word (e.g., `ق ا ن و ن` instead of `قانون`)
- Break words at **line boundaries** within the PDF's internal text objects
- Mis-order characters due to RTL bidirectional text reordering

The garbled-text heuristic [`_is_persian_text_garbled()`](src/backend/documents/tasks/document_processing.py:56) only checks for **isolated Persian characters** (surrounded by non-Persian). But the real problem is **spaces inserted between Persian characters** — which the heuristic does NOT detect because the characters are still adjacent to other Persian chars.

**Example of what happens:**
- PDF internal: `[RTL] قانون مدنی `
- PyMuPDF output: `ق ا ن و ن   م د ن ی` (spaces between letters)
- Heuristic: Each Persian char has Persian neighbors → NOT flagged as garbled
- Result: `قانون` becomes `ق ا ن و ن` → keyword search fails, embedding is garbage

### Problem 2: Chunking Cuts Mid-Sentence/Mid-Word

**Root Cause A (Sentence-boundary mode):** The [`_find_split_point()`](src/backend/documents/services/chunking_service.py:781) method only recognizes `.`, `!`, `?` as sentence endings. **Persian text uses `؟` (U+061F) as question mark** and `،` (U+060C) as comma. The method does NOT recognize Persian sentence-ending characters.

**Root Cause B (Sentence-boundary mode):** When no sentence boundary is found, it falls back to **last space character**. But if the text has broken words (Problem 1), spaces appear between every character, so the split happens at arbitrary positions within words.

**Root Cause C (Legal structural mode):** The legal chunking works well for well-structured legal text with `ماده` markers. But if the PDF extraction is garbled (Problem 1), the `LegalStructureDetector` may fail to detect `ماده` patterns because the text is `م ا د ه` instead of `ماده`.

**Root Cause D (Overlap too small):** The sentence-boundary overlap is only **200 characters (20%)**. For Persian legal text where a single article can span multiple chunks, this is insufficient to maintain context. The legal mode's clause-aware overlap of 1 clause is also minimal.

---

## 3. Proposed Changes

### Change 1 (REVISED): Fix Shattered Persian Words — Two-Pronged Strategy

**The naive regex approach (`r'([\u0600-\u06FF])\s+([\u0600-\u06FF])'`) is rejected** because it would merge real word boundaries (e.g., `قانون تجارت` → `قانونتجارت`).

Instead, we use **two complementary approaches**:

#### Prong A: Upgrade the Garbled-Text Heuristic to Detect Shattered Words

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:56)

**What:** Add a **second heuristic** to `_is_persian_text_garbled()` that detects "shattered word" patterns — where Persian text has an abnormally high ratio of single-character "words" (sequences of Persian chars separated by spaces).

**Algorithm:**
```python
def _has_shattered_persian_words(text: str, threshold: float = 0.4) -> bool:
    """Detect if Persian text has shattered words (spaces between letters).
    
    Counts how many Persian "words" (space-delimited tokens) consist of 
    a single Persian character. In normal Persian text, single-character 
    words are rare (e.g., 'و' meaning 'and'). In shattered text, almost 
    every character becomes its own "word".
    
    Args:
        text: Extracted text to evaluate.
        threshold: If ratio of single-Persian-char tokens exceeds this,
                   the text is considered shattered.
    
    Returns:
        True if text appears to have shattered Persian words.
    """
    tokens = text.split()
    if not tokens:
        return False
    
    persian_range = range(0x0600, 0x06FF + 1)
    single_char_count = 0
    persian_token_count = 0
    
    for token in tokens:
        # Count Persian chars in this token
        persian_chars = [c for c in token if ord(c) in persian_range]
        if not persian_chars:
            continue
        persian_token_count += 1
        # If the token is exactly one Persian character (possibly with 
        # surrounding non-Persian), it's suspicious
        if len(persian_chars) == 1:
            single_char_count += 1
    
    if persian_token_count == 0:
        return False
    
    ratio = single_char_count / persian_token_count
    return ratio > threshold
```

This is integrated into the existing `_is_persian_text_garbled()` check — if **either** the existing isolated-char heuristic **or** the new shattered-word heuristic triggers, the text is considered garbled and the fallback pipeline activates.

#### Prong B: Enhance pdfplumber Extraction with `arabic_reshaper` + `bidi`

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:145)

**What:** When pdfplumber is used as fallback (which already happens when PyMuPDF is garbled), enhance its output with `arabic_reshaper` and `python-bidi` libraries for proper RTL text reconstruction.

**New dependencies to add to `requirements.txt`:**
```
arabic_reshaper>=3.0.0
python-bidi>=0.4.2
```

**Updated `_extract_with_pdfplumber()`:**
```python
def _extract_with_pdfplumber(pdf_content: bytes) -> str:
    """Fallback extraction using pdfplumber with RTL reshaping.
    
    Uses arabic_reshaper and python-bidi to properly reconstruct
    Persian/Arabic text from pdfplumber's output, which handles
    RTL layout better than PyMuPDF for complex legal PDFs.
    """
    import arabic_reshaper
    from bidi.algorithm import get_display
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        page_texts: list[str] = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            # Reshape Persian/Arabic text for proper RTL rendering
            if text.strip():
                try:
                    reshaped = arabic_reshaper.reshape(text)
                    text = get_display(reshaped)
                except Exception:
                    pass  # Fall back to raw text if reshaping fails
            page_texts.append(f"[PAGE {i + 1}]\n{text}")
    return "\n".join(page_texts)
```

**Why this works:** `arabic_reshaper` converts Persian characters from their isolated forms to their correct positional forms (initial, medial, final), and `python-bidi` applies the Unicode Bidirectional Algorithm to reorder the text correctly for RTL. This fixes the shattered-word problem at the extraction level rather than trying to patch it after the fact.

### Change 2: Upgrade PyMuPDF Extraction Flags

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:137)

**What:** Add `fitz.TEXT_PRESERVE_IMAGES` and `fitz.TEXT_DEHYPHENATE` flags.

**New flags:**
```python
flags=(
    fitz.TEXT_PRESERVE_LIGATURES |
    fitz.TEXT_PRESERVE_WHITESPACE |
    fitz.TEXT_PRESERVE_IMAGES |
    fitz.TEXT_DEHYPHENATE
)
```

### Change 3: Add Persian Sentence Endings to Split Point Detection

**File:** [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:44)

**What:** Add Persian sentence-ending characters to `_SENTENCE_ENDINGS`.

```python
_SENTENCE_ENDINGS: set[str] = {".", "!", "?", "؟", "،", "؛"}
```

- `؟` (U+061F) — Persian/Arabic question mark
- `،` (U+060C) — Persian/Arabic comma
- `؛` (U+061B) — Persian/Arabic semicolon

### Change 4: Update `_find_split_point()` Priority for Persian Punctuation

**File:** [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:781)

**What:** Update the priority order to recognize Persian punctuation first.

**New priority order:**
1. Persian sentence endings (`؟`, `،`, `؛`) followed by space/newline
2. Standard sentence endings (`.`, `!`, `?`) followed by space/newline
3. Double newline (paragraph break)
4. Last space character
5. Hard split at `window_end`

### Change 5: Increase Chunk Overlap

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:492)

**What:** Increase overlap from 200 (20%) to 300 (30%).

```python
chunk_results = chunking_service.chunk_text(
    extracted_text,
    chunk_size=1000,
    overlap=300,  # Was 200 — now 30% of chunk_size
    ...
)
```

### Change 6: Add Comprehensive Tests

**New tests needed:**

1. **`test_persian_normalizer.py`** (new file) — Test `_has_shattered_persian_words()`:
   - Normal Persian text: `"قانون مدنی جمهوری اسلامی ایران"` → `False`
   - Shattered text: `"ق ا ن و ن   م د ن ی"` → `True`
   - Mixed text: `"قانون مدنی ج م ه و ر ی"` → `True`
   - English text: `"This is a test"` → `False`
   - Empty/edge cases

2. **`test_chunking_service.py`** — Add tests for Persian sentence endings:
   - Text with `؟` → split at `؟`
   - Text with `،` → split at `،`
   - Text with `؛` → split at `؛`

3. **`test_tasks.py`** — Update extraction tests:
   - Test that `_has_shattered_persian_words` is called during extraction
   - Test fallback routing when shattered words detected

---

## 4. Implementation Plan (Step-by-Step)

### Step 1: Add `_has_shattered_persian_words()` to `document_processing.py`

**Files to modify:**
- [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)

**Changes:**
1. Add `_has_shattered_persian_words()` function (new heuristic)
2. Integrate it into the garbled-text check in `extract_text_from_pdf()` — call it alongside `_is_persian_text_garbled()`

### Step 2: Add `arabic_reshaper` + `python-bidi` Dependencies

**Files to modify:**
- [`src/backend/requirements.txt`](src/backend/requirements.txt)

**Changes:**
1. Add `arabic_reshaper>=3.0.0`
2. Add `python-bidi>=0.4.2`

### Step 3: Enhance pdfplumber Extraction with RTL Reshaping

**Files to modify:**
- [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:145)

**Changes:**
1. Update `_extract_with_pdfplumber()` to use `arabic_reshaper` and `python-bidi`

### Step 4: Update PyMuPDF Extraction Flags

**Files to modify:**
- [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:137)

**Changes:**
1. Add `fitz.TEXT_PRESERVE_IMAGES` and `fitz.TEXT_DEHYPHENATE` to the flags

### Step 5: Add Persian Sentence Endings to Chunking Service

**Files to modify:**
- [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:44)
- [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:781)

**Changes:**
1. Add `"؟"`, `"،"`, `"؛"` to `_SENTENCE_ENDINGS`
2. Update `_find_split_point()` priority order to include Persian endings

### Step 6: Increase Chunk Overlap

**Files to modify:**
- [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:492)

**Changes:**
1. Change `overlap=200` to `overlap=300`

### Step 7: Write Tests

**Files to create/modify:**
- New: `src/backend/documents/tests/test_persian_normalizer.py`
- Modify: `src/backend/documents/tests/test_chunking_service.py`
- Modify: `src/backend/documents/tests/test_tasks.py`

### Step 8: Run Full Test Suite & Verify

- Run `docker-compose exec backend pytest` to verify no regressions
- Run specific tests for the modified modules

---

## 5. Files Changed Summary

| # | File | Action | Description |
|---|------|--------|-------------|
| 1 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) | Modify | Add `_has_shattered_persian_words()` heuristic, integrate into garbled check |
| 2 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:145) | Modify | Enhance `_extract_with_pdfplumber()` with `arabic_reshaper` + `bidi` |
| 3 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:137) | Modify | Add `TEXT_PRESERVE_IMAGES` and `TEXT_DEHYPHENATE` flags |
| 4 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:492) | Modify | Increase overlap from 200 to 300 |
| 5 | [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:44) | Modify | Add Persian sentence endings to `_SENTENCE_ENDINGS` |
| 6 | [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py:781) | Modify | Update `_find_split_point()` priority for Persian punctuation |
| 7 | [`src/backend/requirements.txt`](src/backend/requirements.txt) | Modify | Add `arabic_reshaper` and `python-bidi` |
| 8 | `src/backend/documents/tests/test_persian_normalizer.py` | **Create** | Tests for `_has_shattered_persian_words()` |
| 9 | [`src/backend/documents/tests/test_chunking_service.py`](src/backend/documents/tests/test_chunking_service.py) | Modify | Add tests for Persian sentence endings |
| 10 | [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Modify | Update WIP context |
| 11 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | No change | No schema changes needed |

---

## 6. Revised Fix #1 — Detailed Logic

### Flow Diagram for Garbled Text Detection

```
extract_text_from_pdf(document_id)
    │
    ├── Stage 1: PyMuPDF extraction
    │       │
    │       ▼
    ├── Check 1: _is_persian_text_garbled()  [existing: isolated chars]
    │       │
    │       ▼
    ├── Check 2: _has_shattered_persian_words()  [NEW: single-char tokens]
    │       │
    │       ▼
    ├── If EITHER check triggers → fallback to pdfplumber
    │       │
    │       ▼
    ├── pdfplumber extraction (ENHANCED with arabic_reshaper + bidi)
    │       │
    │       ▼
    ├── Repeat Check 1 + Check 2
    │       │
    │       ▼
    ├── If still garbled → fallback to Tesseract OCR
    │
    ▼
    PersianNormalizer.normalize()
```

### Why This Is Better Than the Naive Regex

| Approach | Problem | Solution |
|----------|---------|----------|
| **Naive regex** (`[\u0600-\u06FF]\s+[\u0600-\u06FF]`) | Merges real word boundaries (`قانون تجارت` → `قانونتجارت`) | ❌ Rejected |
| **Prong A: Shattered-word heuristic** | Only detects the problem, doesn't fix it | ✅ Routes to better extractor |
| **Prong B: arabic_reshaper + bidi** | Fixes the root cause at extraction level | ✅ Produces clean text |

The key insight is: **if PyMuPDF produces shattered text for a given PDF, it will do so for the ENTIRE document**. So detecting the shattered pattern and routing to pdfplumber (with RTL reshaping) is more reliable than trying to patch individual broken words with regex.

---

## 7. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| `arabic_reshaper` + `bidi` might distort non-Persian text | Low | Only applied in pdfplumber fallback path (already triggered for garbled text) |
| Shattered-word heuristic might false-positive on short text | Low | Only triggers when ratio exceeds 0.4 threshold; short texts have fewer tokens |
| `TEXT_DEHYPHENATE` might affect English text | Low | Only affects hyphenated words; English text is unaffected |
| Increased overlap (200→300) might increase chunk count | Low | 10% increase in overlap → ~10% more chunks, proportional storage increase |
| Persian sentence endings might cause over-splitting | Low | Only split when followed by space/newline (same as English endings) |
| Existing tests might fail due to changed overlap | Medium | Update test assertions that check exact overlap values |

---

## 8. Verification Criteria

After implementation, the following must be true:

1. **Shattered-word detection:** `_has_shattered_persian_words("ق ا ن و ن   م د ن ی")` returns `True`
2. **Normal text passes:** `_has_shattered_persian_words("قانون مدنی جمهوری اسلامی ایران")` returns `False`
3. **Fallback routing:** When shattered words detected, extraction routes to pdfplumber (not PyMuPDF)
4. **pdfplumber enhancement:** `_extract_with_pdfplumber()` uses `arabic_reshaper` + `bidi` for RTL reshaping
5. **PyMuPDF flags:** Extraction uses all 4 flags (PRESERVE_LIGATURES, PRESERVE_WHITESPACE, PRESERVE_IMAGES, DEHYPHENATE)
6. **Persian sentence endings:** Chunks split at `؟`, `،`, `؛` boundaries in sentence-boundary mode
7. **Overlap:** Sentence-boundary mode uses 300-char overlap (30%)
8. **No regressions:** All existing tests pass
9. **New tests pass:** All new tests for shattered-word detection and Persian sentence endings pass
