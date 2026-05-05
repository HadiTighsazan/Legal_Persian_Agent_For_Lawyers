# WIP Context — Fix Document "failed" Status After Upload

## What Was Just Completed

**Fixed the document processing pipeline that was setting documents to `"failed"` status after upload.**

### Root Causes & Fixes

#### RC#1 (Most Likely): Ollama unreachable from Celery Worker container
- **Problem:** The Celery worker runs inside a Docker container on the `docuchat_network` bridge network. `host.docker.internal` is a Docker Desktop feature that may not resolve reliably without explicit configuration. When `embed_batch()` gets a `ConnectionError`, it raises `EmbeddingBatchError`, which is caught in `embed_document` and sets `document.status = "failed"`.
- **Fix:** Added `extra_hosts` to both `celery_worker` and `celery_beat` services in `docker-compose.yml`:
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```

#### RC#2 (Likely): File path mismatch between Backend and Celery Worker
- **Problem:** `LocalStorageBackend.save_file()` returned an **absolute path** (e.g., `/app/media/documents/uuid.pdf`). This absolute path was stored in the database. When the Celery worker tried to open the file using `storage.open(document.file_path)`, it worked because both containers mount the same `backend_media` volume at `/app/media`. However, the backend also has a bind mount `./src/backend:/app` which overlays `/app`. If the file was saved to the bind-mounted path vs the volume-mounted path, there could be a discrepancy.
- **Fix:** Changed `save_file()` to return a **relative path** (the same `relative_path` passed in) instead of an absolute path. Both containers resolve relative paths against their own `LOCAL_STORAGE_PATH` setting, ensuring consistency. Updated `delete_file()` to also resolve relative paths against the storage root.

#### RC#3: error_handler.py crash vulnerability
- **Problem:** `_has_pdf_magic_bytes()` opened the file directly from the filesystem path using `open(file_path, "rb")`. If the file didn't exist at that path in the worker container, this raised an unhandled `FileNotFoundError` inside `classify_pdf_error()`, causing an unhandled exception.
- **Fix:** Wrapped the file open in a `try/except (FileNotFoundError, PermissionError, OSError)` block, returning `False` instead of crashing. Also added a module-level `logger` instance that was missing.

#### Improved error message persistence
- **Problem:** The `except Exception` block in `embed_document` stored only `str(e)` in `document.processing_error`, which didn't include the exception type or traceback, making debugging difficult.
- **Fix:** Enhanced the error message to include `[ExceptionTypeName]: message` format and the full traceback via `traceback.format_exc()`. Also added detailed logging with `logger.exception()` in the `extract_text_from_pdf` catch-all block.

#### Added detailed logging for diagnostics
- Added logging of `document.file_path` before `storage.open()` in `extract_text_from_pdf`
- Added `error_type` to log messages in `embed_document` exception handler

## Files Modified

### `docker-compose.yml`
- Added `extra_hosts` to `celery_worker` service (line 126)
- Added `extra_hosts` to `celery_beat` service (line 170)

### `src/backend/documents/storage/local.py`
- `save_file()` now returns a **relative path** instead of absolute path
- `delete_file()` now resolves relative paths against the storage root (backward compat with absolute paths preserved)

### `src/backend/documents/services/error_handler.py`
- Added module-level `logger = logging.getLogger(__name__)`
- `_has_pdf_magic_bytes()` now catches `FileNotFoundError`, `PermissionError`, and `OSError` gracefully, returning `False`

### `src/backend/documents/tasks/document_processing.py`
- Added detailed logging of `document.file_path` before `storage.open()` in `extract_text_from_pdf`
- Added `logger.exception()` with error type in the catch-all `except Exception` block

### `src/backend/documents/tasks/embedding_tasks.py`
- Enhanced error messages to include exception type name: `[TypeName]: message`
- Added full traceback to `processing_error` and `error_message` fields
- Added `error_type` to log output

## New Test Files

### `src/backend/tests/test_storage_local.py` (7 tests)
- `test_save_file_returns_relative_path` — verifies `save_file` returns relative path
- `test_open_relative_path` — verifies `open` resolves relative paths
- `test_open_absolute_path_backward_compat` — verifies `open` still works with absolute paths
- `test_open_nonexistent_file_raises_storage_error` — verifies proper error for missing files
- `test_delete_file_relative_path` — verifies `delete_file` works with relative paths
- `test_delete_file_nonexistent_returns_false` — verifies graceful handling of missing files
- `test_get_file_url_returns_path_as_is` — verifies `get_file_url` returns path unchanged

### `src/backend/documents/tests/test_error_handler.py` (6 tests)
- `test_nonexistent_file_returns_false` — verifies `_has_pdf_magic_bytes` doesn't crash on missing file
- `test_permission_error_returns_false` — verifies graceful handling of permission errors
- `test_valid_pdf_header_returns_true` — verifies correct detection of PDF magic bytes
- `test_non_pdf_header_returns_false` — verifies non-PDF files return False
- `test_empty_file_returns_false` — verifies empty files return False
- `test_nonexistent_file_path_does_not_crash` — verifies `classify_pdf_error` doesn't crash on missing file

## Test Results
- ✅ All **13 new tests** pass
- ✅ All **243 existing tests** pass (plus 30 subtests)

## Current State of Code
- All 7 containers are running and healthy
- `docker-compose.yml` updated with `extra_hosts` for Ollama connectivity
- Storage backend returns relative paths for cross-container consistency
- Error handler is resilient to missing/unreadable files
- Error messages include full exception details for debugging

## Next Steps
1. Restart all services: `docker-compose down && docker-compose up -d`
2. Verify Ollama connectivity from Celery worker:
   ```bash
   docker-compose exec celery_worker python -c "import requests; r = requests.get('http://host.docker.internal:11434/api/tags', timeout=5); print(r.status_code, r.json())"
   ```
3. Verify file path consistency:
   ```bash
   docker-compose exec celery_worker ls -la /app/media/documents/
   docker-compose exec backend ls -la /app/media/documents/
   ```
4. Test embedding directly:
   ```bash
   docker-compose exec celery_worker python -c "
   from documents.services.embedding_service import generate_embedding
   result = generate_embedding('test text')
   print('Embedding result:', result[:5] if result else 'None')
   "
   ```
5. Upload a document through the frontend and verify it reaches `"completed"` status
