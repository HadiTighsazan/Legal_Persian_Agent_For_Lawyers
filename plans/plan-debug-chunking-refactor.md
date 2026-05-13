# Debug & Fix Plan — Chunking Refactor Issues

## Overview

The chunking refactor (plan `plans/plan-chunking-refactor.md`) was implemented but introduced several bugs causing:
- **404 errors** on file upload / processing
- **503 errors** and repeated request failures
- **Import errors** from deleted modules still referenced elsewhere

This plan identifies all root causes and provides step-by-step fixes.

---

## Root Cause Analysis

### 🔴 Issue 1: `import_reference_laws.py` — Broken Import (CRITICAL)

**File:** [`src/backend/documents/management/commands/import_reference_laws.py`](src/backend/documents/management/commands/import_reference_laws.py:54)

```python
from documents.services.chunking_service import ChunkingService  # LINE 54 — BROKEN
...
chunking_service = ChunkingService()  # LINE 162 — BROKEN
```

The old `ChunkingService` was **deleted** (Phase 8 of the plan), but this management command still imports and uses it. Any attempt to run `import_reference_laws` will raise `ModuleNotFoundError`.

**Fix:** Replace with `AnchorChunkingService` and update the method signatures.

---

### 🔴 Issue 2: `test_tasks.py` — Broken Import (CRITICAL)

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py:26)

```python
from documents.services.chunking_service import ChunkingService  # LINE 26 — BROKEN
```

This test file still imports the deleted `ChunkingService`. Running tests will fail with `ModuleNotFoundError`.

**Fix:** Replace with `AnchorChunkingService` or remove the import if unused in tests.

---

### 🔴 Issue 3: `NonTextChunkFilter` — Type Mismatch (HIGH)

**File:** [`src/backend/documents/services/non_text_filter.py`](src/backend/documents/services/non_text_filter.py:218)

```python
def filter_chunks(self, chunks: List["ChunkResult"]) -> List["ChunkResult"]:
```

The `NonTextChunkFilter.filter_chunks()` method expects `List[ChunkResult]` (the old type from `ChunkingService`), but the new `AnchorChunkingService.chunk_text()` returns `List[AnchorChunk]`. The type annotation is wrong, and while Python doesn't enforce types at runtime, this could cause attribute access issues if the filter accesses `ChunkResult`-specific attributes.

**Fix:** Update the type annotation to accept `List[AnchorChunk]` (or a union type), and verify the filter only accesses `.content` (which both types have).

---

### 🔴 Issue 4: `test_non_text_filter.py` — Broken Type Reference (MEDIUM)

**File:** [`src/backend/documents/tests/test_non_text_filter.py`](src/backend/documents/tests/test_non_text_filter.py:30)

```python
class FakeChunkResult:
    """Minimal stand-in for :class:`~documents.services.chunking_service.ChunkResult`."""
```

The docstring references the deleted `ChunkResult`. While the `FakeChunkResult` class itself works, the docstring is misleading.

**Fix:** Update docstring to reference `AnchorChunk`.

---

### 🔴 Issue 5: `extract_text_from_pdf` — PDF Content Read After Close (HIGH)

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:439-529)

The scanned PDF detection logic has a critical flow issue:

1. **Line 400:** `pdf_document = fitz.open(stream=pdf_content, filetype="pdf")` — Opens the PDF
2. **Line 444-449:** `pdf_bytes_for_check = pdf_content.read()` — Reads the bytes from the storage backend
3. **Line 480:** `pdf_document.close()` — Closes the PyMuPDF document (if scanned)
4. **Line 500-506:** If EasyOCR fails, it tries to re-open: `pdf_document_for_extraction = fitz.open(stream=pdf_bytes_for_check, filetype="pdf")` — This is fine since it uses the saved bytes
5. **BUT** in the `else` branch (line 530-549, when EasyOCR is disabled), the code does:
   - `pdf_bytes = pdf_content.read()` — Reads bytes
   - `pdf_document_for_extraction = fitz.open(stream=pdf_bytes, filetype="pdf")` — Opens
   - `pdf_document_for_extraction.close()` — Closes
   - `pdf_document.close()` — Closes the original
   
   **However**, at line 449, `pdf_content.seek(0)` was called, but if `pdf_content` is a `bytes` object (not a stream), `seek()` does nothing. Then at line 532, `pdf_content.read()` is called again on an already-consumed stream — this returns empty bytes!

**Fix:** Save `pdf_bytes` early (before any reads) and use it consistently throughout.

---

### 🔴 Issue 6: `auto_fallback` Variable Scope Bug (HIGH)

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:554)

```python
if auto_fallback is None:
    auto_fallback = getattr(settings, "EXTRACTION_AUTO_FALLBACK", True)
```

The variable `auto_fallback` is only defined in two branches:
- **Line 484:** `auto_fallback = False` — Set when scanned PDF is detected
- **Line 548:** `auto_fallback = getattr(settings, "EXTRACTION_AUTO_FALLBACK", True)` — Set when EasyOCR is disabled

**But** if the scanned PDF detection itself throws an exception (lines 509-529), the code falls through to the fallback extraction chain **without setting `auto_fallback`**. This means `auto_fallback` is undefined, causing a `NameError` at line 554.

**Fix:** Initialize `auto_fallback = True` at the top of the function, before any conditional branches.

---

### 🔴 Issue 7: `extract_text_from_pdf` — Double-close of `pdf_document` (MEDIUM)

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:480, 546)

When a scanned PDF is detected:
1. Line 480: `pdf_document.close()` — Closes the document
2. Line 546: `pdf_document.close()` — This is in the `else` branch (EasyOCR disabled), so it won't execute for scanned PDFs

But in the exception fallback path (lines 509-529), the code opens a **new** `pdf_document_for_extraction` and closes it, but the original `pdf_document` was never closed. This is a resource leak.

**Fix:** Use a `try/finally` block to ensure `pdf_document` is always closed.

---

### 🔴 Issue 8: `is_scanned_pdf` — Temp File Cleanup Risk (LOW)

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:451-460)

```python
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp.write(pdf_bytes_for_check)
    tmp_path = tmp.name

try:
    scanned = is_scanned_pdf(tmp_path)
finally:
    os.unlink(tmp_path)
```

The temp file is created with `delete=False` (needed because PyMuPDF needs a file path), then manually deleted in `finally`. This is correct, but if `is_scanned_pdf` raises an exception (e.g., corrupted PDF), the temp file is still cleaned up. However, `os.unlink` could also fail on Windows if the file handle isn't released.

**Fix:** Add error handling around `os.unlink` to prevent secondary exceptions.

---

### 🔴 Issue 9: `chunk_document` — `document_id` Type Mismatch in Log (LOW)

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:748)

```python
logger.info(
    "Non-text chunk filter removed %d chunk(s) "
    "(kept %d) for document %d",
    filtered_count,
    len(chunk_results),
    document_id,  # document_id is a string (UUID), but %d expects integer
)
```

The `document_id` is a UUID string, but the format specifier is `%d` (integer). This will cause a `TypeError` or `ValueError` in the logging call.

**Fix:** Change `%d` to `%s` in the log format string.

---

### 🔴 Issue 10: `AnchorChunkingService` — `_resolve_pages` Logic Bug (MEDIUM)

**File:** [`src/backend/documents/services/anchor_chunking_service.py`](src/backend/documents/services/anchor_chunking_service.py:449-468)

```python
for pos, page_num in page_map:
    if pos <= start:
        active_page = page_num
    if start <= pos < end:
        pages.add(page_num)

pages.add(active_page)

for pos, page_num in page_map:
    if start < pos < end:
        pages.add(page_num)
```

The second loop (`start < pos < end`) is redundant — the first loop already adds pages where `start <= pos < end`. The second loop uses `<` instead of `<=`, so it's a subset of the first. This is not a bug per se, but it's dead code.

More importantly, the `active_page` logic has a subtle issue: if `start` is **before** the first page marker, `active_page` stays at 1 (default). But what if the document starts on page 1? That's correct. However, if `start` is between two page markers, `active_page` correctly gets the page of the marker before `start`. This logic is actually correct.

**Fix:** Remove the redundant second loop for clarity.

---

## Summary of All Issues

| # | Severity | File | Line(s) | Issue |
|---|----------|------|---------|-------|
| 1 | 🔴 CRITICAL | `import_reference_laws.py` | 54, 162 | Import of deleted `ChunkingService` — causes `ModuleNotFoundError` |
| 2 | 🔴 CRITICAL | `test_tasks.py` | 26 | Import of deleted `ChunkingService` — causes `ModuleNotFoundError` |
| 3 | 🟠 HIGH | `non_text_filter.py` | 218 | Type annotation references deleted `ChunkResult` |
| 4 | 🟡 MEDIUM | `test_non_text_filter.py` | 30 | Docstring references deleted `ChunkResult` |
| 5 | 🟠 HIGH | `document_processing.py` | 532 | `pdf_content.read()` on already-consumed stream returns empty bytes |
| 6 | 🟠 HIGH | `document_processing.py` | 554 | `auto_fallback` may be undefined in exception fallback path |
| 7 | 🟡 MEDIUM | `document_processing.py` | 480, 546 | Resource leak: `pdf_document` not closed in exception path |
| 8 | 🟢 LOW | `document_processing.py` | 460 | `os.unlink` could raise on Windows |
| 9 | 🟢 LOW | `document_processing.py` | 748 | `%d` format specifier for UUID string causes `TypeError` |
| 10 | 🟢 LOW | `anchor_chunking_service.py` | 463-466 | Redundant loop in `_resolve_pages` |

---

## Fix Plan (Execution Order)

### Step 1: Fix `import_reference_laws.py` — Replace `ChunkingService` with `AnchorChunkingService`

**Changes:**
1. Change import from `ChunkingService` to `AnchorChunkingService`
2. Update `chunking_service.chunk_text(content)` call to use `AnchorChunkingService.chunk_text()` signature
3. Update type annotations in method signatures

### Step 2: Fix `test_tasks.py` — Replace broken import

**Changes:**
1. Change import from `ChunkingService` to `AnchorChunkingService`
2. Update any test code that uses `ChunkingService`

### Step 3: Fix `non_text_filter.py` — Update type annotations

**Changes:**
1. Change `List["ChunkResult"]` to `List[AnchorChunk]` (or use a Protocol)
2. Import `AnchorChunk` from `anchor_chunking_service`

### Step 4: Fix `test_non_text_filter.py` — Update docstring

**Changes:**
1. Update docstring to reference `AnchorChunk` instead of `ChunkResult`

### Step 5: Fix `document_processing.py` — Stream consumption bug

**Changes:**
1. Read `pdf_bytes` early, before any conditional branches
2. Use the saved bytes consistently throughout the function
3. Initialize `auto_fallback = True` at function start
4. Fix `%d` → `%s` in log format string
5. Add `try/finally` for `pdf_document.close()`

### Step 6: Fix `anchor_chunking_service.py` — Clean up redundant code

**Changes:**
1. Remove the redundant second loop in `_resolve_pages`

---

## Testing After Fixes

```bash
# Run all tests to verify no regressions
docker-compose exec backend pytest

# Specifically test the fixed areas
docker-compose exec backend pytest documents/tests/test_tasks.py -v
docker-compose exec backend pytest documents/tests/test_non_text_filter.py -v
docker-compose exec backend pytest documents/tests/test_anchor_chunking_service.py -v

# Test the management command (dry-run)
docker-compose exec backend python manage.py import_reference_laws --dry-run
```

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| `import_reference_laws.py` still broken after fix | Cannot import reference laws | Test with `--dry-run` flag first |
| `test_tasks.py` has complex mocking that may break | Test suite fails | Run tests incrementally |
| Stream consumption fix changes behavior for typed PDFs | Extraction fails for typed PDFs | Test with both typed and scanned PDF samples |
