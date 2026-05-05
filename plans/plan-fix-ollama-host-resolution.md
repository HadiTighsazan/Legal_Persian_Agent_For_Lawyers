# Fix Plan: Ollama `host.docker.internal` DNS Resolution Failure

## Problem Summary

When a user uploads a document and then asks a question via "Start Chat", the RAG pipeline fails with:

```
Error: Failed to embed question: Failed to embed query:
HTTPConnectionPool(host='host.docker.internal', port=11434):
Max retries exceeded with url: /api/embed
(Caused by NameResolutionError("... Failed to resolve 'host.docker.internal'"))
```

## Root Cause Analysis

### Call Chain

```
Frontend (browser)
  → POST /conversations/{id}/messages/
    → ConversationMessageView.post()
      → run_rag_query()
        → embed_query(question)
          → get_embedding_provider()  → returns OllamaEmbeddingProvider
            → OllamaEmbeddingProvider.embed_query(text)
              → requests.post("http://host.docker.internal:11434/api/embed")
                → ❌ DNS resolution fails for 'host.docker.internal'
```

### Primary Root Cause

The [`backend`](docker-compose.yml:66) service in [`docker-compose.yml`](docker-compose.yml) is **missing** the `extra_hosts` entry that maps `host.docker.internal` to `host-gateway`. This entry **is** present on [`celery_worker`](docker-compose.yml:128-129) and [`celery_beat`](docker-compose.yml:174-175), but not on `backend`.

Since the `backend` service runs the Django API server (which handles the synchronous POST to `/messages/`), it needs to resolve `host.docker.internal` to reach Ollama running on the host machine.

### Secondary Issue: Inconsistent Configuration

The [`EMBEDDING_PROVIDER`](src/backend/config/settings.py:252) is set to `ollama` (via `.env`), but the [`OLLAMA_BASE_URL`](src/backend/config/settings.py:251) defaults to `http://host.docker.internal:11434`. This hostname:
- Works on **Docker Desktop** (Windows/Mac) automatically via a DNS entry
- Works on **Linux** **only** if `extra_hosts` is explicitly set
- Is **not** resolvable inside the `backend` container because `extra_hosts` is missing

### Tertiary Issue: `.env.example` Encourages Fragile Pattern

The [`.env.example`](.env.example:110) shows `OLLAMA_BASE_URL=http://host.docker.internal:11434` as the default, which is fragile across different Docker environments.

## Solution Options

### Option A (Recommended): Add `extra_hosts` to `backend` service

**Files to modify:**
- [`docker-compose.yml`](docker-compose.yml)

**Changes:**
Add the same `extra_hosts` block to the `backend` service that already exists on `celery_worker` and `celery_beat`:

```yaml
backend:
  # ... existing config ...
  extra_hosts:
    - "host.docker.internal:host-gateway"
  # ... rest of existing config ...
```

**Pros:**
- Minimal change (1 block, ~2 lines)
- Consistent with existing pattern on worker/beat containers
- No `.env` changes needed
- No code changes needed

**Cons:**
- Still relies on `host.docker.internal` which is Docker-specific
- Only works if Ollama is running on the host machine

---

### Option B: Use Docker service name for Ollama (if Ollama is containerized)

If Ollama is running as a Docker container on the same `docuchat_network`, change the URL to use the service name directly.

**Files to modify:**
- [`.env`](.env.example) (or actual `.env` file)
- [`docker-compose.yml`](docker-compose.yml) (to add Ollama service)

**Changes:**
1. Add Ollama as a service in `docker-compose.yml`
2. Change `OLLAMA_BASE_URL=http://ollama:11434`
3. Update `.env` accordingly

**Pros:**
- No dependency on Docker Desktop-specific DNS
- Works identically on Windows, Mac, and Linux
- Ollama is managed alongside other services

**Cons:**
- Larger change (new service in docker-compose)
- Requires pulling Ollama Docker image
- May conflict with locally-running Ollama

---

### Option C: Change `EMBEDDING_PROVIDER` to `google` (use Gemini)

**Files to modify:**
- [`.env`](.env.example) (or actual `.env` file)

**Changes:**
Set `EMBEDDING_PROVIDER=google` and ensure `GOOGLE_API_KEY` is set.

**Pros:**
- No dependency on Ollama at all
- Uses the already-configured Gemini API key
- More reliable (cloud API vs local service)

**Cons:**
- Requires internet connectivity
- May incur API costs
- Changes the embedding provider behavior

---

### Option D: Change `OLLAMA_BASE_URL` to `localhost` (if Ollama is on host, Docker networking mode)

**Files to modify:**
- [`.env`](.env.example) (or actual `.env` file)

**Changes:**
Set `OLLAMA_BASE_URL=http://localhost:11434`

**Note:** This only works if the `backend` container uses `--network=host` mode, which it currently does not (it uses `docuchat_network` bridge network). In bridge mode, `localhost` inside the container refers to the container itself, not the host.

**Pros:**
- Simple change

**Cons:**
- ❌ **Does not work** with the current bridge network setup
- Would require changing the network mode, which breaks inter-container communication

---

## Recommended Fix: Option A

### Implementation Steps

1. **Add `extra_hosts` to `backend` service** in [`docker-compose.yml`](docker-compose.yml)

   Add after line 72 (`restart: unless-stopped`) and before line 73 (`depends_on:`):

   ```yaml
       extra_hosts:
         - "host.docker.internal:host-gateway"
   ```

2. **Verify the fix** by:
   - Running `docker-compose down && docker-compose up -d`
   - Uploading a document and waiting for processing to complete
   - Starting a chat and asking a question
   - Checking `docker-compose logs backend` for any remaining connection errors

### Why Option A is Best

- **Minimal change surface** — only 2 lines in 1 file
- **Consistent** — matches what `celery_worker` and `celery_beat` already do
- **No code changes** — the Python/Ollama provider code is correct; it's purely an infrastructure/Docker networking issue
- **No `.env` changes** — the existing configuration continues to work
- **Reversible** — easy to remove if the architecture changes later

## Files to Modify

| File | Change | Risk |
|------|--------|------|
| [`docker-compose.yml`](docker-compose.yml) | Add `extra_hosts` to `backend` service | Low |
