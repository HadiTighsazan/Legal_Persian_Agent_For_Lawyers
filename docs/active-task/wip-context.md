# WIP Context — RAG Retrieval Diagnosis Sprint (3 Tasks + Arabic Char Fix + User Query Normalization)

## Status: ✅ COMPLETED (2026-05-06)

All 3 tasks from the RAG Retrieval Diagnosis plan have been implemented, plus Arabic character normalization fixes at multiple layers. See [`plans/plan-diagnose-rag-retrieval-issues.md`](plans/plan-diagnose-rag-retrieval-issues.md) for the full diagnosis and rationale, and [`plans/plan-fix-persian-arabic-char-network-error.md`](plans/plan-fix-persian-arabic-char-network-error.md) for the user query normalization fix plan.

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

**2a. [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py:200)**
- Changed default `top_k` from `5` to `15` in `run_rag_query()` function signature.
- Changed default `top_k` from `5` to `15` in `run_rag_query_stream()` function signature.

**2b. [`src/backend/conversations/views.py`](src/backend/conversations/views.py:348)**
- Fixed `ConversationMessageView.post()` — changed hardcoded `top_k=5` to `top_k=15`.

**2c. [`src/backend/conversations/views.py`](src/backend/conversations/views.py:458)**
- Fixed `ConversationMessageStreamView.post()` — changed hardcoded `top_k=5` to `top_k=15`.

**2d. [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py:227)**
- Fixed `DirectQuerySerializer` — changed default `top_k` from `5` to `15`.

### Acceptance Criteria
- [x] `top_k` default is changed to 15 in all code paths
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

## Task 4: Arabic → Persian Character Normalization in `normalize_for_fts()` (HIGH)

### Problem
PDFs often encode Persian text using Arabic glyph variants (Arabic Yeh `ي` U+064A instead of Persian Yeh `ی` U+06CC, Arabic Kaf `ك` U+0643 instead of Persian Kaf `ک` U+06A9). This causes Ctrl+F to fail to find words like "جایز" in the PDF even though they visually exist, and also causes FTS mismatches.

### Changes

**4a. [`src/backend/documents/services/persian_normalizer.py`](src/backend/documents/services/persian_normalizer.py:39)**
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

## Task 5: Normalize Arabic→Persian Chars in User Queries (CRITICAL)

### Problem
When a user asks a Persian question containing Arabic character variants (Yeh `ي` U+064A or Kaf `ك` U+0643), the LLM query formulation call can fail, resulting in a **"Network Error"** on the frontend. The [`PersianNormalizer`](src/backend/documents/services/persian_normalizer.py:77) already normalizes these characters for chunk content, but the normalization was **NOT applied to user queries** before they're sent to the LLM.

The specific failing query was: **"عقد جایز و لازم چه تفاوتی دارند؟"**

### Changes

**5a. [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py:38)**
- Added import: `from documents.services.persian_normalizer import PersianNormalizer`

**5b. [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py:153)**
- Added Arabic→Persian character normalization at the **start** of `formulate_query()`, **before** the short-circuit checks and the LLM call.
- Uses `str.maketrans()` to convert Arabic Yeh (U+064A) → Persian Yeh (U+06CC) and Arabic Kaf (U+0643) → Persian Kaf (U+06A9).
- This ensures the LLM receives clean Persian text and produces reliable JSON output.

**5c. [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py:202)**
- Added `validate_content()` method to `AskQuestionSerializer` that normalizes Arabic→Persian characters at the input validation layer.
- Provides **defense-in-depth**: every query is normalized at the earliest possible point, regardless of which code path processes it.

### Why Two Layers?
- **Fix 1 (query_formulation.py)**: Catches the issue right before the LLM call, which is the direct root cause of the "Network Error".
- **Fix 2 (serializers.py)**: Normalizes at the API input layer, ensuring all downstream code receives clean Persian text. This protects against future code paths that might bypass `formulate_query()`.

### Acceptance Criteria
- [x] Arabic Yeh/Kaf in user queries are normalized before LLM formulation call
- [x] Arabic Yeh/Kaf in user queries are normalized at the serializer validation layer
- [x] The failing query `"عقد جایز و لازم چه تفاوتی دارند؟"` no longer produces "Network Error"
- [x] Previously working queries (`"hi"`, `"سند در مورد چیه"`) continue to work

---

## Task 6: Fix Docker DNS Resolution & Chat Provider Timeouts (CRITICAL)

### Problem (Discovered via Log Analysis)
After deploying the character normalization fixes, the "Network Error" persisted. Log analysis revealed the **real root cause**:

1. **Docker DNS resolution failure**: The Docker container cannot resolve `api.deepseek.com` (the configured chat provider). The host machine resolves it fine, but Docker's internal DNS on Windows fails.
   - `httpcore.ConnectError: [Errno -3] Temporary failure in name resolution`

2. **No timeout on OpenAI HTTP client**: The OpenAI Python SDK's default HTTP client has **no connect timeout**. When DNS resolution fails, the client retries with exponential backoff indefinitely, causing the Gunicorn worker to hang until the 30-second worker timeout kills it (SIGKILL/OOM).

3. **`top_k=5` hardcoded in views**: Despite `rag_service.py` having `top_k=15` as default, the views were passing `top_k=5` explicitly, overriding the default.

### Changes

**6a. [`docker-compose.yml`](docker-compose.yml:73) — Fix Docker DNS**
- Added `dns: [8.8.8.8, 8.8.4.4]` to `backend`, `celery_worker`, and `celery_beat` services.
- Google Public DNS provides reliable external name resolution from within Docker containers on Windows.

**6b. [`src/backend/providers/openai_chat.py`](src/backend/providers/openai_chat.py:25) — Add HTTP timeouts**
- Configured the OpenAI HTTP client with explicit `httpx.Timeout`:
  - `connect=10.0s` — Fail fast if DNS/connection fails
  - `read=30.0s` — Max wait for response
  - `write=30.0s` — Max time to send request
  - `pool=10.0s` — Max wait for connection pool
- Prevents worker processes from hanging indefinitely on network failures.

**6c. [`src/backend/conversations/views.py`](src/backend/conversations/views.py:348,458) — Fix hardcoded `top_k`**
- Changed `top_k=5` to `top_k=15` in both `ConversationMessageView.post()` and `ConversationMessageStreamView.post()`.

**6d. [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py:227) — Fix `DirectQuerySerializer` default**
- Changed `DirectQuerySerializer.top_k` default from `5` to `15`.

### Acceptance Criteria
- [x] Docker containers can resolve `api.deepseek.com` via Google DNS
- [x] OpenAI HTTP client has explicit connect/read/write/pool timeouts
- [x] `top_k=15` is used consistently across all code paths
- [x] No more worker timeouts or OOM kills due to hanging API calls

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
| 7 | [`src/backend/conversations/query_formulation.py`](src/backend/conversations/query_formulation.py) | Add Arabic→Persian normalization before LLM call in `formulate_query()` | CRITICAL |
| 8 | [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) | Add `validate_content()` to `AskQuestionSerializer` for input-layer normalization | CRITICAL |
| 9 | [`docker-compose.yml`](docker-compose.yml) | Add Google DNS (8.8.8.8, 8.8.4.4) to backend, celery_worker, celery_beat | CRITICAL |
| 10 | [`src/backend/providers/openai_chat.py`](src/backend/providers/openai_chat.py) | Add HTTP timeouts (connect=10s, read/write=30s, pool=10s) to OpenAI client | CRITICAL |
| 11 | [`src/backend/conversations/views.py`](src/backend/conversations/views.py) | Fix hardcoded `top_k=5` → `top_k=15` in both message views | HIGH |
| 12 | [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) | Fix `DirectQuerySerializer` default `top_k=5` → `top_k=15` | HIGH |
| 13 | [`docs/references/database-schema.md`](docs/references/database-schema.md) | Added migration 0009 note + trigger normalization warning | DOCS |

---

## Next Steps / Verification

1. **Restart the containers** to apply DNS and code changes:
   ```
   docker-compose down
   docker-compose up -d
   ```
2. **Verify DNS resolution** from inside the container:
   ```
   docker-compose exec backend python -c "import socket; print(socket.gethostbyname('api.deepseek.com'))"
   ```
3. **Test the failing query** — ask `"عقد جایز و لازم چه تفاوتی دارند؟"` and verify it no longer produces "Network Error"
4. **Test comparative query** — ask `"فرق بین عقد لازم و عقد جایز چیست؟"` and verify both concepts appear in sources
5. **Test simple queries** — verify `"hi"` and `"سند در مورد چیه"` still work
6. **Test Arabic Yeh/Kaf** — upload a PDF where "جایز" is encoded with Arabic Yeh and verify Ctrl+F can find it
7. **Monitor logs** — check for FTS matches in the hybrid search logs
