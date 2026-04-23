# WIP Context — Phase 7: Integration Tests for Upload API (Epic E-03)

## What was just completed

### Task 7.1 — Created `src/backend/tests/test_upload_integration.py`
- **File created:** `src/backend/tests/test_upload_integration.py`
- Implemented `DocumentUploadIntegrationTests` (Django `TestCase`) with **5 test cases** covering the full upload workflow:

  1. **`test_valid_pdf_upload_returns_201`** — Uploads a valid PDF-like file, asserts `201 Created`, verifies the response shape (all 9 expected keys), checks response values (`original_filename`, `mime_type`, `file_size`, `status`, `storage_type`), and confirms the `Document` DB record was created with correct field values.

  2. **`test_invalid_file_type_returns_400`** — Uploads a `.exe` file, asserts `400 Bad Request`, and verifies the error message mentions the invalid extension.

  3. **`test_file_too_large_returns_400`** — Uploads a file 1 byte over `settings.MAX_UPLOAD_SIZE` (50 MB), asserts `400 Bad Request`, and verifies the error message references the size limit.

  4. **`test_storage_failure_returns_500`** — Uses `unittest.mock.patch` to mock `get_storage_backend` so that `save_file` raises `StorageError("Disk full — cannot write file")`, asserts `500 Internal Server Error`, and verifies the error message contains "Storage error". Also asserts the mocked method was called once.

  5. **`test_unauthenticated_request_returns_401`** — Makes a request via a fresh `APIClient` (no JWT token), asserts `401 Unauthorized`, and verifies the response contains an `error` key.

- Test setup creates a test `User`, generates a valid JWT access token via `generate_access_token()`, and authenticates the client with `HTTP_AUTHORIZATION: Bearer {token}` for tests 1-4.
- Uses `SimpleUploadedFile` for multipart upload simulation.

## Current state of the code

- All 5 integration tests **pass** successfully when run inside the Docker container:
  ```
  docker compose exec backend python -m pytest tests/test_upload_integration.py -v --ds=config.settings
  ```
  Output: **5 passed, 2 warnings** (warnings are pre-existing deprecation notices for `STATICFILES_STORAGE` and `drf_yasg`).

- The upload endpoint (`POST /documents/upload/`) is fully integrated and tested end-to-end.

## Exact next step to be executed

Phase 7 is complete. The epic E-03 (Upload API) is now fully implemented and tested. The next epic/phase can proceed once the user confirms.
