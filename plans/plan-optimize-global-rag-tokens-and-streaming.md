# Plan: Optimize Global RAG — Fix Answer Truncation & Reduce Token Cost

## Problem Summary

The user reported two issues when using Global RAG at `/legal-research/{conversation_id}`:

1. **Answer truncation**: The response stopped abruptly mid-sentence at "مسئ" (clearly cut off).
2. **High token cost**: 18,085 total tokens for a single query.

## Root Cause Analysis

### Problem 1: Answer Truncation

The Global RAG pipeline makes **5 sequential LLM calls** for a single user query:

| Step | LLM Call | Purpose | Completion Tokens |
|------|----------|---------|-------------------|
| 1 | `route_question()` | Route question to relevant hubs | `QUERY_FORMULATION_MAX_TOKENS=150` |
| 2 | `generate_hub_partial_answer('legislation')` | Partial answer for legislation | `CHAT_MAX_TOKENS=1000` |
| 3 | `generate_hub_partial_answer('judicial_precedent')` | Partial answer for judicial precedent | `CHAT_MAX_TOKENS=1000` |
| 4 | `generate_hub_partial_answer('advisory_opinion')` | Partial answer for advisory opinions | `CHAT_MAX_TOKENS=1000` |
| 5 | `synthesize_answers()` | Final synthesis of all partial answers | `CHAT_MAX_TOKENS=1000` |

**The synthesis step (Step 5) is capped at `CHAT_MAX_TOKENS=1000`**. The synthesis system prompt alone is ~600 words, plus the partial answers from 3 hubs (each potentially 500-1000 chars), plus the original question. The model needs to produce a comprehensive Persian legal answer covering all three hubs with conflict detection — 1000 tokens is insufficient, causing the abrupt cutoff.

### Problem 2: High Token Cost (18,085 tokens)

The 18K tokens come from **5 LLM calls**, each with large prompts:

**Call 1 — Question Router:**
- System prompt: ~2,500 chars (~625 tokens)
- User query: ~100 chars (~25 tokens)
- **Total: ~650 prompt tokens**

**Calls 2-4 — Per-Hub Partial Answers (3 calls):**
Each call includes:
- Hub-specific system prompt: ~500 chars (~125 tokens)
- Context from `build_global_context()`: up to `RAG_CONTEXT_TOKEN_BUDGET=4000` tokens per hub
- Question: ~25 tokens
- **Total per hub: ~4,150 prompt tokens × 3 = ~12,450 prompt tokens**

**Call 5 — Synthesis:**
- Synthesis system prompt: ~1,200 chars (~300 tokens)
- Partial answers from 3 hubs: ~1,500 chars total (~375 tokens)
- Question: ~25 tokens
- **Total: ~700 prompt tokens**

**Total prompt tokens: ~13,800**
**Total completion tokens: ~4,000 (5 calls × ~800 avg)**
**Grand total: ~17,800** — matches the reported 18,085.

### Key Inefficiencies

1. **`RAG_CONTEXT_TOKEN_BUDGET=4000`** is applied per-hub in `build_global_context()`, but the function is called separately for each hub's partial answer. Each hub gets up to 4000 tokens of context, even though the same budget is shared across all hubs in the final synthesis.

2. **`top_k_per_hub=10`** retrieves 10 chunks per hub. With `rrf_depth = max(10 * 3, 60) = 60`, each hub fetches up to 60 candidates per search method (vector, keyword, trigram). This is excessive.

3. **No streaming for Global RAG**: The streaming endpoint (`ConversationMessageStreamView`) calls `run_global_rag_query()` which is non-streaming — it waits for all 5 LLM calls to complete before sending the full response as a single token. This creates a poor UX (long wait, then sudden burst).

4. **`CHAT_MAX_TOKENS=1000`** is too low for the synthesis step but reasonable for partial answers.

## Proposed Changes

### Change 1: Reduce `top_k_per_hub` from 10 to 5

**File:** [`src/backend/conversations/views.py`](src/backend/conversations/views.py) (lines 372, 525)
**File:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (line 71)

Change `top_k_per_hub=10` to `top_k_per_hub=5` in both `ConversationMessageView.post()` and `ConversationMessageStreamView.post()`.

**Impact:** Reduces retrieved chunks from 30 (3 hubs × 10) to 15 (3 hubs × 5). This directly reduces context size in partial answer generation calls.

### Change 2: Reduce `RAG_CONTEXT_TOKEN_BUDGET` for Global RAG context building

**File:** [`src/backend/config/settings.py`](src/backend/config/settings.py) (line 278)

Consider reducing `RAG_CONTEXT_TOKEN_BUDGET` from 4000 to 2000 for Global RAG, OR make the `build_global_context()` function accept a per-hub budget parameter.

**Alternative approach (preferred):** Modify `build_global_context()` in [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) to accept an optional `max_chars` parameter, and pass a reduced budget for per-hub partial answer generation (e.g., `RAG_CONTEXT_TOKEN_BUDGET * _CHARS_PER_TOKEN // 2`).

### Change 3: Increase `CHAT_MAX_TOKENS` for the synthesis step

**File:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (line 590)

In `synthesize_answers()`, increase `max_tokens` from `settings.CHAT_MAX_TOKENS` (1000) to a higher value (e.g., `settings.CHAT_MAX_TOKENS * 2 = 2000` or a new setting `SYNTHESIS_MAX_TOKENS`).

**Impact:** The synthesis LLM will have enough output budget to produce a complete, well-structured answer without being cut off mid-sentence.

### Change 4: Implement streaming for Global RAG

**File:** [`src/backend/conversations/views.py`](src/backend/conversations/views.py) (lines 520-542)

Currently, the Global RAG branch in `ConversationMessageStreamView.event_stream()` calls `run_global_rag_query()` (non-streaming) and sends the full content as a single token. This should be changed to:

1. Run the question router, multi-hub search, and per-hub partial answers (all non-streaming — these are fast).
2. For the synthesis step, use the chat provider's `chat_stream()` method instead of `chat()`.
3. Yield tokens from the synthesis stream as they arrive.
4. After streaming completes, yield the `done` event with sources and metadata.

This requires:
- Adding a new function `run_global_rag_query_stream()` in [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) that mirrors `run_global_rag_query()` but streams the synthesis step.
- Updating `ConversationMessageStreamView.event_stream()` to use the new streaming function.

### Change 5: Add conversation history truncation for Global RAG

**File:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (line 676)

The `run_global_rag_query()` function receives `conversation_history` but doesn't truncate it. Add the same `RAG_MAX_HISTORY_TURNS` truncation that `run_rag_query()` uses (lines 320-325 of `rag_service.py`).

### Change 6: Optimize per-hub partial answer prompts

**File:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (lines 285-353)

The `build_hub_system_prompt()` function includes a `base_instructions` block that is duplicated across all three hub types. The "Instructions" section (items 1-6) is identical for all hubs. Consider shortening the prompt by:
- Removing redundant instructions (e.g., "Answer the user's question based ONLY on the context provided below" appears twice in items 1 and 2).
- Shortening the hub-specific suffix to be more concise.

## Implementation Order

1. **Change 3** (Increase synthesis max_tokens) — Directly fixes the truncation issue.
2. **Change 1** (Reduce top_k_per_hub) — Biggest impact on token cost.
3. **Change 2** (Reduce context budget for partial answers) — Secondary token savings.
4. **Change 5** (History truncation) — Prevents history bloat in multi-turn conversations.
5. **Change 4** (Streaming) — Improves UX but is the most complex change.
6. **Change 6** (Prompt optimization) — Minor savings, low priority.

## Files to Modify

| File | Changes |
|------|---------|
| `src/backend/conversations/views.py` | Reduce `top_k_per_hub=10` to `top_k_per_hub=5` (lines 372, 525); Update streaming to use new streaming function |
| `src/backend/conversations/global_rag_service.py` | Add `run_global_rag_query_stream()`; Increase synthesis `max_tokens`; Add history truncation; Optimize prompts; Modify `build_global_context()` for per-hub budget |
| `src/backend/config/settings.py` | Optionally add `SYNTHESIS_MAX_TOKENS` setting |
| `src/backend/conversations/rag_service.py` | No changes needed (reference for streaming pattern) |

## Expected Impact

| Metric | Before | After (estimated) |
|--------|--------|-------------------|
| Total tokens per query | ~18,000 | ~8,000-10,000 |
| LLM calls per query | 5 | 5 (but smaller prompts) |
| Answer truncation | Yes (cut off at 1000 tokens) | No (2000 tokens for synthesis) |
| Streaming UX | Full response at once | Token-by-token streaming |
| Chunks retrieved per hub | 10 (60 candidates) | 5 (60 candidates still, but fewer final) |

## Testing

1. Run existing backend tests: `docker-compose exec backend pytest`
2. Run existing frontend tests: `docker-compose exec frontend npm test`
3. Manual test: Send a complex Persian legal query via Global RAG and verify:
   - Answer is complete (no truncation)
   - Token usage is significantly reduced
   - Streaming works token-by-token
   - Sources and hub_metadata are correctly returned
