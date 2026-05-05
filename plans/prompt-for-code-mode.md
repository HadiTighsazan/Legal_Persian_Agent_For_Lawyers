# Prompt for Code Mode — Fix Ollama `host.docker.internal` DNS Resolution

## Problem

When a user uploads a document and asks a question via "Start Chat", the RAG pipeline fails with:

```
Error: Failed to embed question: Failed to embed query:
HTTPConnectionPool(host='host.docker.internal', port=11434):
Max retries exceeded with url: /api/embed
(Caused by NameResolutionError("... Failed to resolve 'host.docker.internal'"))
```

## Root Cause

The [`backend`](docker-compose.yml:66) service in [`docker-compose.yml`](docker-compose.yml) is **missing** the `extra_hosts` entry that maps `host.docker.internal` to `host-gateway`. This entry **is** present on [`celery_worker`](docker-compose.yml:128-129) and [`celery_beat`](docker-compose.yml:174-175), but not on `backend`.

Since the `backend` service runs the Django API server (which handles the synchronous POST to `/messages/`), it needs to resolve `host.docker.internal` to reach Ollama running on the host machine.

## Task

Apply **Option A** from the plan at [`plans/plan-fix-ollama-host-resolution.md`](plans/plan-fix-ollama-host-resolution.md):

### Step 1: Add `extra_hosts` to `backend` service

In [`docker-compose.yml`](docker-compose.yml), add the following block to the `backend` service definition (after `restart: unless-stopped` on line 72, before `depends_on:` on line 73):

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

The final result should look like this (around lines 70-78):

```yaml
  backend:
    build:
      context: .
      dockerfile: ./docker/backend/Dockerfile
    image: docuchat_backend
    container_name: docuchat_backend
    restart: unless-stopped
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

### Step 2: Update WIP Context

After making the change, update [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) with:
1. What was completed (added `extra_hosts` to `backend` service)
2. Current state (docker-compose.yml updated)
3. Next step (verify the fix by rebuilding and testing)

### Step 3: Verify

Run the following to rebuild and restart:
```bash
docker-compose down && docker-compose up -d
```

Then test by:
1. Uploading a document
2. Waiting for processing to complete
3. Starting a chat and asking a question
4. Checking logs: `docker-compose logs backend`
