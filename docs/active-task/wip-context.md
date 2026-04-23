# WIP Context — Phase 6: Upload API Endpoint (Epic E-03)

## What was just completed

### Task 6.1 — Created `documents/serializers.py`
- **File created:** `src/backend/documents/serializers.py`
- Implemented `DocumentUploadSerializer` — a DRF `Serializer` with a single `file` field (`FileField`) for basic request validation. Deeper type/size validation is delegated to the upload service.
- Implemented `DocumentResponseSerializer` — a DRF `Serializer` that mirrors the metadata dictionary returned by `upload_document()`, with fields: `id`, `title`, `original_filename`, `file_size`, `mime_type`, `file_path`, `storage_type`, `status`, `created_at`.

### Task 6.2 — Created `documents/views.py`
- **File created:** `src/backend/documents/views.py`
- Implemented `DocumentUploadView` (APIView) with a `POST` handler that:
  1. Validates the incoming `multipart/form-data` request using `DocumentUploadSerializer`.
  2. Calls `upload_document(user=request.user, file=uploaded_file)` from the Phase 5 service.
  3. Catches `django.core.exceptions.ValidationError` → returns `400 Bad Request`.
  4. Catches `StorageError` → returns `500 Internal Server Error`.
  5. Catches `RuntimeError` → returns `500 Internal Server Error`.
  6. On success, serializes the metadata with `DocumentResponseSerializer` and returns `201 Created`.
- Uses `IsAuthenticated` permission class (JWT auth is configured globally in settings).

### Task 6.3 — Created `documents/urls.py`
- **File created:** `src/backend/documents/urls.py`
- Registered the `upload/` route connected to `DocumentUploadView` with `app_name = "documents"` and URL name `document-upload`.

### Task 6.4 — Updated `config/urls.py`
- **File modified:** `src/backend/config/urls.py`
- Replaced the commented line `# path('api/v1/documents/', include('documents.urls', namespace='documents'))` with an active `path('documents/', include('documents.urls'))`.
- The `/api/` prefix is handled by Nginx (which proxies `/api/` → `http://backend/`, stripping the prefix), so the internal Django route is just `documents/`.

## Current state of the code

- The full upload API endpoint is wired up: `POST /api/documents/upload/` (external) → `POST /documents/upload/` (internal Django).
- All prior layers (storage, validators, repository, upload service) remain unchanged.
- The `documents` app is already registered in `INSTALLED_APPS`.

## Exact next step to be executed

Phase 6 is complete. The next phase can proceed once the user confirms.
