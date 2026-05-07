# WIP Context — Fix Missing Overlap Between Chunks in Persian Legal Document Chunking

## Status: ✅ COMPLETED (2026-05-07)

All changes from the implementation plan [`plans/plan-fix-chunk-overlap-persian-legal.md`](plans/plan-fix-chunk-overlap-persian-legal.md) have been implemented and verified.

---

## What Changed

### Problem Summary

Chunks produced by the legal structural chunking pipeline had **no overlap between consecutive articles** (مواد). This was problematic for a RAG system on Persian legal texts because:
- A legal concept often spans across article boundaries
- Without overlap, a user query referencing a concept bridging two articles gets incomplete context
- Chunks showed broken words/sentences across chunk boundaries (e.g., Chunk #20 ending with `خواه` and Chunk #21 starting with `د. کرد.`)

### Root Causes Addressed

1. **`_chunk_legal()`** — Each article group became one chunk with no overlap from the next article
2. **`_split_by_chars()`** — Had zero overlap at all; simply did `start = end` with no rewind mechanism; split blindly at `max_chunk_size` without checking sentence boundaries
3. **`_split_long_article()` fallback** — When falling back to `_split_by_chars()` (no clauses found), no overlap parameter was passed

### Changes Made

#### File: [`src/backend/documents/services/chunking_service.py`](src/backend/documents/services/chunking_service.py)

| Change | Lines | Description |
|--------|-------|-------------|
| Added `legal_overlap_chars` param to `chunk_text()` | 143 | New parameter (default 150) for inter-article overlap |
| Passed `legal_overlap_chars` to `_chunk_legal()` | 193 | Wired through the call chain |
| Added `legal_overlap_chars` param to `_chunk_legal()` | 218 | New parameter accepted |
| **Inter-article overlap logic** in `_chunk_legal()` | 275-286 | After building each article chunk, appends trailing chars from the next article, trimmed to last space/newline boundary to avoid mid-word breaks |
| Added `overlap` param to `_split_long_article()` | 369 | New parameter (default 0) for character-based overlap fallback |
| Passed `overlap` to `_split_by_chars()` fallback | 411 | When no clauses found, passes overlap to the character-based splitter |
| **Rewrote `_split_by_chars()`** | 504-558 | Now uses `_find_split_point()` for space/sentence-boundary detection, falls back to `_find_sentence_boundary()`, and applies character-based overlap between sub-chunks |
| **Added `_find_sentence_boundary()`** | 784-821 | New static method that searches for sentence-ending characters (`.`, `!`, `?`, `؟`, `،`, `؛`) within a 400-char window around the preferred end point |

#### File: [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)

| Change | Lines | Description |
|--------|-------|-------------|
| Read `LEGAL_CHUNK_OVERLAP_CHARS` from settings | 609 | `getattr(settings, "LEGAL_CHUNK_OVERLAP_CHARS", 150)` |
| Pass `legal_overlap_chars` to `chunk_text()` | 618 | Wired through to the chunking service |

#### File: [`src/backend/documents/tests/test_chunking_service.py`](src/backend/documents/tests/test_chunking_service.py)

| Test Class | Tests | Description |
|------------|-------|-------------|
| `TestInterArticleOverlap` | 6 tests | `test_inter_article_overlap_appended`, `test_inter_article_overlap_zero`, `test_inter_article_overlap_metadata_preserved`, `test_last_article_no_overlap`, `test_single_article_no_inter_overlap`, `test_inter_article_overlap_trimmed_to_boundary` |
| `TestSplitByChars` | 4 tests | `test_split_by_chars_sentence_boundary`, `test_split_by_chars_with_overlap`, `test_split_by_chars_no_overlap_when_zero`, `test_split_by_chars_small_content_no_split` |
| `TestFindSentenceBoundary` | 4 tests | `test_finds_period_boundary`, `test_finds_persian_question_mark`, `test_no_boundary_returns_none`, `test_boundary_outside_range_returns_none` |

### Key Design Decisions

1. **Inter-article overlap is appended to the current chunk** — The overlap text from the next article is appended to the current chunk's content. This means the current chunk contains its own article PLUS a preview of the next article. The chunk's metadata (legal_type, legal_number) remains tied to the primary article.

2. **Overlap trimmed to last space/newline** — To avoid mid-word breaks, the overlap text is trimmed to the last space or newline boundary within the overlap window.

3. **`_split_by_chars()` reuses `_find_split_point()`** — The existing sentence-boundary detection logic is reused, with `_find_sentence_boundary()` as an additional fallback for cases where no standard boundary is found.

4. **`_find_sentence_boundary()` searches bidirectionally** — It looks for sentence-ending characters in a window of `[preferred_end - 200, preferred_end + 200]`, finding the closest boundary to the preferred end point, accepting it only if within 300 characters.

### Test Results

**38 passed, 0 failed** — All existing tests plus 14 new tests pass successfully.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `LEGAL_CHUNK_OVERLAP_CHARS` | `150` | Number of characters from the next article to append as overlap (~30-40 Persian words) |

### Files Modified

- `src/backend/documents/services/chunking_service.py` — Core changes (inter-article overlap, `_split_by_chars()` rewrite, `_find_sentence_boundary()`)
- `src/backend/documents/tasks/document_processing.py` — Pass new setting to chunking service
- `src/backend/documents/tests/test_chunking_service.py` — 14 new test cases

---

## Rollback Plan

If any change causes regression:

1. **Chunking service**: Revert `src/backend/documents/services/chunking_service.py` — remove `legal_overlap_chars` param from `chunk_text()` and `_chunk_legal()`, remove inter-article overlap logic in `_chunk_legal()`, restore original `_split_by_chars()`, remove `_find_sentence_boundary()`, remove `overlap` param from `_split_long_article()`
2. **Task file**: Revert `src/backend/documents/tasks/document_processing.py` — remove `legal_overlap_chars` reading and passing
3. **Tests**: Remove `TestInterArticleOverlap`, `TestSplitByChars`, `TestFindSentenceBoundary` test classes
