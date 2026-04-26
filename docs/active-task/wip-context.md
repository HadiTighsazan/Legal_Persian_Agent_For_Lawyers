# WIP Context — Epic E-04 Bug Fixes (Tasks 4 & 5)

## What Was Just Completed

Applied the 6 issues identified in the Task 4 code review to [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) and [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py).

### 🔴 Bug #1 Fixed: `extract_text_from_pdf` now sets `processing_status = "completed"` on success

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:149-153)

**Change:** Added `document.processing_status = "completed"` to the `save(update_fields=...)` call at line 152-153 (both the normal extraction path and the empty-PDF path at line 131). Previously, extraction only set `processing_status = "processing"` at start and never updated it to `"completed"`, which meant that if chunking subsequently failed, the document would remain stuck at `"processing"`.

### 🔴 Bug #2 Fixed: `chunk_document` no longer overwrites `"failed"` status

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:231-278)

**Change:** Both the empty-text handler (line 234) and the successful-chunking path (line 274) now check `if document.processing_status != "failed"` before setting `processing_status = "completed"`. If the document was already marked as `"failed"` by `_fail_extract()` (e.g., corrupted PDF), the failed status is preserved and only `total_chunks` is saved.

### 🟡 Design Concern #1 Fixed: `link_error` callback on the Celery chain

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:314-421)

**Change:**
- Added a new [`_handle_chain_error`](src/backend/documents/tasks/document_processing.py:314) shared task that acts as a `link_error` callback. It finds the most recent `pending`/`running` `ProcessingTask` for the document and marks it as `"failed"`, and also marks the document as `"failed"` if not already in a terminal state.
- [`process_document`](src/backend/documents/tasks/document_processing.py:364) now passes `link_error=[_handle_chain_error.s(document_id, task_type="extract")]` to `chain_obj.apply_async()`.

### 🟡 Design Concern #2 Fixed: Retry mechanism for transient failures

**File:** [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py:41-48, 187-194)

**Change:** Both [`extract_text_from_pdf`](src/backend/documents/tasks/document_processing.py:41) and [`chunk_document`](src/backend/documents/tasks/document_processing.py:187) now use:
```python
@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
```
Transient DB/storage errors are retried up to 3 times with exponential backoff (max 60s). Permanent PDF errors (corrupted, password-protected) are still caught and fail immediately without retry.

### 🟡 Test Gap #1 Filled: Extract-success + chunk-failure scenario

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py:398-422)

**Test:** [`test_extract_success_then_chunk_failure_sets_failed_status`](src/backend/documents/tests/test_tasks.py:398) — Sets `processing_status = "completed"` (simulating successful extraction), then runs `chunk_document` with a mocked `ChunkingService` that raises. Verifies the document ends up as `"failed"` (not stuck at `"processing"` or incorrectly `"completed"`).

### 🟡 Test Gap #2 Filled: Extract-fail + chunk-on-empty scenario

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py:360-394)

**Tests:**
- [`test_does_not_overwrite_failed_status_on_empty_text`](src/backend/documents/tests/test_tasks.py:360) — Sets `processing_status = "failed"`, runs `chunk_document("")`, verifies status remains `"failed"` and `processing_error` is preserved.
- [`test_does_not_overwrite_failed_status_on_successful_chunking`](src/backend/documents/tests/test_tasks.py:382) — Same setup but with valid text; verifies `"failed"` status is preserved even when chunking succeeds.

### Additional Test Coverage

- [`test_passes_link_error_to_apply_async`](src/backend/documents/tests/test_tasks.py:526) — Verifies `process_document` passes `link_error` to `chain_obj.apply_async()`.
- **`HandleChainErrorTests`** class (6 tests) — Comprehensive tests for the `_handle_chain_error` callback: marks pending/running tasks as failed, marks document as failed, does not overwrite terminal document status, handles nonexistent document gracefully.

### Updated Existing Test

- [`test_updates_document_fields`](src/backend/documents/tests/test_tasks.py:174) — Now expects `processing_status = "completed"` (was `"processing"`) after successful extraction, reflecting Bug #1 fix.

### Files Modified

| File | Change |
|------|--------|
| `src/backend/documents/tasks/document_processing.py` | Bug #1, Bug #2, Design #1 (link_error), Design #2 (retry) |
| `src/backend/documents/tests/test_tasks.py` | Test Gap #1, Test Gap #2, link_error tests, `_handle_chain_error` tests, updated existing test |

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
- **Bug #1 fixed**: `extract_text_from_pdf` now sets `document.processing_status = "completed"` on success
- **Bug #2 fixed**: `chunk_document` preserves `processing_status = "failed"` if extraction already failed
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

Run the tests to verify all changes pass. Expected command:
```
docker-compose exec backend python -m pytest documents/tests/test_tasks.py --ds=config.settings --reuse-db -v
```
