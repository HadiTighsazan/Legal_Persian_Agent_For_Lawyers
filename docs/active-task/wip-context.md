# WIP Context — Strategist RAG Retrieval Fix (Steps 1-5) + max_tokens Fix

## What Was Just Completed

### Step 1: Rewrote `_build_case_description` (Root Cause #1 fix)

**File:** [`src/backend/conversations/strategist_service.py:757`](src/backend/conversations/strategist_service.py:757)

Replaced the JSON-dump implementation with a fluent Persian natural language legal description generator.

**Changes:**
- Added `case_type_labels` mapping (e.g., `contract_dispute` → `اختلافات قراردادی`)
- Extracts known fields in order: `parties`, `claims`, `amount`, `timeline`, `jurisdiction`, `evidence`, `current_status`
- Formats `amount` with comma separators for readability (e.g., `۶۰,۰۰۰,۰۰۰ تومان`)
- Handles `parties` as both `dict` and `str`
- Any remaining unknown keys are appended as `key: value` strings
- All parts joined with ` | ` separator

**Example output:**
```
پرونده اختلافات قراردادی | طرفین دعوا: موجر: کاربر و مستاجر: نامشخص | خواسته: عدم پرداخت اجاره و تخلیه | مبلغ: ۶۰,۰۰۰,۰۰۰ تومان | زمان‌بندی: قرارداد یک‌ساله از ۱۴۰۳/۰۳/۰۱ تا ۱۴۰۴/۰۳/۰۱ | مرجع قضایی: تهران | ادله و مدارک: قرارداد کتبی عادی
```

### Step 2: Added `_filter_relevant_chunks` (Root Cause #2 fix)

**File:** [`src/backend/conversations/strategist_service.py:765`](src/backend/conversations/strategist_service.py:765)

Added a new method that filters retrieved chunks by relevance to the case type before passing them to the LLM.

**Changes:**
- New `_filter_relevant_chunks(self, all_chunks, case_type)` method at line 765
- Defines `case_keywords` dict with Persian legal keywords for 7 case types: `contract_dispute`, `family_law`, `criminal`, `civil`, `labour`, `inheritance`, `property`
- Keeps a chunk if its `content` contains any relevant keyword OR if its `relevance_score` >= 0.5
- `logger.debug` for each dropped chunk (with score and first 100 chars of content)
- `logger.info` for total filtered count per case type
- If no keywords defined for a case type, returns all chunks unchanged

**Integration at call site (line 675):**
- Before building `legal_context` and collecting `all_chunks`, iterates over each hub in `hub_results` and applies `_filter_relevant_chunks` per-hub
- This ensures both `build_global_context()` and the citation extraction only see relevant chunks

### Step 3: Updated `_build_analysis_prompt` (Root Cause #3 fix)

**File:** [`src/backend/conversations/strategist_service.py:951`](src/backend/conversations/strategist_service.py:951)

**Changes:**
- Added `**Case Description (Persian):**` section — injects the natural language case description so the LLM understands the case facts clearly in fluent Persian
- Added `**IMPORTANT — Context Relevance Check:**` instruction block:
  > "If the retrieved legal context is not relevant to the case, ignore it and base your analysis on general legal principles. Do NOT cite laws or precedents that are not relevant to the case facts."
- The JSON facts are still included as `**Extracted Facts (JSON):**` for structured data access

### Step 4: Added diagnostic logging

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py)

Three new logging points:

1. **Case description output** (line 623, `logger.debug`): Logs the full Persian case description produced by `_build_case_description`
2. **Router query details** (line 642, `logger.debug`): Logs per-hub `fts_query` and `vector_query` (truncated to 120 chars) for debugging routing quality
3. **raw_report extraction status** (lines 1341-1362, `logger.info`): Logs whether `raw_report` was successfully extracted (with char count and strategy) or if the fallback `_build_fallback_report` was triggered

### Step 5: Created diagnostic test script

**File:** [`scripts/diag_step_rental_case.py`](scripts/diag_step_rental_case.py) (new)
**Also copied to:** [`src/backend/scripts/diag_step_rental_case.py`](src/backend/scripts/diag_step_rental_case.py) (for Docker container access)

A runnable diagnostic script that tests the full pipeline for a rental dispute case:

1. **Builds case description** — Uses the updated `_build_case_description` with realistic rental facts (موجر, مستاجر, اجاره, تخلیه)
2. **Routes the question** — Calls `route_question()` and prints active hubs, FTS/vector queries, and router reasoning
3. **Runs multi-hub search** — Calls `multi_hub_search()` and prints chunks per hub with relevance scores
4. **Verifies rental law retrieval** — Checks if chunks contain keywords like "قانون روابط موجر و مستأجر", "موجر", "مستاجر", "اجاره", "تخلیه"
5. **Manual Persian legal queries** — Tests 5 manual queries about rental law to verify the knowledge base has relevant content

**Usage:**
```
docker-compose exec backend python scripts/diag_step_rental_case.py
```

**File:** [`src/backend/conversations/strategist_service.py`](src/backend/conversations/strategist_service.py)

Three new logging points:

1. **Case description output** (line 623, `logger.debug`): Logs the full Persian case description produced by `_build_case_description`
2. **Router query details** (line 642, `logger.debug`): Logs per-hub `fts_query` and `vector_query` (truncated to 120 chars) for debugging routing quality
3. **raw_report extraction status** (lines 1341-1362, `logger.info`): Logs whether `raw_report` was successfully extracted (with char count and strategy) or if the fallback `_build_fallback_report` was triggered

### Step 6: Increased max_tokens for Router & Fact Extraction

**Files:**
- [`src/backend/config/settings.py:316`](src/backend/config/settings.py:316)
- [`src/backend/conversations/strategist_service.py:61`](src/backend/conversations/strategist_service.py:61)

**Changes:**
1. **`QUERY_FORMULATION_MAX_TOKENS`**: `150` → `1024` — prevents router LLM responses from being truncated mid-JSON (was causing `Unterminated string` parse errors)
2. **`QUERY_FORMULATION_TIMEOUT`**: `5` → `15` seconds — increased to accommodate longer generation time for 1024 tokens
3. **`_FACT_EXTRACTION_MAX_TOKENS`**: `600` → `1024` — ensures fact extraction LLM calls have enough room for complete Persian legal text output

**Rationale:** The diagnostic script revealed `_parse_router_response` was failing with "Unterminated string" because the LLM response was cut off at 150 tokens. Increasing to 1024 gives deepseek-chat enough room to complete its JSON output. The analysis LLM calls (`_ANALYSIS_MAX_TOKENS = 8192`) were already sufficient.

## Current State of Code

### File: `src/backend/conversations/strategist_service.py`
- **Lines 765-845**: `_filter_relevant_chunks` — chunk relevance filtering by case type keywords + score threshold.
- **Lines 675-681**: Integration of `_filter_relevant_chunks` per-hub before building legal context.
- **Lines 857-948**: `_build_case_description` — rewritten to produce fluent Persian legal description instead of JSON dump.
- **Lines 951-1007**: `_build_analysis_prompt` — updated with Persian case description section and context relevance check instructions.
- **Lines 614-626**: Diagnostic logging for case description output (DEBUG) and router query details (DEBUG).
- **Lines 1339-1362**: Diagnostic logging for raw_report extraction vs fallback (INFO).
- **Lines 61**: `_FACT_EXTRACTION_MAX_TOKENS = 1024` (was 600)
- **Lines 66-70**: Token constants — `_ANALYSIS_MAX_TOKENS = 8192`, `_REPORT_MAX_TOKENS = 8192`.
- **Lines 1009-1041**: `_extract_json_from_fence` — handles truncated responses (missing closing ```).
- **Lines 1062-1106**: `_extract_fields_via_regex` — `re.DOTALL`, array extraction, `raw_report` extraction.
- **Lines 1138-1341**: `parse_analysis_response` — 7-stage graceful degradation pipeline.
- **Lines 1792-1839**: `_save_strategic_report` — uses `update_or_create()` for idempotent retries.

### File: `scripts/diag_step_rental_case.py` (new)
- Runnable diagnostic script for the rental dispute pipeline.
- Tests: case description generation, routing, multi-hub search, rental law keyword verification, and 5 manual Persian legal queries.

### File: `src/backend/conversations/tests/test_strategist_parsing.py`
- 40 tests across 8 test classes, all passing.
- Covers fence extraction, JSON repair, regex fallback, error result, multi-strategy pipeline, truncated responses, Persian text with newlines/quotes, and DB idempotency.

## Next Steps
1. Restart backend: `docker-compose restart backend`
2. Run the diagnostic script again: `docker-compose exec backend python scripts/diag_step_rental_case.py`
3. Run the full backend test suite to ensure no regressions: `docker-compose exec backend pytest`
