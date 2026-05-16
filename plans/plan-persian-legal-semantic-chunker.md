# Plan: Semantic Chunking Refactor for Persian Legal PDFs

## Problem Summary

The current [`AnchorChunkingService`](src/backend/documents/services/anchor_chunking_service.py) has these issues when chunking Persian legal PDFs:

1. **Token-based splitting breaks mid-sentence/mid-word** — [`_token_overlap_split`](src/backend/documents/services/anchor_chunking_service.py:469) splits at arbitrary token boundaries, producing chunks like `"ه تحقق از ارکان ب"` (12 tokens, broken mid-word).
2. **Content repetition** — The overlap mechanism (`overlap_tokens=50`) re-encodes overlapping tokens via tiktoken, which can produce garbled overlap text that repeats content awkwardly.
3. **Lost context** — Related legal sections (e.g., court verdict vs. minutes) get mixed or separated without proper section tracking.
4. **Imbalanced chunk sizes** — No minimum size enforcement, producing chunks as small as 12 tokens alongside 400-token chunks.
5. **No sentence boundary awareness** — The splitter doesn't respect Persian sentence boundaries (`.` , `:` , `\n\n`).

## Proposed Solution: `PersianLegalChunker`

Replace the current `AnchorChunkingService` with a new `PersianLegalChunker` that implements **semantic chunking** specifically designed for Persian legal document structure.

### Architecture Overview

```mermaid
flowchart TD
    A[Extracted Text with [PAGE N] markers] --> B[PersianLegalChunker.chunk_text]
    
    B --> C[1. Clean Page Markers & Normalize]
    C --> D[2. Structural Segmentation via Primary Anchors]
    
    D --> E{Primary anchors found?}
    E -->|Yes| F[Split into structural sections]
    E -->|No| G[Fallback: sentence-based split]
    
    F --> H[For each section:]
    H --> I{Section length check}
    I -->|Under min_tokens| J[Merge with next section]
    I -->|Over max_tokens| K[Sentence-aware split with secondary anchor hints]
    I -->|Within range| L[Keep as single chunk]
    
    K --> M[Split by sentence boundaries]
    M --> N[Accumulate sentences until max_tokens]
    N --> O[Apply intelligent overlap at sentence boundaries]
    O --> P[Check secondary anchors for chunk boundaries]
    
    J --> Q[Attach metadata: section_type, pages, anchor_text, etc.]
    L --> Q
    P --> Q
    
    G --> R[Sentence-based fallback split]
    R --> Q
    
    Q --> S[Return List[AnchorChunk]]
```

### Key Design Decisions

#### 1. Two-Tier Anchor System (Primary + Secondary)

**Primary anchors** create new structural sections:

```python
PRIMARY_ANCHORS = [
    # Court ruling sections
    r"ر[أا]ی[\\s‌]+دادگاه",
    r"دادنامه",
    r"قرار[\\s‌]+دادگاه",
    
    # Case flow
    r"گردشکار",
    r"گردش[\\s‌]+کار",
    r"خلاصه[\\s‌]+گردشکار",
    
    # Proceedings
    r"صورت[\\s‌]*جلسه",
    r"صورت[\\s‌]*مجلس",
    r"جلسه[\\s‌]+رسیدگی",
    r"ختم[\\s‌]+دادرسی",
    r"ختم[\\s‌]+جلسه",
    
    # Legal opinions
    r"نظریه[\\s‌]+مشورتی",
    r"نظریه[\\s‌]+تفسیری",
    
    # Case details
    r"در[\\s‌]+خصوص[\\s‌]+دعوی",
    r"در[\\s‌]+خصوص[\\s‌]+دادخواست",
    r"شرح[\\s‌]+شکایت",
    r"شرح[\\s‌]+دادخواست",
    r"دفاعیات",
    r"دفاعیات[\\s‌]+خوانده",
    r"دفاعیات[\\s‌]+وکیل",
    
    # Document headers
    r"بسمه[\\s‌]+تعالی",
    r"بسم[\\s‌]+الله[\\s‌]+الرحمن[\\s‌]+الرحیم",
    
    # Legislation structure
    r"ماده[\\s‌]*\\d+",
    r"فصل[\\s‌]*\\d+",
    r"بخش[\\s‌]*\\d+",
    r"تبصره[\\s‌]*\\d+",
]
```

**Secondary anchors** are chunk-boundary hints (not section boundaries):

```python
CHUNK_BOUNDARY_HINTS = [
    r"مستنداً[\\s‌]+به[\\s‌]+مواد",
    r"لذا[\\s‌]+دادگاه",
    r"دادگاه[\\s‌]+با[\\s‌]+توجه[\\s‌]+به",
    r"محکوم[\\s‌]+می‌نماید",
    r"حکم[\\s‌]+به",
]
```

Logic:
- **PRIMARY** → creates a new section
- **SECONDARY** → if current chunk > `min_tokens`, close the chunk and start a new one within the same section

#### 2. Flexible Whitespace Handling for Persian Text

PDF extraction produces inconsistent spacing. All anchor regexes use `[\\s‌]*` (space + ZWNJ) instead of fixed whitespace:

| Pattern | Matches |
|---------|---------|
| `r"صورت[\\s‌]*جلسه"` | صورتجلسه, صورت جلسه, صورت‌جلسه |
| `r"ر[أا]ی[\\s‌]+دادگاه"` | رأی دادگاه, رای دادگاه, رأی‌دادگاه |
| `r"ماده[\\s‌]*\\d+"` | ماده۱, ماده ۱, ماده‌۱ |

#### 3. Sentence-Aware Splitting (Not Token-Aware)

Replace [`_token_overlap_split`](src/backend/documents/services/anchor_chunking_service.py:469) with a sentence-aware splitter:

```python
# Compiled once in __init__
self._sentence_pattern = re.compile(
    r'(?<!\d)[\.؟!](?!\d)|'     # Period/question/exclamation not between digits
    r'\:\s|'                     # Colon followed by space
    r'\n{2,}'                    # Double newline (paragraph)
)
```

This handles:
- Persian periods `.` (not in numbers like `1.2`)
- Persian question mark `؟`
- Exclamation `!`
- Colon `:` (common in legal: `ماده ۱:`)
- Date slashes `/` are NOT split (negative lookbehind/lookahead for digits)
- English periods in `v.` or `Co.` are NOT split (context-dependent)

#### 4. Minimum Chunk Size Enforcement

Add `min_chunk_tokens` parameter (default: 150 tokens).

- If a chunk is below `min_tokens` AND it's the **last chunk in a section** → merge with previous chunk (even if it slightly exceeds `max_tokens`)
- If a chunk is below `min_tokens` AND it's **not the last** → merge with next chunk
- This eliminates the 12-token chunk problem

#### 5. Intelligent Overlap at Sentence Boundaries

Instead of raw token overlap (which causes garbled repetition), overlap is applied at **sentence boundaries**:
- The last `overlap_sentences` (default: 1) sentences of chunk N become the first sentences of chunk N+1
- This ensures overlap is always clean, readable Persian text

#### 6. Page Marker Cleanup Before Chunking

Strip `[PAGE N]` markers from chunk content and store page numbers in metadata only. This prevents embedding noise from page markers.

#### 7. Rich Metadata for RAG Enhancement

```python
@dataclass
class AnchorChunk:
    content: str
    pages: List[int]
    char_count: int
    token_count: int
    metadata: dict = field(default_factory=dict)
    section_title: Optional[str] = None
    
    # NEW metadata fields:
    # metadata = {
    #     "section_type": "verdict",       # verdict/minutes/opinion/etc.
    #     "anchor_text": "رأی دادگاه",      # The matched anchor text
    #     "sentence_count": 12,             # Number of sentences
    #     "has_verdict": True,              # Contains "محکوم می‌نماید"
    #     "has_legislation_ref": True,      # Contains "ماده \d+"
    #     "legislation_refs": ["ماده ۱۲۳"], # Extracted article references
    #     "start_page": 1,                  # First page of chunk
    #     "end_page": 2,                    # Last page of chunk
    # }
```

This metadata enables **hybrid search** (keyword + semantic) and smarter RAG retrieval.

#### 8. Persian Normalization Before Chunking

Before any regex matching, apply lightweight normalization:
- `ي` → `ی` (Arabic Yeh → Persian Yeh)
- `ك` → `ک` (Arabic Kaf → Persian Kaf)
- `أ` `إ` `آ` → `ا` (Alef variants → plain Alef)
- Remove ZWNJ/ZWNJ artifacts
- Collapse excessive whitespace

This ensures anchor regexes match regardless of PDF extraction quality.

### Changes Required

#### Files to Create

| File | Description |
|------|-------------|
| [`src/backend/documents/services/persian_legal_chunker.py`](src/backend/documents/services/persian_legal_chunker.py) | **NEW** — The `PersianLegalChunker` class with semantic chunking logic |
| [`src/backend/documents/tests/test_persian_legal_chunker.py`](src/backend/documents/tests/test_persian_legal_chunker.py) | **NEW** — Comprehensive tests for the new chunker |

#### Files to Modify

| File | Change |
|------|--------|
| [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) | Change import from `AnchorChunkingService` to `PersianLegalChunker` in [`chunk_document`](src/backend/documents/tasks/document_processing.py:1182) |
| [`src/backend/config/settings.py`](src/backend/config/settings.py:397) | Add new settings: `PERSIAN_LEGAL_CHUNKER_ENABLED`, `MIN_CHUNK_TOKENS`, `MAX_CHUNK_TOKENS`, `OVERLAP_SENTENCES` |
| [`docs/references/database-schema.md`](docs/references/database-schema.md) | No schema changes needed (same `AnchorChunk` dataclass output) |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | No API changes needed |

#### Files to Keep Unchanged

- [`src/backend/documents/services/anchor_chunking_service.py`](src/backend/documents/services/anchor_chunking_service.py) — The old service stays for backward compatibility
- [`src/backend/documents/tests/test_anchor_chunking_service.py`](src/backend/documents/tests/test_anchor_chunking_service.py) — Existing tests remain valid

### Detailed Implementation Steps

#### Step 1: Create `PersianLegalChunker` class

Create [`src/backend/documents/services/persian_legal_chunker.py`](src/backend/documents/services/persian_legal_chunker.py) with:

**Constants:**
- `PRIMARY_ANCHORS` — List of regex patterns for structural section boundaries
- `CHUNK_BOUNDARY_HINTS` — List of regex patterns for chunk-level boundaries
- `SECTION_TYPE_MAP` — Mapping from anchor patterns to section type strings
- `_PAGE_MARKER_RE` — Regex for `[PAGE N]` markers
- `_ENCODING_NAME` — `"cl100k_base"` for tiktoken

**`__init__(self, min_chunk_tokens=150, max_chunk_tokens=400, overlap_sentences=1)`:**
- Compile all regex patterns once for performance
- Initialize tiktoken encoding

**`chunk_text(self, text, chunk_tokens=400, overlap_tokens=50) -> List[AnchorChunk]`:**
- Same signature as `AnchorChunkingService.chunk_text` for drop-in replacement
- `chunk_tokens` maps to `max_chunk_tokens`
- `overlap_tokens` is ignored (replaced by `overlap_sentences`), kept for API compatibility

**Internal methods:**
- `_clean_page_markers(text)` → `(cleaned_text, page_map)`
- `_normalize_persian(text)` → normalized text
- `_detect_section_boundaries(text)` → list of `{start, end, anchor_text, section_type}`
- `_split_by_sentences(text)` → list of sentences
- `_merge_small_chunks(sentences, min_tokens)` → merged sentence groups
- `_split_large_section(sentences, max_tokens, overlap)` → sentence-aware split with overlap
- `_apply_secondary_hints(chunks, text)` → split chunks at secondary anchor boundaries
- `_detect_section_type(anchor_text)` → section type string
- `_extract_legislation_refs(text)` → list of article references
- `_build_metadata(chunk_text, section_type, anchor_text, pages)` → metadata dict

#### Step 2: Create comprehensive tests

Create [`src/backend/documents/tests/test_persian_legal_chunker.py`](src/backend/documents/tests/test_persian_legal_chunker.py) with:

**`TestStructuralSegmentation`** (10+ tests):
- `test_verdict_section_detected` — "رأی دادگاه" creates a verdict section
- `test_minutes_section_detected` — "صورتجلسه" / "صورت جلسه" / "صورت‌جلسه" all match
- `test_multiple_anchors_create_sections` — Multiple anchors create multiple sections
- `test_no_anchors_fallback` — No anchors → sentence-based split
- `test_anchor_at_text_start` — No intro section when anchor is at position 0
- `test_consecutive_anchors` — Empty sections between consecutive anchors are skipped
- `test_expanded_anchor_list` — All new anchors are recognized
- `test_section_type_mapping` — Each anchor maps to correct section_type
- `test_secondary_anchor_creates_chunk_boundary` — Secondary anchors split within section
- `test_whitespace_variations_in_anchors` — Flexible whitespace matching

**`TestSentenceAwareChunking`** (10+ tests):
- `test_sentence_boundary_respected` — Chunks never break mid-sentence
- `test_persian_period_boundary` — Persian period `.` is a valid boundary
- `test_colon_boundary` — Colon `:` is a valid boundary
- `test_double_newline_boundary` — `\n\n` is a valid boundary
- `test_number_period_not_boundary` — `1.2` (number) is NOT a boundary
- `test_date_slash_not_boundary` — `۱۴۰۲/۰۵/۱۵` is NOT split
- `test_mixed_rtl_ltr_no_break` — `Smith v. Jones` is NOT split
- `test_sentence_accumulation` — Sentences accumulate until max_tokens
- `test_no_mid_word_break` — No chunk contains a broken word like `"ه تحقق"`
- `test_empty_text` — Empty text → empty list

**`TestMinChunkSize`** (6+ tests):
- `test_small_chunk_merged_with_next` — Chunk below min_tokens is merged with next
- `test_last_small_chunk_merged_with_previous` — Last small chunk merges backward
- `test_chunk_at_min_size_kept` — Chunk exactly at min_tokens is kept
- `test_very_small_chunks_merged_into_one` — Multiple tiny chunks merge into one
- `test_single_sentence_below_min` — Single short sentence is still kept (can't merge further)
- `test_min_chunk_configurable` — min_chunk_tokens parameter works

**`TestIntelligentOverlap`** (5+ tests):
- `test_overlap_at_sentence_boundary` — Overlap is at sentence boundary, not token boundary
- `test_overlap_sentences_count` — Correct number of sentences overlap
- `test_no_garbled_overlap` — Overlap text is clean, readable Persian
- `test_overlap_configurable` — overlap_sentences parameter works
- `test_no_content_repetition_in_middle` — Only overlap region repeats, not random content

**`TestPageTracking`** (5+ tests):
- `test_page_markers_removed_from_content` — `[PAGE N]` not in chunk content
- `test_page_numbers_in_metadata` — Page numbers stored in metadata
- `test_multi_page_chunk` — Chunk spanning pages 1-3 has pages=[1,2,3]
- `test_page_tracking_with_anchors` — Anchored sections track correct pages
- `test_start_end_page_in_metadata` — start_page and end_page in metadata

**`TestMetadataEnrichment`** (6+ tests):
- `test_section_type_in_metadata` — section_type is correctly set
- `test_anchor_text_in_metadata` — anchor_text is correctly set
- `test_sentence_count_in_metadata` — sentence_count is accurate
- `test_has_verdict_detected` — has_verdict=True when verdict language present
- `test_legislation_refs_extracted` — legislation_refs contains article references
- `test_metadata_not_in_content` — Metadata values not injected into content

**`TestEdgeCases`** (8+ tests):
- `test_mixed_numerals` — Persian/Arabic/English numerals in anchors
- `test_very_long_text` — Very long text split correctly
- `test_whitespace_only` — Whitespace-only → empty list
- `test_token_count_accuracy` — Token count is accurate
- `test_realistic_legal_document` — Full realistic Persian legal document
- `test_no_broken_words` — CRITICAL: no chunk contains partial words
- `test_balanced_chunk_sizes` — All chunks between min_tokens and max_tokens*1.2
- `test_arabic_chars_normalized` — Arabic Yeh/Kaf normalized before matching

#### Step 3: Update `chunk_document` task

In [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py):

1. Add import: `from documents.services.persian_legal_chunker import PersianLegalChunker`
2. In [`chunk_document`](src/backend/documents/tasks/document_processing.py:1182), add a settings check:
   ```python
   if getattr(settings, "PERSIAN_LEGAL_CHUNKER_ENABLED", True):
       chunker = PersianLegalChunker(
           min_chunk_tokens=getattr(settings, "MIN_CHUNK_TOKENS", 150),
           max_chunk_tokens=chunk_tokens,
           overlap_sentences=getattr(settings, "OVERLAP_SENTENCES", 1),
       )
   else:
       chunker = AnchorChunkingService()
   ```

#### Step 4: Update settings

In [`src/backend/config/settings.py`](src/backend/config/settings.py:397), add:

```python
# ---------------------------------------------------------------------------
# Persian Legal Chunker settings (replaces AnchorChunkingService)
# ---------------------------------------------------------------------------
PERSIAN_LEGAL_CHUNKER_ENABLED = True
MIN_CHUNK_TOKENS = 150
MAX_CHUNK_TOKENS = 400  # Same as ANCHOR_CHUNK_TOKENS
OVERLAP_SENTENCES = 1
```

#### Step 5: Run tests and verify

1. Run existing tests: `docker-compose exec backend pytest documents/tests/test_anchor_chunking_service.py -v`
2. Run new tests: `docker-compose exec backend pytest documents/tests/test_persian_legal_chunker.py -v`
3. Run full test suite: `docker-compose exec backend pytest -v`
4. Upload a real Persian legal PDF and verify chunk quality via the monitoring page

### Migration Strategy

The new `PersianLegalChunker` is a **drop-in replacement** for `AnchorChunkingService`:
- Same input: `(text: str, chunk_tokens: int, overlap_tokens: int)`
- Same output: `List[AnchorChunk]`
- Same `AnchorChunk` dataclass

This means:
- No database migrations needed
- No API changes needed
- No frontend changes needed
- Existing documents are unaffected (they keep their old chunks)
- Only **new uploads** use the new chunker

The old `AnchorChunkingService` is kept in the codebase (not deleted) for:
- Backward compatibility (via `PERSIAN_LEGAL_CHUNKER_ENABLED = False`)
- Reference during the transition period

### Test Scenarios

#### Scenario 1: Realistic Persian Court Ruling (Page 8 example)

**Input**: Text from page 8 of a court ruling containing:
- "رأی دادگاه" section with verdict text
- "صورتجلسه" section with plaintiff/defendant statements

**Expected Output**:
- Chunk 1: `section_type="verdict"` — Full verdict text (~300 tokens)
- Chunk 2: `section_type="minutes"` — Plaintiff statements (~250 tokens)
- Chunk 3: `section_type="minutes"` — Defendant statements (~200 tokens)

**Not** 8 broken chunks with mid-word cuts and content repetition.

#### Scenario 2: Document Without Legal Anchors

**Input**: A general Persian text PDF with no legal section markers.

**Expected Output**:
- Sentence-based chunks, each 150-400 tokens
- No mid-sentence breaks
- Clean overlap at sentence boundaries

#### Scenario 3: Very Long Single Section

**Input**: A "گردشکار" section that is 2000 tokens long.

**Expected Output**:
- Multiple chunks, each 150-400 tokens
- Each chunk ends at a sentence boundary
- 1-sentence overlap between consecutive chunks
- All chunks have `section_type="proceedings"`

#### Scenario 4: Mixed RTL/LTR Content

**Input**: Text containing `Smith v. Jones`, `Article 123`, and Persian legal text.

**Expected Output**:
- `Smith v. Jones` is NOT split by the period
- `Article 123` is NOT split
- Persian sentences are correctly split at `.` and `:`
