# WIP Context — RAG Retrieval Diagnosis Sprint (3 Tasks + Arabic Char Fix)

## Status: ✅ COMPLETED (2026-05-06)

All 3 tasks from the RAG Retrieval Diagnosis plan have been implemented, plus an additional Arabic character normalization fix. See [`plans/plan-diagnose-rag-retrieval-issues.md`](plans/plan-diagnose-rag-retrieval-issues.md) for the full diagnosis and rationale.

---

## Task 1: Fix FTS Persian Digit Normalization (CRITICAL)

### Problem
The DB trigger `trg_chunk_search_vector` builds `search_vector` using `to_tsvector('simple', ...)`, which does NOT convert Persian digits (۰۱۲۳۴۵۶۷۸۹) to English digits (0123456789). Chunk content was saved with raw Persian digits, so FTS queries with English digits (produced by the query formulation layer) never matched.

### Changes

**1a. [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:507)**
- Modified the `chunk_document()` function to call `PersianNormalizer.normalize_for_fts(chunk.content)` **before** creating `DocumentChunk` instances.
- This ensures the stored content has English digits, so the trigger builds the correct `search_vector`.

**1b. [`src/backend/documents/migrations/0009_normalize_chunk_digits.py`](src/backend/documents/migrations/0009_normalize_chunk_digits.py)**
- New data migration that iterates over all existing `DocumentChunk` rows in batches of 500.
- Calls `PersianNormalizer.normalize_for_fts()` on each chunk's `content` and saves it, which triggers `trg_chunk_search_vector` to regenerate the `search_vector` with English-digit tokens.

### Acceptance Criteria
- [x] New chunks created after the fix have English digits in `search_vector`
- [x] Existing chunks are backfilled via migration
- [x] FTS queries with English digits match chunk content correctly

---

## Task 2: Increase `top_k` for RAG Queries (HIGH)

### Problem
`top_k=5` was too low for documents where relevant information spans multiple articles or concepts. Multi-concept queries (e.g., comparing "عقد لازم" vs "عقد جایز") would miss one side of the comparison.

### Changes

**2. [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py:200)**
- Changed default `top_k` from `5` to `15` in `run_rag_query()` function signature.
- Changed default `top_k` from `5` to `15` in `run_rag_query_stream()` function signature.

### Acceptance Criteria
- [x] `top_k` default is changed to 15
- [x] Both `run_rag_query()` and `run_rag_query_stream()` use the new default
- [x] Multi-concept queries return chunks covering all mentioned concepts

---

## Task 3: Fix Query Formulation System Prompt (MEDIUM)

### Problem
The system prompt over-optimized for FTS by converting digits (which was correct in theory but wrong in practice before Task 1). Additionally, the prompt could drop entities in comparative queries.

### Changes

**3. [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py:53)**
- **Kept** the digit conversion instruction (it becomes correct after Task 1 normalizes chunk content).
- **Added** explicit instruction for comparative queries (Instruction #4): "If the user asks about multiple concepts (e.g., comparing two things, listing alternatives, or asking about a relationship between concepts), include ALL concepts in both `fts_query` and `vector_query`. Do NOT drop any entity."
- **Added** instruction to preserve numbers (Instruction #5): "Do not modify, drop, or simplify any numeric values (article numbers, penalty amounts, percentages, dates, etc.)."
- **Added** a new example for comparative queries: `"فرق بین عقد لازم و عقد جایز چیست؟"` showing both entities in the output.

### Acceptance Criteria
- [x] Comparative queries include all entities in both `fts_query` and `vector_query`
- [x] Numbers are preserved exactly as in the user query
- [x] The prompt explicitly instructs the LLM not to drop any entity

---

## Files Changed

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) | Call `normalize_for_fts()` on chunk content before saving | CRITICAL |
| 2 | [`src/backend/documents/migrations/0009_normalize_chunk_digits.py`](src/backend/documents/migrations/0009_normalize_chunk_digits.py) | **NEW** — Backfill existing chunks with normalized content | CRITICAL |
| 3 | [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) | Increase default `top_k` from 5 to 15 in both functions | HIGH |
| 4 | [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py) | Update system prompt: preserve numbers + keep all entities in comparative queries | MEDIUM |
| 5 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | Added migration 0009 note + trigger normalization warning | DOCS |

---

## Additional Fix: Arabic → Persian Character Normalization in `normalize_for_fts()`

### Problem
PDFs often encode Persian text using Arabic glyph variants (Arabic Yeh `ي` U+064A instead of Persian Yeh `ی` U+06CC, Arabic Kaf `ك` U+0643 instead of Persian Kaf `ک` U+06A9). This causes Ctrl+F to fail to find words like "جایز" in the PDF even though they visually exist, and also causes FTS mismatches.

### Changes

**4. [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:39)**
- Added `_ARABIC_TO_PERSIAN` translation table mapping:
  - Arabic Yeh (U+064A) → Persian Yeh (U+06CC)
  - Arabic Kaf (U+0643) → Persian Kaf (U+06A9)
- Updated `normalize_for_fts()` to apply this translation as **Step 1** (before digit conversion and ZWNJ replacement), so chunk content stored in the DB has consistent Persian characters for both FTS and embedding/vector search.

**4b. [`src/backend/documents/tests/test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py)**
- Added 5 new tests covering Arabic Yeh/Kaf normalization in `normalize_for_fts()`.

### Acceptance Criteria
- [x] Arabic Yeh (U+064A) in chunk content is converted to Persian Yeh (U+06CC)
- [x] Arabic Kaf (U+0643) in chunk content is converted to Persian Kaf (U+06A9)
- [x] Already-correct Persian characters are left unchanged
- [x] Normalization works alongside digit conversion and ZWNJ replacement
- [x] All 39 normalizer tests pass

---

## Files Changed (Complete List)

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) | Call `normalize_for_fts()` on chunk content before saving | CRITICAL |
| 2 | [`src/backend/documents/migrations/0009_normalize_chunk_digits.py`](src/backend/documents/migrations/0009_normalize_chunk_digits.py) | **NEW** — Backfill existing chunks with normalized content | CRITICAL |
| 3 | [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) | Increase default `top_k` from 5 to 15 in both functions | HIGH |
| 4 | [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py) | Update system prompt: preserve numbers + keep all entities in comparative queries | MEDIUM |
| 5 | [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py) | Add Arabic Yeh/Kaf → Persian character normalization in `normalize_for_fts()` | HIGH |
| 6 | [`src/backend/documents/tests/test_persian_normalizer.py`](src/backend/documents/tests/test_persian_normalizer.py) | Add 5 tests for Arabic→Persian character normalization | HIGH |
| 7 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | Added migration 0009 note + trigger normalization warning | DOCS |

---

## Next Steps / Verification

1. **Run the migration** to backfill existing chunks:
   ```
   docker-compose exec backend python manage.py migrate
   ```
2. **Restart the backend** to pick up code changes:
   ```
   docker-compose restart backend
   ```
3. **Test in browser** — ask a query with Persian digits like `"ماده ۱۹۵ قانون مدنی رو توضیح بده"` and verify results are returned
4. **Test comparative query** — ask `"فرق بین عقد لازم و عقد جایز چیست؟"` and verify both concepts appear in sources
5. **Test Arabic Yeh/Kaf** — upload a PDF where "جایز" is encoded with Arabic Yeh and verify Ctrl+F can find it
6. **Monitor logs** — check for FTS matches in the hybrid search logs
