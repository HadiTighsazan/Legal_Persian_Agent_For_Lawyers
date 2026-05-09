# WIP Context — Fix DNS Resolution Failure in Docker Containers

## Status: ✅ COMPLETED (2026-05-09)

## Problem Summary

User reported "Chat provider API call failed: Connection error." when sending a chat message after uploading a document.

### Root Cause: Hardcoded DNS Server Unreachable

The `docker-compose.yml` had hardcoded `dns: - 192.168.221.203` entries for the `backend`, `celery_worker`, and `celery_beat` services. This DNS server was **unreachable** from within the Docker containers, causing all external hostname resolutions to fail with:

```
httpcore.ConnectError: [Errno -3] Temporary failure in name resolution
```

This affected the chat provider (DeepSeek API at `api.deepseek.com`) which is called via the OpenAI-compatible provider at `CHAT_BASE_URL=https://api.deepseek.com/v1`.

### Error Chain

1. User sends chat message → Backend calls `OpenAIChatProvider.chat()` → OpenAI client tries to connect to `api.deepseek.com`
2. DNS lookup fails → `httpx.ConnectError: [Errno -3] Temporary failure in name resolution`
3. OpenAI client raises `openai.APIConnectionError: Connection error`
4. `rag_service.py` catches it and raises `RAGServiceException("Chat provider API call failed: Connection error.")`
5. Backend returns HTTP 502 Bad Gateway to frontend

### Verification

- Before fix: `socket.gethostbyname('api.deepseek.com')` → ❌ `[Errno -3] Temporary failure in name resolution`
- After fix: `socket.gethostbyname('api.deepseek.com')` → ✅ `3.173.21.63`

## What Changed

### Files Modified

| File | Change |
|------|--------|
| [`docker-compose.yml`](docker-compose.yml) | **Removed hardcoded `dns: - 192.168.221.203`** from `backend` (lines 78-79), `celery_worker` (lines 137-138), and `celery_beat` (lines 185-186) services. Docker now inherits DNS from the host automatically. |

## Next Step

User should test by uploading a file and sending a chat message in the UI to confirm the fix works.
