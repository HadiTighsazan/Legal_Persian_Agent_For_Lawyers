# WIP Context — Phase 3: File Validation Utility (Epic E-03)

## What was just completed

### Task 3.1 — Created `documents/utils/__init__.py`
- **File created:** `src/backend/documents/utils/__init__.py` (empty package init)

### Task 3.2 — Created `documents/utils/file_validator.py`
- **File created:** `src/backend/documents/utils/file_validator.py`
- **Action:** Two validation functions:

#### `validate_file_type(filename, allowed_types=None)`
- Checks the file extension against an allowed list.
- If `allowed_types` is not provided, reads from `settings.ALLOWED_EXTENSIONS` (falling back to `['.pdf', '.docx', '.txt']`).
- Normalises extensions (ensures leading dot, case-insensitive comparison).
- Raises `django.core.exceptions.ValidationError` if the extension is missing or not allowed.

#### `validate_file_size(file, max_size_mb=None)`
- Checks if the uploaded file's `size` attribute (bytes) is within the limit.
- If `max_size_mb` is not provided, reads from `settings.MAX_UPLOAD_SIZE` (default: 50 MB).
- Raises `django.core.exceptions.ValidationError` if the file exceeds the limit.

## Current state of the code

- The `documents/utils/` package is now created with the file validator module.
- The existing settings in `src/backend/config/settings.py` already define:
  - `MAX_UPLOAD_SIZE` (50 MB)
  - `ALLOWED_FILE_TYPES` (MIME types — note: the validator uses extensions, not MIME types; a future enhancement could add MIME-based validation)
- No changes were made to `models.py` or any other existing files.
- The storage abstraction layer from Phase 2 remains unchanged.

## Exact next step to be executed

Phase 3 is complete. The next phase (Phase 4) can proceed once the user confirms.
