# WIP Context - Epic E02 Authentication & User Management

## Current Status: DEBUG FIX - test_public_endpoints_with_invalid_token ✅

**Last Updated:** 2026-04-23 13:13 (UTC+3:30)
**Current Epic:** Epic E02 - Authentication & User Management
**Current Task:** Debug Fix - test_public_endpoints_with_invalid_token (FIXED ✅)

---

## What Was Just Completed:

### Bug Fix: test_public_endpoints_with_invalid_token

**Root Cause:**
The test `test_public_endpoints_with_invalid_token` sends a POST to `/auth/login/` with `Authorization: Bearer invalid_token` and expects a `400` response (from the view logic for missing email/password). Instead, it received `401`.

The issue was **not** in the custom `JWTAuthenticationMiddleware` — that middleware correctly checks public endpoints first and bypasses authentication for `/auth/login/`.

The real problem was **DRF's `rest_framework_simplejwt.authentication.JWTAuthentication`** (configured in `settings.py` as the default authentication class). When DRF processes a view, it runs **Authentication before Permissions**. If an `Authorization` header is present but the token is invalid, SimpleJWT's `JWTAuthentication` raises `AuthenticationFailed` immediately (resulting in a 401), **before** the `@permission_classes([AllowAny])` decorator or the view logic is ever reached.

**Fix Applied:**
Added `@authentication_classes([])` decorator to the three public views in [`src/backend/users/views.py`](src/backend/users/views.py):
- `register_view` (line 33)
- `login_view` (line 164)
- `refresh_view` (line 409)

This tells DRF to skip all authentication for these endpoints, so even if an invalid token is present in the `Authorization` header, the request proceeds to the view logic without raising a 401.

**Files Modified:**
- [`src/backend/users/views.py`](src/backend/users/views.py): Added `authentication_classes` import and `@authentication_classes([])` decorator to `register_view`, `login_view`, and `refresh_view`.

**Test Results:**
- ✅ `test_public_endpoints_with_invalid_token` — PASSED
- ✅ All 6 middleware integration tests — PASSED
- ✅ All 59 view tests — PASSED (no regression)

### Next Steps:
- Continue with remaining Epic E02 tasks as planned
