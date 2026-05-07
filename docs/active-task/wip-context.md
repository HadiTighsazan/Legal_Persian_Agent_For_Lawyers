# WIP Context — Safe Non-Text Section Filtering for Persian Legal Chunking

## Status: ✅ COMPLETED (2026-05-07)

All changes from the implementation plan [`plans/plan-safe-non-text-chunk-filtering.md`](plans/plan-safe-non-text-chunk-filtering.md) have been implemented and verified.

---

## What Changed

### Problem Summary

When chunking Persian legal documents, certain sections are **not actual legal content** but structural artifacts (table of contents, headers, footers, page numbers, etc.). These sections, if chunked and embedded, pollute the vector database with meaningless content, degrading RAG retrieval quality.

### Solution

A conservative (high-precision) non-text chunk filter that runs **after chunking** but **before persisting to the database**. The filter uses a chain of detector strategies — currently `TableOfContentsDetector` — with an extensible `BaseDetector` abstract class for future detectors.

### Detection Criteria (Conservative)

1. **Explicit Title Check** (first 300 chars): `فهرست مطالب`, `فهرست مندرجات`, `Table of Contents`, etc.
2. **Structural Line Check**: ≥3 lines ending with digits (page numbers) or containing dotted patterns (`...` or `…`)
3. **Ratio Check**: Structural lines / total lines > **40%**

### Files Created

| File | Description |
|------|-------------|
| [`src/backend/documents/services/non_text_filter.py`](src/backend/documents/services/non_text_filter.py) | **NEW** — `BaseDetector` (abstract), `TableOfContentsDetector`, `NonTextChunkFilter` (orchestrator) |
| [`src/backend/documents/tests/test_non_text_filter.py`](src/backend/documents/tests/test_non_text_filter.py) | **NEW** — 20 tests across 3 test classes |

### Files Modified

| File | Change |
|------|--------|
| [`src/backend/config/settings.py`](src/backend/config/settings.py) | Added `NON_TEXT_CHUNK_FILTERING_ENABLED` setting (default `True`, line 286) |
| [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) | Imported `NonTextChunkFilter` (line 45); applied filter after `chunking_service.chunk_text()` and before `DocumentChunk.bulk_create()` (lines 625-640) |

### New Setting

```python
# Non-Text Chunk Filtering (Epic E11)
NON_TEXT_CHUNK_FILTERING_ENABLED = env.bool('NON_TEXT_CHUNK_FILTERING_ENABLED', default=True)
```

Can be disabled by setting `NON_TEXT_CHUNK_FILTERING_ENABLED=false` in the `.env` file.

### Test Results

```
documents/tests/test_non_text_filter.py .............. 20 passed in 0.49s
```

#### TestTableOfContentsDetector (12 tests)

| Test | Verifies |
|------|----------|
| `test_toc_with_title_and_page_numbers` | Persian TOC with title + page numbers → `True` |
| `test_toc_with_dotted_lines` | Persian TOC with dotted separators → `True` |
| `test_no_title_returns_false` | No explicit title → `False` |
| `test_few_structural_lines` | Only 2 structural lines (<3) → `False` |
| `test_low_structural_ratio` | Ratio <40% → `False` |
| `test_english_toc` | English "Table of Contents" → `True` |
| `test_legal_article_not_toc` | Article containing "فهرست" in body → `False` |
| `test_empty_text` | Empty string → `False` |
| `test_whitespace_only` | Whitespace only → `False` |
| `test_persian_toc_alternative_title` | "فهرست مندرجات" → `True` |
| `test_toc_with_arabic_digits` | Arabic (Eastern) digits → `True` |
| `test_toc_title_appears_later_in_text` | Title beyond 300-char scan window → `False` (safe miss) |

#### TestNonTextChunkFilter (6 tests)

| Test | Verifies |
|------|----------|
| `test_filters_toc_chunks` | TOC chunk removed, real chunks preserved |
| `test_passes_all_real_chunks` | All real chunks unchanged |
| `test_empty_chunks_list` | Empty input → empty output |
| `test_single_toc_chunk` | Single TOC chunk → empty list |
| `test_custom_detector_chain` | Custom detector chain works |
| `test_custom_detector_chain_all_pass` | Custom chain preserves when none match |

#### TestIntegrationWithChunkingService (2 tests)

| Test | Verifies |
|------|----------|
| `test_toc_at_start_of_document` | TOC at start filtered, article chunks preserved |
| `test_toc_in_middle_of_document` | TOC between chapters filtered, surrounding preserved |

---

## Next Steps

1. Add more detectors (e.g., `HeaderFooterDetector`, `PageNumberDetector`) by subclassing `BaseDetector`
2. Monitor false positive rate in production — the conservative thresholds are designed to err on the side of keeping content
3. Consider adding a `NON_TEXT_FILTER_DEBUG_LOGGING` setting to log filtered chunk previews for tuning
