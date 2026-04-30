# E03 — Document Upload & Storage: Code Review Report

## Overview

This report analyzes the Epic E03 implementation (`Document Upload & Storage`) covering:
- File upload endpoint (`POST /documents/upload/`)
- S3/local storage abstraction
- Document metadata model
- File validation (type, size)
- Associated tests

## Architecture Summary

```
HTTP Request
    │
    ▼
DocumentUploadView (views.py)
    │  ┌─ DocumentUploadSerializer (validates file field exists)
    │  └─ upload_document() (services/upload_service.py)
    │       ├─ validate_file_type() (utils/file_validator.py)
    │       ├─ validate_file_size() (utils/file_validator.py)
    │       ├─ get_storage_backend() (storage/__init__.py → factory)
    │       │    ├─ LocalStorageBackend (storage/local.py)
    │       │    └─ S3StorageBackend (storage/s3.py)
    │       └─ create_document() (repositories/document_repository.py)
    │
    └─ DocumentResponseSerializer (serializes metadata → JSON)
```

## Findings

### ✅ Strengths

1. **Clean separation of concerns**: The upload flow is well-layered — view → service → validator/storage/repository. Each layer has a single responsibility.

2. **Comprehensive error handling**: The view catches `DjangoValidationError`, `StorageError`, and `RuntimeError` with appropriate HTTP status codes (400, 500).

3. **Good test coverage**: Integration tests cover all major paths:
   - Valid PDF upload → 201
   - Invalid file type → 400
   - Oversized file → 400
   - Storage failure → 500
   - Unauthenticated → 401

4. **Storage abstraction**: The factory pattern in [`storage/__init__.py`](src/backend/documents/storage/__init__.py) cleanly abstracts backend selection via `settings.STORAGE_TYPE`.

5. **Directory traversal protection**: [`LocalStorageBackend._resolve_path()`](src/backend/documents/storage/local.py:43) sanitizes paths and prevents escape from the storage root.

6. **Consistent error response format**: All views return structured `{"error": "...", "message": "..."}` responses.

### ⚠️ Issues Found

#### 1. Mismatch: `ALLOWED_FILE_TYPES` (MIME) vs `ALLOWED_EXTENSIONS` (extension)

**File**: [`settings.py`](src/backend/config/settings.py:283) and [`file_validator.py`](src/backend/documents/utils/file_validator.py:38)

The setting is named `ALLOWED_FILE_TYPES` and contains MIME types (`application/pdf`, etc.), but the validator's default parameter is `ALLOWED_EXTENSIONS` and expects file extensions (`.pdf`, `.docx`, `.txt`). The validator normalizes by adding dots, but the MIME types from settings will never match.

```python
# settings.py:283
ALLOWED_FILE_TYPES = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']

# file_validator.py:38 — reads ALLOWED_EXTENSIONS, not ALLOWED_FILE_TYPES
allowed_types = getattr(settings, "ALLOWED_EXTENSIONS", [".pdf", ".docx", ".txt"])
```

**Impact**: The default validation always falls back to `[".pdf", ".docx", ".txt"]` regardless of what's in `ALLOWED_FILE_TYPES`. The setting `ALLOWED_FILE_TYPES` is effectively dead code.

**Severity**: Medium — the fallback works, but the setting is misleading.

#### 2. `upload_document()` catches bare `Exception` in Step 5

**File**: [`upload_service.py`](src/backend/documents/services/upload_service.py:137)

```python
except Exception as exc:
    logger.exception(...)
    raise RuntimeError(...) from exc
```

Catching bare `Exception` is too broad. If a `StorageError` or `ValidationError` were to somehow propagate here (they shouldn't based on the flow, but defensive coding is better), they'd be wrapped in a `RuntimeError` and returned as 500 instead of their intended status codes.

**Severity**: Low — the flow ensures storage errors are raised before this point, but it's a code smell.

#### 3. `DocumentUploadSerializer` does not validate file type/size at the DRF level

**File**: [`serializers.py`](src/backend/documents/serializers.py:13)

The serializer only ensures a file is present. All type/size validation happens in the service layer. This means:
- The serializer's `is_valid()` can pass for invalid files
- Error messages come from the service layer, not DRF's built-in validation
- The OpenAPI schema (if generated) won't reflect type/size constraints

**Severity**: Low — the validation still happens, just not at the serializer level. This is a design choice, not a bug.

#### 4. `DocumentResponseSerializer` uses `serializers.Serializer` instead of `ModelSerializer`

**File**: [`serializers.py`](src/backend/documents/serializers.py:26)

The response serializer manually mirrors the `Document` model fields rather than using `ModelSerializer`. This creates a maintenance burden — if the model changes, the serializer must be manually updated.

**Severity**: Low — it works, but is more brittle than necessary.

#### 5. `_guess_mime_type()` uses `mimetypes.guess_type()` which is unreliable

**File**: [`upload_service.py`](src/backend/documents/services/upload_service.py:24)

```python
def _guess_mime_type(original_filename: str) -> str:
    mime_type, _ = mimetypes.guess_type(original_filename)
    return mime_type or "application/octet-stream"
```

The `mimetypes` module relies on the OS registry and may return incorrect or `None` values. For example, `.docx` files may not be recognized on all systems.

**Severity**: Low — falls back to `application/octet-stream`, but this could be improved by using a curated mapping.

#### 6. `S3StorageBackend.open()` returns raw `StreamingBody` instead of `BytesIO`

**File**: [`storage/s3.py`](src/backend/documents/storage/s3.py:126)

```python
def open(self, storage_path: str) -> BinaryIO:
    ...
    return response["Body"]  # Raw StreamingBody
```

The `LocalStorageBackend.open()` returns `io.BytesIO(f.read())` (an in-memory buffer), but `S3StorageBackend.open()` returns the raw `StreamingBody`. This inconsistency could cause issues for consumers that expect a full `BytesIO`-like object (e.g., seeking, `.read()` after partial consumption).

**Severity**: Medium — if code relies on `BytesIO` behavior (like `chunking_service.py` which uses PyMuPDF), the S3 path may fail at runtime.

#### 7. `Document` model has two status fields with overlapping semantics

**File**: [`models.py`](src/backend/documents/models.py:13)

The model has `status` (upload lifecycle: uploaded/processing/completed/failed) and `processing_status` (pipeline granular: pending/processing/completed/failed). The docstring explains the distinction, but having two fields tracking similar states is confusing and increases the chance of bugs where one is updated but not the other.

**Severity**: Low — documented, but adds cognitive overhead.

#### 8. `DocumentChunksListView` implements manual pagination instead of using DRF's paginators

**File**: [`views.py`](src/backend/documents/views.py:386-425)

The view manually parses `page`/`page_size`, computes offsets, and builds the paginated response. DRF provides `PageNumberPagination` which would handle all of this with less code and better consistency.

**Severity**: Low — works correctly, but is more code to maintain.

#### 9. `validate_file_size()` uses `file.size` but the type hint says `UploadedFile | file-like`

**File**: [`file_validator.py`](src/backend/documents/utils/file_validator.py:63)

The function accepts a generic `file` parameter and accesses `.size`. Not all file-like objects have a `.size` attribute (e.g., `BytesIO` doesn't). This could fail silently or with an `AttributeError` if used outside the upload context.

**Severity**: Low — in practice, Django's `UploadedFile` always has `.size`.

#### 10. No cleanup on database creation failure

**File**: [`upload_service.py`](src/backend/documents/services/upload_service.py:126-144)

If the file is saved to storage (Step 4) but the database record creation fails (Step 5), the file remains orphaned in storage. There's no cleanup/rollback mechanism.

**Severity**: Medium — leads to storage leaks over time.

### 📋 Summary Table

| # | Issue | Severity | File | Line |
|---|-------|----------|------|------|
| 1 | `ALLOWED_FILE_TYPES` vs `ALLOWED_EXTENSIONS` mismatch | Medium | `settings.py` / `file_validator.py` | 283 / 38 |
| 2 | Bare `Exception` catch in upload_service | Low | `upload_service.py` | 137 |
| 3 | Serializer doesn't validate file type/size | Low | `serializers.py` | 13 |
| 4 | Manual serializer instead of ModelSerializer | Low | `serializers.py` | 26 |
| 5 | `mimetypes.guess_type()` unreliable | Low | `upload_service.py` | 24 |
| 6 | S3 `open()` returns raw `StreamingBody` (not `BytesIO`) | Medium | `storage/s3.py` | 126 |
| 7 | Two overlapping status fields | Low | `models.py` | 13 |
| 8 | Manual pagination instead of DRF paginator | Low | `views.py` | 386 |
| 9 | `file.size` assumption in validator | Low | `file_validator.py` | 88 |
| 10 | No cleanup on DB creation failure | Medium | `upload_service.py` | 126-144 |

### 🎯 Recommended Actions

1. **Fix the `ALLOWED_FILE_TYPES`/`ALLOWED_EXTENSIONS` mismatch** — Either rename the setting to `ALLOWED_EXTENSIONS` and use extensions, or change the validator to check MIME types. The current state is misleading.

2. **Make `S3StorageBackend.open()` return `BytesIO`** — Wrap the `StreamingBody` in `io.BytesIO(response["Body"].read())` to match the local backend's contract.

3. **Add storage cleanup on DB failure** — In `upload_service.py`, if `create_document()` fails, delete the saved file from storage before raising the error.

4. **Consider using DRF's `PageNumberPagination`** in `DocumentChunksListView` to reduce boilerplate.

5. **Consider using `ModelSerializer`** for `DocumentResponseSerializer` to reduce maintenance burden.

### 🧪 Test Quality Assessment

| Aspect | Rating | Notes |
|--------|--------|-------|
| Coverage | ✅ Excellent | All major paths covered (success, invalid type, oversized, storage failure, unauthenticated) |
| Edge cases | ✅ Good | Empty chunks, pagination, ownership checks, processing status transitions |
| Mock usage | ✅ Appropriate | Storage backend mocked for failure test; `process_document` mocked for process view |
| Test isolation | ✅ Good | Each test creates its own user and document |
| Readability | ✅ Excellent | Well-named tests with clear docstrings and Arrange/Act/Assert structure |

### ✅ Conclusion

The E03 implementation is **solid and production-ready**. The architecture is clean, error handling is comprehensive, and test coverage is excellent. The issues identified are mostly minor (low severity) with two medium-severity items worth addressing:

1. **The `ALLOWED_FILE_TYPES`/`ALLOWED_EXTENSIONS` mismatch** should be fixed to avoid confusion.
2. **The S3 `open()` inconsistency** could cause runtime failures if the S3 backend is used with code expecting `BytesIO`.
3. **The missing storage cleanup on DB failure** could lead to orphaned files over time.

None of these issues are blockers — the code works correctly with the local storage backend (which is the default), and all tests pass.
