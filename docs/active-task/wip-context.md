# WIP Context — Phase 1 Token Optimization

## What Was Just Completed

Implemented **Phase 1 (Steps 1, 3, 5, 6)** of the Token Optimization Plan. All changes are low-risk and focus on prompt reduction and constant tweaking.

### Task 1 (Step 1a): Router Prompt Reduction
- **File:** [`src/backend/conversations/question_router.py`](../src/backend/conversations/question_router.py)
- **Change:** Reduced `SYSTEM_PROMPT` from ~106 lines (3 JSON examples, ~300 tokens) to ~50 lines (1 JSON example, ~150 tokens).
- **Details:** Removed 2 of 3 examples. Condensed hub descriptions from full labels to concise one-liners. Merged redundant instructions (e.g., "Analyse the user's question" appeared twice). Kept all core instructions: hub selection logic, fts_query/vector_query generation, entity preservation, hypothetical_answer requirement, and JSON output format.

### Task 1 (Step 1b): Hub System Prompt Condensation
- **File:** [`src/backend/conversations/global_rag_service.py`](../src/backend/conversations/global_rag_service.py) — `build_hub_system_prompt()`
- **Change:** Reduced `base_instructions` from 18 lines (~200 tokens) to 10 lines (~120 tokens).
- **Details:** Merged instruction #1 (redundant "answer based ONLY on context" appeared twice). Condensed the "insufficient info" message. Combined citation instruction with format example. Removed redundant "Answer in Persian" (already in hub-specific suffix). Kept all 6 original instructions but more concise.

### Task 1 (Step 1c): Synthesis Prompt Condensation
- **File:** [`src/backend/conversations/global_rag_service.py`](../src/backend/conversations/global_rag_service.py) — `build_synthesis_system_prompt()`
- **Change:** Reduced from 38 lines (~450 tokens) to ~25 lines (~300 tokens).
- **Details:** Condensed hub descriptions. Merged conflict detection sub-steps (a-d) into tighter prose. Removed redundant explanation of legal hierarchy (mentioned only once now). Kept all key behaviors: conflict detection with `[Conflict]` marker, legal hierarchy resolution, hub attribution, and logical answer structure.

### Task 2 (Step 3): Context Header Optimization
- **File:** [`src/backend/conversations/global_rag_service.py`](../src/backend/conversations/global_rag_service.py) — `build_global_context()`
- **Change:** Removed `Hub:` field from source headers.
- **Old format:** `[Source N | Hub: {hub_label} | Pages {start}-{end} | {legal_context}]`
- **New format:** `[Source N | Pages {start}-{end} | {legal_context}]`
- **Rationale:** The hub label is already shown in the section header `=== [{hub_label}] ===`, so it was redundant in every chunk header. Saves ~30-50 chars per header × 15 chunks = ~100-200 tokens.

### Task 3 (Step 5): RRF Depth Reduction
- **File:** [`src/backend/documents/services/search_service.py`](../src/backend/documents/services/search_service.py)
- **Change:** `_RRF_DEPTH_MULTIPLIER` from 6 → 4, `_RRF_MIN_DEPTH` from 30 → 20.
- **Effect:** For top_k=5: depth = max(5×4, 20) = 20 (was 30). Each search method now fetches 20 candidates instead of 30 before RRF fusion. Still provides 4× the final result count, which is sufficient for RRF to find the top-5.

### Task 3 (Step 6): Hub Timeout Reduction
- **File:** [`src/backend/conversations/global_rag_service.py`](../src/backend/conversations/global_rag_service.py)
- **Change:** `_TIMEOUT_PER_HUB` from 45 → 30 seconds.
- **Rationale:** Pipeline handles timeouts gracefully (returns error, continues with other hubs). 30s is still ample for embedding + DB queries.

### Test Updates
- Updated [`test_question_router.py`](../src/backend/conversations/tests/test_question_router.py): `test_system_prompt_contains_hub_labels` — now checks Persian names directly instead of full `HUB_LABELS` values (which are no longer verbatim in the condensed prompt).
- Updated [`test_global_rag_service.py`](../src/backend/conversations/tests/test_global_rag_service.py): `test_global_source_numbering` and `test_includes_legal_context_in_source_header` — removed assertions for the removed `Hub:` field in source headers.

## Current State
- All 69 tests pass (22 question_router + 47 global_rag_service).
- No business logic changed. Only prompt text and constants modified.
- Estimated token savings: ~400-500 (prompts) + ~100-200 (headers) = ~500-700 tokens per query.

## Next Step
Proceed with **Step 2** (Reduce Partial Answer `max_tokens`) and **Step 4** (Reduce `SYNTHESIS_MAX_TOKENS`) when ready. These require adding a new setting `PARTIAL_ANSWER_MAX_TOKENS=600` in `settings.py` and reducing `SYNTHESIS_MAX_TOKENS` from 4000 to 3000.
