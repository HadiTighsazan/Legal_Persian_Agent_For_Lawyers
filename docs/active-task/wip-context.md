# WIP Context — Phase 2: Storage Abstraction Layer (Epic E-03)

## What was just completed

### Task 2.1 — Created `documents/storage/__init__.py`
- **File created:** `src/backend/documents/storage/__init__.py`
- **Action:** Factory function `get_storage_backend()` that reads `settings.STORAGE_TYPE` and returns the appropriate backend instance.
- Supports `"local"` → `LocalStorageBackend` and `"s3"` → `S3StorageBackend`.
- Raises `StorageError` for unknown storage types.

### Task 2.2 — Created `documents/storage/base.py`
- **File created:** `src/backend/documents/storage/base.py`
- **Action:** Abstract `StorageBackend` class with three abstract methods:
  - `save_file(uploaded_file, relative_path) -> str`
  - `get_file_url(storage_path) -> str`
  - `delete_file(storage_path) -> bool`
- Also defines `StorageError` exception class.

### Task 2.3 — Created `documents/storage/local.py`
- **File created:** `src/backend/documents/storage/local.py`
- **Action:** `LocalStorageBackend` implementing the abstract class.
- Reads `settings.LOCAL_STORAGE_PATH` as the root directory.
- Includes directory traversal protection.
- Auto-creates parent directories on save.
- Returns absolute filesystem paths.

### Task 2.4 — Created `documents/storage/s3.py`
- **File created:** `src/backend/documents/storage/s3.py`
- **Action:** `S3StorageBackend` implementing the abstract class using `boto3` client.
- Reads `settings.S3_BUCKET_NAME` and `settings.S3_REGION`.
- `save_file()` uses `upload_fileobj()`.
- `get_file_url()` generates a presigned URL (1-hour expiry).
- `delete_file()` handles `NoSuchKey` gracefully (returns `False`).

## Current state of the code

- All 4 storage abstraction files are created and ready.
- The existing settings in `src/backend/config/settings.py` already define:
  - `STORAGE_TYPE` (default: `'local'`)
  - `LOCAL_STORAGE_PATH` (default: `BASE_DIR / 'media/documents'`)
  - `S3_BUCKET_NAME` (default: `'docuchat-uploads'`)
  - `S3_REGION` (default: `'us-east-1'`)
- `boto3` is already listed in `requirements.txt`.
- No changes were made to `models.py` — the model changes (using `filename` and `storage_type` fields) will be applied in a later phase.

## Exact next step to be executed

Phase 2 is complete. The next phase (Phase 3: File Validation Utility) can proceed once the user confirms.
