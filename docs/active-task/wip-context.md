# WIP Context — E03 Refactoring (3 Medium-Severity Fixes)

## What Was Completed

All 3 changes from the E03 refactoring prompt were applied:

### Issue 1 — Fix `ALLOWED_FILE_TYPES` / `ALLOWED_EXTENSIONS` mismatch
- Renamed [`ALLOWED_FILE_TYPES`](src/backend/config/settings.py:283) → [`ALLOWED_EXTENSIONS`](src/backend/config/settings.py:283) in [`settings.py`](src/backend/config/settings.py:283).
- Changed values from MIME types (`application/pdf`, etc.) to file extensions (`['.pdf', '.docx', '.txt']`).
- Verified [`file_validator.py`](src/backend/documents/utils/file_validator.py:38) already reads `ALLOWED_EXTENSIONS` from settings with correct fallback — no code change needed.

### Issue 2 — Make `S3StorageBackend.open()` return `BytesIO`
- Added `import io` to [`s3.py`](src/backend/documents/storage/s3.py:5).
- Modified [`S3StorageBackend.open()`](src/backend/documents/storage/s3.py:126) to wrap `response["Body"]` in `io.BytesIO(response["Body"].read())` instead of returning the raw `StreamingBody`.
- This ensures seekability for PyMuPDF (E04) and consistency with [`LocalStorageBackend.open()`](src/backend/documents/storage/local.py:94).

### Issue 3 — Add storage cleanup on DB creation failure
- Modified the exception handler in [`upload_service.py`](src/backend/documents/services/upload_service.py:137-144) Step 5 to call `storage.delete_file(file_path)` when the database record creation fails.
- Added a nested try/except to log cleanup failures without masking the original `RuntimeError`.

## Current State of the Code

All 3 changes are applied and all existing tests pass.

### Files Modified

| File | Changes |
|------|---------|
| [`src/backend/config/settings.py`](src/backend/config/settings.py) | Renamed `ALLOWED_FILE_TYPES` → `ALLOWED_EXTENSIONS`, changed values from MIME types to extensions |
| [`src/backend/documents/storage/s3.py`](src/backend/documents/storage/s3.py) | Added `import io`, wrapped `response["Body"]` in `BytesIO` in `open()` method |
| [`src/backend/documents/services/upload_service.py`](src/backend/documents/services/upload_service.py) | Added `storage.delete_file()` cleanup in DB creation failure handler |
## Remaining Items

- No remaining items — all 3 changes are complete.

## Reference Documentation Updates

- **`docs/references/database-schema.md`**: No changes — no database schema modifications were made.
- **`docs/references/api-registry.md`**: No changes — no API endpoints were modified.
