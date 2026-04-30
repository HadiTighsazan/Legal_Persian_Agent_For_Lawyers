# E03 — Refactoring Prompt: Fix 3 Medium-Severity Issues

## Context

This prompt is for fixing 3 medium-severity issues identified in the E03 (Document Upload & Storage) code review. All tests currently pass — the goal is to improve correctness and robustness without breaking anything.

## Changes Required

### Issue 1: Fix `ALLOWED_FILE_TYPES` / `ALLOWED_EXTENSIONS` mismatch

**Problem**: [`src/backend/config/settings.py:283`](src/backend/config/settings.py:283) defines `ALLOWED_FILE_TYPES` with MIME types, but [`src/backend/documents/utils/file_validator.py:38`](src/backend/documents/utils/file_validator.py:38) reads `ALLOWED_EXTENSIONS` expecting file extensions. The setting is dead code; the fallback `[".pdf", ".docx", ".txt"]` is always used.

**Fix**:
1. In [`src/backend/config/settings.py`](src/backend/config/settings.py), rename `ALLOWED_FILE_TYPES` to `ALLOWED_EXTENSIONS` and change the values from MIME types to extensions:
   ```python
   # Before:
   ALLOWED_FILE_TYPES = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']
   
   # After:
   ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt']
   ```
2. In [`src/backend/documents/utils/file_validator.py`](src/backend/documents/utils/file_validator.py), no code change needed — it already reads `ALLOWED_EXTENSIONS` from settings. Just verify the default fallback matches.

### Issue 2: Make `S3StorageBackend.open()` return `BytesIO`

**Problem**: [`src/backend/documents/storage/s3.py:126`](src/backend/documents/storage/s3.py:126) returns `response["Body"]` (a raw `StreamingBody`), while [`src/backend/documents/storage/local.py:94`](src/backend/documents/storage/local.py:94) returns `io.BytesIO(f.read())`. This inconsistency means the S3 backend returns a non-seekable stream, which will break PyMuPDF (used in Epic E04 for PDF text extraction) and any other code that expects `BytesIO` behavior.

**Fix**:
In [`src/backend/documents/storage/s3.py`](src/backend/documents/storage/s3.py), modify the `open()` method to wrap the response body in `BytesIO`:

```python
import io  # Add at top if not already imported

def open(self, storage_path: str) -> BinaryIO:
    """..."""
    try:
        response = self._client.get_object(
            Bucket=self._bucket_name,
            Key=storage_path,
        )
        # Wrap in BytesIO to match LocalStorageBackend contract
        # and ensure seekability for PyMuPDF and other consumers.
        return io.BytesIO(response["Body"].read())
    except ClientError as exc:
        ...
```

**Important**: The return type hint `BinaryIO` is already correct — `BytesIO` is a `BinaryIO`. No type changes needed.

### Issue 3: Add storage cleanup on DB creation failure

**Problem**: In [`src/backend/documents/services/upload_service.py:126-144`](src/backend/documents/services/upload_service.py:126), if the file is saved to storage (Step 4) but the database record creation fails (Step 5), the file remains orphaned in storage with no cleanup mechanism.

**Fix**:
In [`src/backend/documents/services/upload_service.py`](src/backend/documents/services/upload_service.py), modify the exception handler in Step 5 to delete the orphaned file:

```python
try:
    document = create_document(...)
    logger.info("Document record created with id=%s", document.id)
except Exception as exc:
    logger.exception(
        "Failed to create database record for '%s'", unique_filename
    )
    # Clean up the orphaned file from storage
    try:
        storage.delete_file(file_path)
        logger.info("Cleaned up orphaned file: %s", file_path)
    except Exception as cleanup_exc:
        logger.error(
            "Failed to clean up orphaned file '%s': %s",
            file_path, cleanup_exc,
        )
    raise RuntimeError(
        f"Document file was saved but the database record could not be "
        f"created: {exc}"
    ) from exc
```

## Files to Modify

| File | Change |
|------|--------|
| [`src/backend/config/settings.py`](src/backend/config/settings.py) | Rename `ALLOWED_FILE_TYPES` → `ALLOWED_EXTENSIONS`, change values to extensions |
| [`src/backend/documents/storage/s3.py`](src/backend/documents/storage/s3.py) | Wrap `response["Body"]` in `io.BytesIO(...)` in `open()` method |
| [`src/backend/documents/services/upload_service.py`](src/backend/documents/services/upload_service.py) | Add `storage.delete_file()` cleanup in the DB creation failure handler |

## Verification

After making changes, run the existing tests to confirm nothing is broken:

```bash
docker-compose exec backend pytest src/backend/documents/tests/ src/backend/tests/test_upload_integration.py -v
```

All existing tests should pass without modification.
