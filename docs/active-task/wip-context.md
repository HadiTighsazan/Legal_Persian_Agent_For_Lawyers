# WIP Context — Epic E-04 Bug Fixes (Tasks 4 & 5)

## What Was Just Completed

**Phase 3 (Cleanup) of the Task 5 refactoring plan** — 3 changes across 4 files.

### Change #8: Moved `process_document` to services module

**Files:**
- [`src/backend/documents/services/processing_service.py`](src/backend/documents/services/processing_service.py:174) — Added `process_document()` function with lazy imports to avoid circular deps
- [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) — Removed `process_document` function body, replaced with docstring noting the move
- [`src/backend/documents/tasks/__init__.py`](src/backend/documents/tasks/__init__.py) — Updated to re-export `process_document` from the service module for backward compatibility

**Rationale:** `process_document` is a regular Python function (not a Celery task), so it belongs in the services layer alongside the other processing-service functions. The tasks module should only contain actual Celery tasks (`@shared_task`). A backward-compatible re-export via `tasks/__init__.py` ensures no import breakage for existing callers.

**Circular import handling:** The function uses lazy imports inside its body:
```python
from documents.tasks.document_processing import (
    _handle_chain_error, chunk_document, extract_text_from_pdf,
)
```
This avoids the circular dependency: `processing_service → tasks.document_processing → processing_service`.

### Change #9: Documented `status` vs `processing_status` in model docstring

**File:** [`src/backend/documents/models.py`](src/backend/documents/models.py:12)

Updated the `Document` model docstring to clarify the distinction between the two status fields:

| Field | Purpose | Values |
|-------|---------|--------|
| `status` | Upload lifecycle — source of truth for API consumers | `uploaded`, `processing`, `completed`, `failed` (choices) |
| `processing_status` | Pipeline granular state — set by Celery tasks, being superseded by `ProcessingTask` model | `pending`, `processing`, `completed`, `failed` (free text) |

### Change #10: Added serializer unit tests

**New file:** [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py)

Added **28 test cases** across 4 test classes:

| Test Class | Tests | Coverage |
|-----------|-------|----------|
| `DocumentUploadSerializerTests` | 4 | Valid file, missing file, null file, help_text |
| `DocumentResponseSerializerTests` | 7 | Valid data, serialized output, missing id/title/status, invalid UUID, help_text on all fields |
| `ProcessingTaskSerializerTests` | 8 | Valid data, serialized output, error_message as string, missing task_type/status/progress, non-integer progress, help_text on all fields |
| `ProcessingStatusSerializerTests` | 9 | Valid data, serialized output, missing document_id/status/progress/tasks, empty tasks list, invalid task entry, help_text on all fields |

### Additional Fix: Updated `test_tasks.py` imports and mock paths

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py)

- Updated `process_document` import from `documents.tasks.document_processing` to `documents.tasks` (re-export)
- Updated mock paths from `documents.tasks.document_processing.chain` to `documents.services.processing_service.chain` (since `process_document` now lives in the service module)
- Updated `test_updates_document_fields` assertion: `processing_status` is now `"processing"` (not `"completed"`) after extraction alone, since `chunk_document` is responsible for setting the terminal status

### Files Modified/Created

| File | Change |
|------|--------|
| `src/backend/documents/services/processing_service.py` | Added `process_document()` function with lazy imports |
| `src/backend/documents/tasks/document_processing.py` | Removed `process_document` body, replaced with docstring |
| `src/backend/documents/tasks/__init__.py` | Re-export `process_document` from service module |
| `src/backend/documents/models.py` | Updated `Document` docstring with `status` vs `processing_status` clarification |
| `src/backend/documents/tests/test_serializers.py` | **NEW** — 28 serializer unit tests |
| `src/backend/documents/tests/test_tasks.py` | Updated imports, mock paths, and assertion for new `process_document` location |

### Test Results

- **All 83 tests pass** (0 failures, 0 errors)
- Tests run via: `docker-compose exec backend python -m pytest documents/tests/ --ds=config.settings`

---

## E04-T4-T5 Bug Fixes — Authentication & User Management (2026-04-25)

### Bugs Fixed

#### Bug #1 (Critical): Password field/property setter in `users/models.py`
- **Problem**: The `User` model used a custom `password_hash` field with a `@property password` getter/setter that bypassed Django's native password hashing. The setter had flawed logic that couldn't reliably detect raw vs. already-hashed passwords.
- **Fix**:
  - Removed `password_hash = models.CharField(max_length=255)` field
  - Removed `@property password` getter and `@password.setter`
  - Removed custom `set_password()` method
  - Django's `AbstractBaseUser` now provides the `password` field natively with proper `set_password()` and `check_password()` methods
  - Created migration `0002_rename_password_hash_to_password.py` with `RenameField` and `AlterField` (max_length=128)

#### Bug #2 (Medium): Duplicate `JWTAuthenticationMiddleware` in settings.py
- **Problem**: Both `users.middleware.JWTAuthenticationMiddleware` (in MIDDLEWARE) and DRF's `JWTAuthentication` (in `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`) were configured, causing redundant authentication checks.
- **Fix**: Removed `'users.middleware.JWTAuthenticationMiddleware'` from `MIDDLEWARE`. DRF's `JWTAuthentication` now handles all JWT authentication. The middleware file is preserved with a deprecation warning.

#### Bug #3 (Medium): Refresh token rotation not implemented
- **Problem**: The `refresh_view` generated a new access token but did not revoke the old refresh token or issue a new one, meaning refresh tokens were reusable indefinitely.
- **Fix**: Implemented full refresh token rotation:
  - Revokes the old refresh token (deletes from DB)
  - Generates a new refresh token with a new UUID
  - Stores the new token hash in the `refresh_tokens` table
  - Returns both `accessToken` and `refreshToken` in the response

#### Issue #3 (Medium): Hardcoded `timedelta(days=7)` in views.py
- **Problem**: Both `register_view` and `login_view` used hardcoded `timedelta(days=7)` for refresh token expiry instead of reading from settings.
- **Fix**: Replaced with `settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']` in both views.

#### Issue #7 (Low): Duplicate URL inclusion in urls.py
- **Problem**: `config/urls.py` had two identical `path('users/', include('users.urls'))` lines.
- **Fix**: Removed the duplicate. Added direct `path('users/me/', users_views.profile_view, name='users-profile')` with proper import.

### Additional Cleanup
- **Removed** `rest_framework_simplejwt.token_blacklist` from `INSTALLED_APPS` (revocation handled via custom `RefreshToken` model)
- **Removed** `BlacklistedToken` import from `jwt_utils.py`
- **Simplified** `is_token_blacklisted()` to always return `False`
- **Updated** `test_models.py` to use `user.password` instead of `user.password_hash`
- **Updated** `test_views.py` to check for `'detail'` key (DRF format) instead of `'error'` in `test_logout_requires_authentication`
- **Updated** `test_middleware_integration.py` to use `/users/me/` URL and DRF response format

### Files Modified
| File | Change |
|------|--------|
| `src/backend/users/models.py` | Removed `password_hash` field, custom property/setter, custom `set_password()` |
| `src/backend/users/migrations/0002_rename_password_hash_to_password.py` | New migration: rename `password_hash` → `password`, alter to VARCHAR(128) |
| `src/backend/config/settings.py` | Removed middleware from MIDDLEWARE, removed `token_blacklist` from INSTALLED_APPS |
| `src/backend/users/middleware.py` | Added deprecation warning |
| `src/backend/users/views.py` | Refresh token rotation, replaced hardcoded `timedelta(days=7)` with settings |
| `src/backend/config/urls.py` | Removed duplicate `include('users.urls')`, added direct `/users/me/` path |
| `src/backend/users/jwt_utils.py` | Removed `BlacklistedToken` import, simplified `is_token_blacklisted()` |
| `src/backend/users/tests/test_models.py` | Updated `test_password_hashing` to use `user.password` |
| `src/backend/users/tests/test_views.py` | Updated `test_logout_requires_authentication` for DRF format |
| `src/backend/users/tests/test_middleware_integration.py` | Updated URLs and assertions for DRF auth |

### Test Results
- **All 117 tests pass** (0 failures, 0 errors)
- Tests run via: `docker-compose exec backend python -m pytest --ds=config.settings --reuse-db`

### Reference Documentation Updated
- **`docs/references/database-schema.md`**: Updated `password` column type to VARCHAR(128), added migration note for 0002
- **`docs/references/api-registry.md`**: Updated refresh endpoint to document rotation (returns `refreshToken`), updated middleware notes, added DRF error format, added configuration changes section

## Current State of Code

- `process_document` is a regular function (not a Celery task) — now lives in `documents/services/processing_service.py`, called directly from `DocumentProcessView.post()`
- `chunk_document` creates its own `ProcessingTask` with `task_type="chunk"` and manages its own lifecycle
- `extract_text_from_pdf` manages the "extract" ProcessingTask — uses `status="pending"` lookup for robustness
- The Celery chain still works: `extract_text_from_pdf → chunk_document`, with extracted text passed as first arg
- **Phase 1 bugs fixed**: `None` return handled, premature `processing_status` removed, `display_status` computed from tasks, redundant check removed
- **Phase 2 architecture**: `AsyncResult` healing extracted to `processing_service.py`, view is ~20 lines, 25 new test cases
- **Phase 3 cleanup**: `process_document` moved to services module, model docstring clarifies `status` vs `processing_status`, 28 serializer unit tests added
- **Bug #2 (original) fixed**: `chunk_document` preserves `processing_status = "failed"` if extraction already failed
- **Design #1 fixed**: `_handle_chain_error` callback catches chain-level failures via `link_error`
- **Design #2 fixed**: Both tasks have `autoretry_for` with exponential backoff for transient DB/storage errors
- Error responses follow the API registry format
- Celery `AsyncResult` healing prevents stale "running" statuses
- PDF path resolution works for both relative and absolute paths
- User model uses Django's native `AbstractBaseUser` password field with proper hashing
- JWT authentication is handled entirely by DRF's `JWTAuthentication` (no custom middleware)
- Refresh token rotation is fully implemented (old token revoked, new token issued on each refresh)
- Refresh token lifetime is configurable via `SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']`

## Exact Next Step

All 3 phases of the Task 5 refactoring plan are complete. The full documents test suite (83 tests) and users test suite (117 tests) both pass.

To verify:
```
docker-compose exec backend python -m pytest documents/tests/ users/tests/ --ds=config.settings
```
