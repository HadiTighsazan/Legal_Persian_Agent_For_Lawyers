# WIP Context — Epic E-04 Bug Fixes (Tasks 4 & 5)

## What Was Just Completed

Applied comprehensive bug fixes to Tasks 4 (Celery Tasks) and 5 (Processing Status API) of Epic E-04. All 12 identified bugs were addressed across 3 phases.

### Files Modified

1. **`src/backend/documents/tasks/document_processing.py`** — Major refactor:
   - **Bug #2**: Removed `@shared_task(bind=True)` from `process_document` — it's now a regular Python function called directly from the view, eliminating the deadlock risk of a Celery task submitting `apply_async()`.
   - **Bug #3**: `chunk_document` now creates its own `ProcessingTask` with `task_type="chunk"` instead of reusing/modifying the "extract" task's status.
   - **Bug #6**: PDF path resolution now checks `os.path.isabs()` first before joining with `MEDIA_ROOT`, fixing the issue for absolute paths returned by local storage.
   - **Bug #5**: `process_document` now checks for both `"processing"` AND `"completed"` status to prevent duplicate processing.
   - **Bug #12**: Improved error message for corrupted PDFs to "PDF file is corrupted or unreadable".

2. **`src/backend/documents/views.py`** — Major refactor:
   - **Bug #4**: Removed `.delay()` call since `process_document` is no longer a Celery task. Now calls `process_document()` directly and uses its return value (the chain's task ID).
   - **Bug #5**: Added check for `"completed"` status alongside `"processing"` to prevent re-processing.
   - **Bug #7**: Added Celery `AsyncResult` healing mechanism — checks real-time Celery state for tasks stuck at "running"/"pending" and updates DB accordingly.
   - **Bug #8**: Status view now returns `"pending"` when no ProcessingTasks exist (document hasn't been processed yet), vs using `document.processing_status` directly.
   - **Bug #10**: Replaced `get_object_or_404` with explicit `try/except Document.DoesNotExist` returning proper JSON error responses.
   - **Bug #11**: Standardized all error responses to `{"error": "error_code", "message": "..."}` format matching the API registry.

3. **`src/backend/documents/tests/test_tasks.py`** — Updated tests:
   - **Bug #1**: Fixed `chunk_document` test calls to match the correct argument order: `chunk_document(extracted_text, document_id)`.
   - **Bug #3**: Added `test_creates_chunk_processing_task` to verify a "chunk" ProcessingTask is created.
   - **Bug #5**: Added `test_skips_if_already_completed` test.
   - Updated `process_document` tests since it's no longer a Celery task (no `.delay()` mock needed).

4. **`src/backend/tasks/models.py`** — **Bug #9**: Removed `unique=True` from `celery_task_id`, replaced with `db_index=True`.

5. **`src/backend/tasks/migrations/0002_alter_celery_task_id_unique.py`** — New migration for the `celery_task_id` constraint change.

### Reference Documentation Updated

6. **`docs/references/database-schema.md`** — Updated `celery_task_id` description to reflect removed UNIQUE constraint.
7. **`docs/references/api-registry.md`** — Updated implementation notes for `POST /documents/{id}/process/` to reflect new behavior.

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

- `process_document` is a regular function (not a Celery task) — called directly from `DocumentProcessView.post()`
- `chunk_document` creates its own `ProcessingTask` with `task_type="chunk"` and manages its own lifecycle
- `extract_text_from_pdf` manages the "extract" ProcessingTask as before
- The Celery chain still works: `extract_text_from_pdf → chunk_document`, with extracted text passed as first arg
- Error responses follow the API registry format
- Celery `AsyncResult` healing prevents stale "running" statuses
- PDF path resolution works for both relative and absolute paths
- User model uses Django's native `AbstractBaseUser` password field with proper hashing
- JWT authentication is handled entirely by DRF's `JWTAuthentication` (no custom middleware)
- Refresh token rotation is fully implemented (old token revoked, new token issued on each refresh)
- Refresh token lifetime is configurable via `SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']`
- All 117 tests pass

## Exact Next Step

No pending steps. All bugs are fixed and all tests pass.
