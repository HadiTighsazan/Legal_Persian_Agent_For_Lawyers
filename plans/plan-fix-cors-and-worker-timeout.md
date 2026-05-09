# Plan: Fix CORS Error & Gunicorn Worker Timeout

## Problem Summary

Two distinct issues are preventing the chat feature from working after uploading and embedding a document:

### Issue 1: CORS Error (Blocking ALL API Requests)
The browser console shows:
```
Access to fetch at 'http://localhost/api/conversations/.../messages/stream/' 
from origin 'http://localhost:5173' has been blocked by CORS policy: 
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

### Issue 2: Gunicorn Worker Timeout / OOM (After CORS is Fixed)
Backend logs show:
```
WORKER TIMEOUT (pid:58)
Worker (pid:58) was sent SIGKILL! Perhaps out of memory?
```

---

## Root Cause Analysis

### Issue 1: CORS — Why It's Happening

The architecture is:
```
Browser (localhost:5173) → Nginx (localhost:80) → Django Backend (backend:8000)
```

The frontend [`sendMessageStream`](src/frontend/src/api/conversations.ts:221) function uses the **Fetch API directly** (not axios) and constructs the URL as:
```typescript
`${import.meta.env.VITE_API_URL || 'http://localhost:8000/api/'}conversations/${conversationId}/messages/stream/`
```

**The problem:** The frontend dev environment (`.env.development`) sets:
```
VITE_API_URL=http://localhost:8000/api
```

This means the streaming request goes to `http://localhost:8000/api/conversations/...` — **directly to the Django dev server on port 8000**, NOT through Nginx on port 80.

However, the `docker-compose.yml` overrides this for the frontend container:
```yaml
VITE_API_URL: ${VITE_API_URL:-http://localhost/api}
```

So in Docker, `VITE_API_URL` defaults to `http://localhost/api` (via Nginx on port 80).

**The CORS issue occurs because:**
1. The request goes to `http://localhost/api/...` (Nginx on port 80)
2. Nginx's [`location /api/`](docker/nginx/nginx.conf:97) block has CORS headers **commented out** (lines 112-127)
3. The comment says "CORS headers - Handled by Django" — but Django's CORS middleware only sees the request after Nginx proxies it
4. The **preflight OPTIONS request** never reaches Django because Nginx doesn't handle OPTIONS for `/api/` — it just proxies it through
5. Django's [`CORS_ALLOWED_ORIGINS`](src/backend/config/settings.py:218) includes `http://localhost:5173` which is correct
6. But the `DJANGO_CORS_ALLOWED_ORIGINS` env var passed in `docker-compose.yml` (line 91) is **never read** by `settings.py` — the setting is hardcoded

**The real issue:** The preflight (OPTIONS) request is likely failing because:
- Nginx doesn't add CORS headers for OPTIONS
- Django's `corsheaders` middleware should handle it, but the request must first reach Django
- The Nginx `proxy_pass` should forward OPTIONS correctly, but the response from Django might not include the right headers for the preflight

Actually, looking more carefully: the `corsheaders` middleware IS installed and configured. The issue might be that when using `http://localhost` (Nginx) as the API URL, the request goes through Nginx which proxies to Django, and Django's `corsheaders` should add the headers. But the browser is making the request to `http://localhost/api/...` which is the same origin as the Nginx server... wait, no — the frontend is on `localhost:5173` and the API is on `localhost:80` (different ports = different origins).

**The most likely cause:** The `corsheaders` middleware IS working for regular requests, but for the **streaming endpoint** (`/messages/stream/`), the Fetch API in [`sendMessageStream`](src/frontend/src/api/conversations.ts:233) constructs the URL using `VITE_API_URL` which in Docker is `http://localhost/api`. This goes to Nginx on port 80. Nginx proxies to Django. Django's `corsheaders` should add the headers.

BUT — the error says "Response to preflight request doesn't pass access control check". This means the OPTIONS preflight is failing. Let me check if Django's `corsheaders` middleware handles OPTIONS properly for streaming endpoints...

The fix should be to **enable CORS handling at the Nginx level** for the `/api/` location block, since Nginx is the first point of contact and can respond to OPTIONS preflight requests immediately without proxying to Django.

### Issue 2: Worker Timeout — Why It's Happening

The Gunicorn command in [`entrypoint.sh`](docker/backend/entrypoint.sh:17) is:
```bash
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

**No `--timeout` flag is specified**, so Gunicorn uses its **default timeout of 30 seconds**.

The RAG pipeline for a large Persian legal text document (like "قانون تجارت" / Commercial Law) involves:
1. **Query formulation** via LLM (calling an external API)
2. **Embedding** the query vector
3. **Hybrid search** across potentially thousands of chunks
4. **Building context** from retrieved chunks
5. **Calling the chat provider** API for the final answer

For a large document, steps 1-5 can easily exceed 30 seconds, especially if:
- The embedding provider is slow (Ollama running on host via `host.docker.internal`)
- The chat provider API call takes a long time
- The document has many chunks to search through

The worker is killed at 30 seconds, and the SIGKILL suggests it may also be running out of memory.

---

## Proposed Fixes

### Fix 1: Enable CORS at Nginx Level (Immediate Fix)

**File:** [`docker/nginx/nginx.conf`](docker/nginx/nginx.conf)

Uncomment and enable the CORS headers in the `/api/` location block, and add explicit OPTIONS preflight handling:

```nginx
location /api/ {
    limit_req zone=api burst=20 nodelay;
    
    # CORS headers
    add_header Access-Control-Allow-Origin "$http_origin" always;
    add_header Access-Control-Allow-Methods "GET, POST, PUT, PATCH, DELETE, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type, X-Requested-With" always;
    add_header Access-Control-Allow-Credentials "true" always;
    
    # Handle preflight requests
    if ($request_method = 'OPTIONS') {
        add_header Access-Control-Allow-Origin "$http_origin";
        add_header Access-Control-Allow-Methods "GET, POST, PUT, PATCH, DELETE, OPTIONS";
        add_header Access-Control-Allow-Headers "Authorization, Content-Type, X-Requested-With";
        add_header Access-Control-Max-Age 86400;
        add_header Content-Type 'text/plain charset=UTF-8';
        add_header Content-Length 0;
        return 204;
    }
    
    proxy_pass http://backend/;
    # ... rest of proxy settings
}
```

**Why this works:** Nginx responds to OPTIONS preflight requests immediately with 204, without proxying to Django. This is faster and more reliable. The `always` parameter ensures headers are added even on error responses.

### Fix 2: Increase Gunicorn Worker Timeout

**File:** [`docker/backend/entrypoint.sh`](docker/backend/entrypoint.sh)

Change the Gunicorn command to increase the timeout and add memory-related settings:

```bash
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --max-requests 1000 \
    --max-requests-jitter 100
```

**Why this works:**
- `--timeout 120`: Increases worker timeout from 30s to 120s, giving the RAG pipeline enough time for embedding + search + LLM call
- `--max-requests 1000` + `--max-requests-jitter 100`: Restarts workers after handling ~1000 requests to prevent memory leaks from accumulating

### Fix 3 (Optional but Recommended): Add CORS_ALLOWED_ORIGINS env var support

**File:** [`src/backend/config/settings.py`](src/backend/config/settings.py)

The `DJANGO_CORS_ALLOWED_ORIGINS` env var is passed in `docker-compose.yml` but never read in `settings.py`. Update the CORS settings to read from the environment:

```python
CORS_ALLOWED_ORIGINS = env.list(
    'DJANGO_CORS_ALLOWED_ORIGINS',
    default=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
)
```

This ensures the CORS configuration is consistent between environments.

---

## Implementation Steps

| Step | File | Change | Priority |
|------|------|--------|----------|
| 1 | [`docker/nginx/nginx.conf`](docker/nginx/nginx.conf) | Uncomment and enable CORS headers + OPTIONS handling in `/api/` block | **High** |
| 2 | [`docker/backend/entrypoint.sh`](docker/backend/entrypoint.sh) | Add `--timeout 120 --max-requests 1000 --max-requests-jitter 100` to Gunicorn | **High** |
| 3 | [`src/backend/config/settings.py`](src/backend/config/settings.py) | Make `CORS_ALLOWED_ORIGINS` read from `DJANGO_CORS_ALLOWED_ORIGINS` env var | Medium |
| 4 | Rebuild and restart containers | `docker-compose up -d --build nginx backend` | **Required** |

---

## Verification

After applying the fixes:

1. **CORS Test:** Open browser DevTools → Network tab → Send a chat message → Verify OPTIONS preflight returns 204 with correct CORS headers, and POST returns 201/200
2. **Timeout Test:** Send a query to a large document → Verify the RAG pipeline completes without worker timeout errors in backend logs
3. **Logs:** Check `docker-compose logs backend` for no "WORKER TIMEOUT" messages
