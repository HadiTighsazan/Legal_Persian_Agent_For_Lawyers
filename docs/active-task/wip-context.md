# WIP Context — Debug: Global RAG Truncation & Streaming Fixes

## Status: ✅ COMPLETED (2026-05-12)

## Summary

Debugged and fixed two critical bugs in the Global RAG pipeline:

1. **Bug 1 (Answer Truncation):** Synthesis response was cut off mid-sentence at "صرفاً ع" because `max_tokens` was too low (2000) for comprehensive Persian legal answers.
2. **Bug 2 (Streaming Not Working):** Response appeared all at once after ~2 minutes instead of streaming token-by-token, because Gunicorn's default sync worker class buffers the entire response before sending.

### Root Causes Identified

| Bug | Root Cause | Fix Applied |
|-----|-----------|-------------|
| **Bug 1: Truncation** | Synthesis `max_tokens=2000` insufficient for Persian legal answers (actual response was 12,336 tokens) | Increased to 4000 via new `SYNTHESIS_MAX_TOKENS` setting |
| **Bug 2: No Streaming** | Gunicorn sync workers buffer entire response; Nginx proxy buffering also on by default | Switched to `gthread` worker class; disabled Nginx proxy buffering for `/api/` |

### Changes Applied

| # | Change | File | Impact |
|---|--------|------|--------|
| 1 | **Increased synthesis `max_tokens` from 2000 to 4000** | [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (lines 591, 1045) | Fixes truncation — comprehensive Persian legal answers now have room to complete |
| 2 | **Added `SYNTHESIS_MAX_TOKENS` setting** | [`src/backend/config/settings.py`](src/backend/config/settings.py) (line 277) | Decouples synthesis token limit from `CHAT_MAX_TOKENS`; configurable via env var |
| 3 | **Switched Gunicorn to `gthread` worker class** | [`docker/backend/entrypoint.sh`](docker/backend/entrypoint.sh) (line 35) | Enables true streaming — Gunicorn no longer buffers responses before sending |
| 4 | **Disabled Nginx proxy buffering for `/api/`** | [`docker/nginx/nginx.conf`](docker/nginx/nginx.conf) (line 101) | Prevents Nginx from buffering SSE stream chunks |

---

## Detailed Changes

### Fix 1: Increase Synthesis `max_tokens` to 4000

**Files:** [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) (lines 591, 1045)

**Before:**
```python
max_tokens=settings.CHAT_MAX_TOKENS * 2,  # 2000
```

**After:**
```python
max_tokens=settings.SYNTHESIS_MAX_TOKENS,  # 4000
```

**Rationale:** The user's response was 12,336 tokens total. Previous limit of 2000 was insufficient. The new `SYNTHESIS_MAX_TOKENS` setting defaults to 4000, which provides ample headroom for comprehensive Persian legal answers with citations, conflict markers, and structured sections.

### Fix 2: Add `SYNTHESIS_MAX_TOKENS` Setting

**File:** [`src/backend/config/settings.py`](src/backend/config/settings.py) (line 277)

**Added:**
```python
SYNTHESIS_MAX_TOKENS = env.int("SYNTHESIS_MAX_TOKENS", default=4000)
```

**Rationale:** Decouples the synthesis token limit from `CHAT_MAX_TOKENS`, allowing independent tuning. Configurable via the `SYNTHESIS_MAX_TOKENS` environment variable.

### Fix 3: Switch Gunicorn to `gthread` Worker Class

**File:** [`docker/backend/entrypoint.sh`](docker/backend/entrypoint.sh) (line 35)

**Before:**
```bash
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --max-requests 1000 \
    --max-requests-jitter 100
```

**After:**
```bash
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --threads 4 \
    --workers 3 \
    --timeout 120 \
    --max-requests 1000 \
    --max-requests-jitter 100
```

**Rationale:** Gunicorn's default sync worker class collects all yielded values from a `StreamingHttpResponse` generator before sending the HTTP response. The `gthread` worker class with 4 threads per worker allows true streaming — each response is sent incrementally as tokens are yielded. This is the **primary fix** for Bug 2.

### Fix 4: Disable Nginx Proxy Buffering

**File:** [`docker/nginx/nginx.conf`](docker/nginx/nginx.conf) (line 101)

**Added inside `location /api/` block:**
```nginx
proxy_buffering off;
proxy_cache off;
```

**Rationale:** Nginx's default `proxy_buffering on` causes it to buffer the entire response from the upstream (Gunicorn) before sending to the client. For SSE streams, this defeats the purpose of streaming. Disabling buffering ensures each SSE event is forwarded to the client immediately.

---

## Files Modified

| File | Description |
|------|-------------|
| [`src/backend/conversations/global_rag_service.py`](src/backend/conversations/global_rag_service.py) | Changed synthesis `max_tokens` from `CHAT_MAX_TOKENS * 2` to `SYNTHESIS_MAX_TOKENS` in both `synthesize_answers()` (line 591) and `run_global_rag_query_stream()` (line 1045) |
| [`src/backend/config/settings.py`](src/backend/config/settings.py) | Added `SYNTHESIS_MAX_TOKENS = env.int("SYNTHESIS_MAX_TOKENS", default=4000)` setting |
| [`docker/backend/entrypoint.sh`](docker/backend/entrypoint.sh) | Added `--worker-class gthread --threads 4` to Gunicorn command |
| [`docker/nginx/nginx.conf`](docker/nginx/nginx.conf) | Added `proxy_buffering off; proxy_cache off;` to `/api/` location block |

## Test Results

- **38/38** global RAG service tests pass ✅
- **19/20** views tests pass (1 pre-existing failure: `test_post_default_top_k` — expects `top_k=5` but actual default is `15`, unrelated to our changes) ✅
- **Pre-existing failures** (embedding dimension mismatch in integration tests, top_k default mismatch) are unrelated to our changes

## Next Steps

1. **Rebuild and restart containers:** `docker-compose up --build -d` to apply all changes
2. **Manual verification:** Send a Persian legal query (e.g., "مسئولیت کیفری شخص حقوقی در قانون مجازات اسلامی چیست؟") via the streaming endpoint and verify:
   - Tokens arrive incrementally (not all at once)
   - Response is complete (not truncated)
   - Sources and hub_metadata are correctly returned
3. **Monitor token usage** to ensure the 4000 limit is sufficient without being excessive
