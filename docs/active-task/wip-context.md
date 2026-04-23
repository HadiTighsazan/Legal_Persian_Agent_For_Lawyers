# WIP Context — Phase 5: Upload Service (Epic E-03)

## What was just completed

### Task 5.1 — Created `documents/services/__init__.py`
- **File created:** `src/backend/documents/services/__init__.py` (empty package init)

### Task 5.2 — Created `documents/services/upload_service.py`
- **File created:** `src/backend/documents/services/upload_service.py`
- Implemented the `upload_document(user, file)` orchestration function that performs the full upload workflow:

  1. **Validate file type** — Calls `validate_file_type()` from the Phase‑3 validator, checking the file extension against allowed types.
  2. **Validate file size** — Calls `validate_file_size()` from the Phase‑3 validator, ensuring the file does not exceed the configured maximum.
  3. **Generate unique filename** — Produces a filename in the format `{uuid}{ext}` using Python's `uuid.uuid4()`.
  4. **Save file via storage backend** — Uses `get_storage_backend()` (Phase 2 factory) to persist the file through the configured backend (local or S3).
  5. **Create database record** — Calls `create_document()` from the repository layer (Phase 4) to persist document metadata.
  6. **Return metadata dict** — Returns a dictionary with `id`, `title`, `original_filename`, `file_size`, `mime_type`, `file_path`, `storage_type`, `status`, and `created_at`.

- **Exception handling:**
  - `ValidationError` from file type/size checks propagates naturally to the caller.
  - `StorageError` from the storage backend is caught and re-raised with logging.
  - Generic exceptions from the repository layer are caught and wrapped in a `RuntimeError` with a descriptive message.

- **Helper:** `_guess_mime_type()` uses `mimetypes.guess_type()` to derive the MIME type from the original filename, falling back to `application/octet-stream`.

## Current state of the code

- The `documents/services/` package is created with the upload service module.
- The `upload_document()` function is fully implemented and ready to be called from API views (future Phase).
- All prior layers (storage abstraction, file validators, document repository) remain unchanged.

## Exact next step to be executed

Phase 5 is complete. The next phase can proceed once the user confirms.
