# WIP Context — Global RAG Optimization: Synthesis max_tokens, top_k, and Streaming

## Status: ✅ COMPLETED (2026-05-12)

## Summary

Implemented three high-impact optimizations for the Global RAG pipeline to fix two reported problems: **answer truncation** (synthesis cut off mid-sentence at "مسئ") and **high token cost** (18,085 tokens per query).

### Changes Applied

| # | Change | File | Impact |
|---|--------|------|--------|
| 1 | **Increased synthesis `max_tokens` from 1000 to 2000** | [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (line 591) | Fixes truncation — comprehensive Persian legal answers now have room to complete |
| 2 | **Reduced `top_k_per_hub` from 10 to 5** | [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (line 71), [`src/backend/conversations/views.py`](src/backend/conversations/views.py) (lines 373, 531) | Reduces context size per hub by ~50%, cutting prompt token cost significantly |
| 5 | **Implemented streaming for Global RAG synthesis** | [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (lines 866-1103), [`src/backend/conversations/views.py`](src/backend/conversations/views.py) (lines 521-554) | Users see tokens arrive incrementally instead of waiting for full response |

### Items Deferred (per user instruction)

| # | Change | Reason |
|---|--------|--------|
| 3 | Per-hub context budget reduction in `build_global_context` | Lower priority — top_k reduction already cuts context significantly |
| 4 | Conversation history truncation for Global RAG | Lower priority — history is already truncated by `RAG_MAX_HISTORY_TURNS` |
| 6 | Prompt optimization (shorter hub prompts) | Lower priority — marginal gains compared to items 1, 2, 5 |

---

## Detailed Changes

### Item 1: Increase Synthesis `max_tokens`

**File:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (line 591)

**Before:**
```python
result = provider.chat(
    messages=messages,
    max_tokens=settings.CHAT_MAX_TOKENS,  # 1000
)
```

**After:**
```python
result = provider.chat(
    messages=messages,
    max_tokens=settings.CHAT_MAX_TOKENS * 2,  # 2000
)
```

**Rationale:** The synthesis step merges partial answers from all 3 hubs (legislation, judicial precedent, advisory opinions) with conflict detection. A comprehensive Persian legal answer with citations, conflict markers, and structured sections easily exceeds 1000 tokens. Doubling to 2000 provides sufficient headroom.

### Item 2: Reduce `top_k_per_hub` from 10 to 5

**File:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (line 71)

**Before:**
```python
_GLOBAL_TOP_K_PER_HUB: int = 10
```

**After:**
```python
_GLOBAL_TOP_K_PER_HUB: int = 5
```

**File:** [`src/backend/conversations/views.py`](src/backend/conversations/views.py) (lines 373, 531)

**Before:**
```python
top_k_per_hub=10,
```

**After:**
```python
top_k_per_hub=5,
```

**Rationale:** With 3 hubs, 10 chunks per hub = 30 chunks total in the context. Reducing to 5 per hub = 15 chunks total. This cuts the context prompt size by ~50%, reducing both prompt tokens and the LLM's processing burden. The RRF fusion (vector + keyword + trigram) with top_k=5 still retrieves 15 candidates per method (rrf_depth = max(top_k * 3, 60) = 60), so retrieval quality is preserved.

### Item 5: Implement Streaming for Global RAG

**New function:** [`run_global_rag_query_stream()`](src/backend/conversations/global_rag_service.py:871)

This function mirrors `run_global_rag_query()` for steps 1-3 (routing, search, partial answers) but uses `provider.chat_stream()` for step 4 (synthesis), yielding tokens incrementally.

**Yield protocol:**
- `("token", {"content": str})` — Each token from the synthesis LLM call
- `("done", {...})` — Final event with full result dict (content, sources, token_usage, hub_metadata, raw_chunks, partial_answers)

**View update:** [`ConversationMessageStreamView.event_stream()`](src/backend/conversations/views.py:521)

**Before:** Global RAG branch called `run_global_rag_query()` (non-streaming), waited for the full response, then sent it as a single SSE token.

**After:** Global RAG branch calls `run_global_rag_query_stream()`, iterates over yielded tokens, sends each as an SSE `token` event, then persists the message and sends a `done` event.

**Token usage:** The streaming function uses `max_tokens=settings.CHAT_MAX_TOKENS * 2` (2000) for the synthesis step, consistent with Item 1.

---

## Files Modified

| File | Description |
|------|-------------|
| [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) | Changed `_GLOBAL_TOP_K_PER_HUB` from 10 to 5; doubled synthesis `max_tokens`; added `Generator` import; added `run_global_rag_query_stream()` function |
| [`src/backend/conversations/views.py`](src/backend/conversations/views.py) | Added `run_global_rag_query_stream` import; changed `top_k_per_hub=10` to `top_k_per_hub=5` in both non-streaming and streaming views; rewrote Global RAG streaming branch to use `run_global_rag_query_stream()` |

## Next Steps

1. **Rebuild and restart containers:** `docker-compose up --build -d` to apply changes
2. **Manual verification:** Send a Persian legal query (e.g., "مسئولیت کیفری شخص حقوقی در قانون مجازات اسلامی چیست؟") via the streaming endpoint and verify:
   - Tokens arrive incrementally (not all at once)
   - Response is complete (not truncated)
   - Token usage is reduced compared to previous 18K
3. **Consider deferred items** (Items 3, 4, 6) if further optimization is needed
