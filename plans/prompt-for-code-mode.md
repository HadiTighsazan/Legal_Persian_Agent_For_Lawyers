# Prompt for Code Mode — Fix Document "failed" Status After Upload

## Context

The system runs fully containerized via Docker. When a user uploads a file through the frontend, the document status changes to `"failed"` after a few seconds.

**Tech Stack:**
- Backend: Django + DRF + Celery + Redis
- Embeddings: Ollama (`nomic-embed-text`) running on the **host machine** (Windows)
- Chat: DeepSeek API (OpenAI-compatible)
- Storage: Local filesystem via `LocalStorageBackend`
- PDF extraction: PyMuPDF (fitz)

**Confirmed:** The `nomic-embed-text` model IS available on the host (`ollama list` shows it).

## The Processing Pipeline

When a file is uploaded:

1. **Frontend** (`UploadPage.tsx`) → calls `POST /documents/upload/` → creates Document record with `status="uploaded"`
2. **Frontend** → calls `POST /documents/{id}/process/` → triggers `process_document()` in [`processing_service.py`](src/backend/documents/services/processing_service.py:174)
3. **Celery Chain** is created: `extract_text_from_pdf → chunk_document → embed_document`
4. If any step fails → `fail_processing_task()` is called → sets `document.status = "failed"`

## Suspected Root Causes (both need investigation & fixing)

### RC#1 (Most Likely): Ollama unreachable from Celery Worker container

**Evidence:**
- [`docker-compose.yml:149`](docker-compose.yml:149): `OLLAMA_BASE_URL=http://host.docker.internal:11434`
- [`docker-compose.yml:160`](docker-compose.yml:160): Celery worker command: `celery -A config worker --loglevel=info --concurrency=4`
- The Celery worker runs inside a Docker container on the `docuchat_network` bridge network
- `host.docker.internal` is a Docker Desktop feature that may not work reliably
- When [`embed_batch()`](src/backend/providers/ollama_embedding.py:163) gets a `ConnectionError`, it raises `EmbeddingBatchError`
- This is caught in [`embed_document`](src/backend/documents/tasks/embedding_tasks.py:129-153), which sets `document.status = "failed"`

**Fix:** Either:
- **Option A:** Add `extra_hosts` to the `celery_worker` service in `docker-compose.yml`:
  ```yaml
  celery_worker:
    extra_hosts:
      - "host.docker.internal:host-gateway"
  ```
- **Option B:** Run Ollama as a Docker service in `docker-compose.yml` and change `OLLAMA_BASE_URL` to `http://ollama:11434`
- **Option C:** Use the host machine's actual IP address instead of `host.docker.internal`

### RC#2 (Likely): File path mismatch between Backend and Celery Worker

**Evidence:**
- [`LocalStorageBackend.save_file()`](src/backend/documents/storage/local.py:131) returns an **absolute path** like `/app/media/documents/uuid.pdf`
- The `file_path` is stored in the database as this absolute path
- When [`extract_text_from_pdf`](src/backend/documents/tasks/document_processing.py:122) runs in the Celery worker, it calls `storage.open(document.file_path)` using this path
- The Celery worker mounts `backend_media:/app/media` at [`docker-compose.yml:158-159`](docker-compose.yml:158)
- The backend also mounts `backend_media:/app/media` at [`docker-compose.yml:108`](docker-compose.yml:108)
- **BUT** the backend also mounts `./src/backend:/app` as a bind mount at line 106, which **overlays** the `/app` directory
- The Celery worker also mounts `./src/backend:/app` at line 158
- If the file was saved to the **bind-mounted** path (e.g., `./src/backend/media/documents/uuid.pdf`) vs the **volume-mounted** path (`/app/media/`), there could be a discrepancy

**Additionally**, there's a bug in [`error_handler.py:37`](src/backend/documents/services/error_handler.py:37): `_has_pdf_magic_bytes()` opens the file directly from the filesystem path using `open(file_path, "rb")`. If the file doesn't exist at that path in the worker container, this will raise a `FileNotFoundError` which is **not caught** inside `classify_pdf_error()`, causing an unhandled exception.

**Fix:** 
- Ensure the storage path is consistent between containers
- Fix `_has_pdf_magic_bytes()` to handle `FileNotFoundError` gracefully

## Tasks for Code Mode

### Task 1: Diagnose the exact failure point

Add temporary detailed logging to identify which step fails:

1. In [`extract_text_from_pdf`](src/backend/documents/tasks/document_processing.py:59), add logging before `storage.open()` to log the `file_path`
2. In [`embed_document`](src/backend/documents/tasks/embedding_tasks.py:129), log the full exception details including the error type

### Task 2: Fix Ollama connectivity (RC#1)

**Approach:** Add `extra_hosts` to the Celery worker service in `docker-compose.yml` so `host.docker.internal` resolves properly.

**File to modify:** [`docker-compose.yml`](docker-compose.yml)

Add under `celery_worker` service:
```yaml
celery_worker:
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

Also add the same to `celery_beat` service for consistency.

### Task 3: Fix file path / storage consistency (RC#2)

**Approach:** Change `LocalStorageBackend` to store **relative paths** instead of absolute paths, so both containers resolve them correctly against their own `LOCAL_STORAGE_PATH`.

**Files to modify:**
- [`src/backend/documents/storage/local.py`](src/backend/documents/storage/local.py): Change `save_file()` to return a relative path instead of absolute
- [`src/backend/documents/storage/local.py`](src/backend/documents/storage/local.py): Update `open()` to handle both relative and absolute paths (backward compat)

### Task 4: Fix error_handler.py crash vulnerability

**File to modify:** [`src/backend/documents/services/error_handler.py`](src/backend/documents/services/error_handler.py)

Wrap `_has_pdf_magic_bytes()` in a try/except to handle `FileNotFoundError` and `PermissionError` gracefully, returning `False` instead of crashing.

### Task 5: Improve error message persistence

**File to modify:** [`src/backend/documents/tasks/embedding_tasks.py`](src/backend/documents/tasks/embedding_tasks.py)

In the `except Exception` block at line 129, ensure the actual error message (including the exception type and message) is stored in `document.processing_error` so the user can see what went wrong.

## Verification Steps

After implementing fixes:

1. **Test Ollama connectivity:**
   ```bash
   docker-compose exec celery_worker python -c "import requests; r = requests.get('http://host.docker.internal:11434/api/tags', timeout=5); print(r.status_code, r.json())"
   ```

2. **Test file path consistency:**
   ```bash
   docker-compose exec celery_worker ls -la /app/media/documents/
   docker-compose exec backend ls -la /app/media/documents/
   ```

3. **Test embedding directly:**
   ```bash
   docker-compose exec celery_worker python -c "
   from documents.services.embedding_service import generate_embedding
   result = generate_embedding('test text')
   print('Embedding result:', result[:5] if result else 'None')
   "
   ```

4. **Full flow test:** Upload a document through the frontend and verify it reaches `"completed"` status.

## Important Notes

- The project uses `docker-compose` (v1) not `docker compose` (v2)
- All services must be restarted after changes: `docker-compose down && docker-compose up -d`
- The `backend_media` volume is shared between `backend` and `celery_worker` services
- Do NOT modify the frontend code — the issue is entirely backend-side
- Follow TDD flow for backend changes: write test first (RED), then code (GREEN), then refactor
- Update `docs/active-task/wip-context.md` after each step
- Update `docs/references/database-schema.md` if any model changes are made
- Update `docs/references/api-registry.md` if any API changes are made
