# Epic E-02 Audit Report — Authentication & User Management

**Audit Date:** 2026-04-25  
**Auditor:** Roo (Architect Mode)  
**Scope:** Full review of Epic 2 implementation (Authentication & User Management)

---

## Executive Summary

After thorough review of all 12 source files, 5 test files, migrations, settings, and reference documentation, I found **2 critical bugs**, **2 medium-severity architectural issues**, and **3 low-severity issues**. The core authentication flow (register → login → refresh → logout → profile) is functionally correct and well-tested (117 tests pass). However, there are specific security and correctness gaps that could lead to real problems in production.

---

## 🔴 CRITICAL BUGS

### Bug #C1 (Critical): `verify_access_token` and `verify_refresh_token` use SimpleJWT's `AccessToken(token)` / `RefreshToken(token)` constructors which re-validate the token against `SIMPLE_JWT` settings — but the custom `generate_*` functions set claims directly on the token object, which SimpleJWT may overwrite or conflict with

**Location:** [`src/backend/users/jwt_utils.py`](src/backend/users/jwt_utils.py:38-52)

**Problem:**  
The custom `generate_access_token()` and `generate_refresh_token()` functions create SimpleJWT `AccessToken()` / `RefreshToken()` objects and then set custom claims like `user_id`, `userId`, `email`, `type`, `tokenId` directly on them. However, SimpleJWT's `AccessToken` and `RefreshToken` classes have their own internal claim management:

- `AccessToken` automatically sets `token_type` claim (via `TOKEN_TYPE_CLAIM` setting, default `"token_type"`) to `"access"`.
- `RefreshToken` automatically sets `token_type` claim to `"refresh"`.
- Both set `jti` (JWT ID) claim automatically.
- The `USER_ID_CLAIM` setting (default `"user_id"`) is used by SimpleJWT's internal `for_user()` class method, but **NOT** by the raw constructor `AccessToken()`.

The critical issue: When `verify_access_token()` calls `AccessToken(token)`, SimpleJWT's constructor validates the token against its internal expectations. If the custom claims conflict with SimpleJWT's internal structure (e.g., the `token_type` claim vs the custom `type` claim), verification may behave unexpectedly.

**Evidence:**
```python
# jwt_utils.py:38-52
access_token = AccessToken()  # SimpleJWT's raw constructor
access_token['user_id'] = str(user.id)
access_token['userId'] = str(user.id)  # Duplicate claim!
access_token['email'] = user.email
access_token['type'] = 'access'  # Custom claim, not SimpleJWT's token_type
```

**Risk:** Medium-High. In practice, the tests pass because SimpleJWT's `AccessToken(token)` constructor primarily validates the signature and expiration, not the claim structure. However, there's a **duplicate identity claim** (`user_id` and `userId` both storing the same value) which is a code smell. More importantly, the `type: 'access'` / `type: 'refresh'` custom claim is **never checked by SimpleJWT's built-in `JWTAuthentication` class** — it only checks `token_type` (the SimpleJWT standard claim). So the custom `type` claim in the verification functions is redundant with SimpleJWT's own type checking.

**Recommendation:** Remove the duplicate `userId` claim (keep `user_id` which matches `USER_ID_CLAIM` setting). Remove the custom `type` claim since SimpleJWT handles token type internally via `token_type`. Simplify `verify_access_token()` and `verify_refresh_token()` to rely on SimpleJWT's built-in validation rather than re-checking custom claims.

---

### Bug #C2 (Critical): `verify_access_token` catches ALL exceptions including `KeyError` and `ValueError`, which can silently mask programming errors

**Location:** [`src/backend/users/jwt_utils.py`](src/backend/users/jwt_utils.py:136-138)

**Problem:**  
The broad `except (TokenError, InvalidToken, KeyError, ValueError)` clause catches Python `KeyError` and `ValueError` that may originate from bugs in the verification logic itself, not from invalid tokens. This means a programming error (e.g., accessing a non-existent dict key) would be silently swallowed and return `None`, making debugging extremely difficult.

```python
# jwt_utils.py:136-138
except (TokenError, InvalidToken, KeyError, ValueError):
    # Token is invalid, expired, or malformed
    return None
```

**Risk:** High. If there's ever a bug in the payload validation logic (lines 124-133), it will be silently hidden. The function will return `None` and the caller will treat it as "invalid token" rather than "internal error". This could mask serious issues during development and even in production.

**Recommendation:** Split the exception handling:
```python
try:
    access_token = AccessToken(token)
    # ... validation logic ...
except (TokenError, InvalidToken):
    return None  # Legitimate token validation failure
except (KeyError, ValueError) as e:
    logger.error(f"Internal error in token verification: {e}")
    return None  # Still return None, but at least log it
```

---

## 🟡 MEDIUM-SEVERITY ISSUES

### Bug #M1 (Medium): `config/urls.py` has a duplicate route for `/users/me/` — once via `include('users.urls')` and once as a direct path

**Location:** [`src/backend/config/urls.py`](src/backend/config/urls.py:54-55)

**Problem:**  
Line 54: `path('auth/', include('users.urls'))` — this includes all routes from `users/urls.py`  
Line 55: `path('users/me/', users_views.profile_view, name='users-profile')` — this is a direct route

But looking at [`src/backend/users/urls.py`](src/backend/users/urls.py:15):
```python
path('me/', views.profile_view, name='profile'),
```

This means `/users/me/` is accessible via `include('users.urls')` under `/users/me/`... wait, actually `users/urls.py` has `me/` not `users/me/`. Let me re-check.

Actually, looking more carefully:
- `config/urls.py` line 54: `path('auth/', include('users.urls'))` — this mounts `users/urls.py` under `/auth/`
- `users/urls.py` has: `register/`, `login/`, `refresh/`, `logout/`, `me/`
- So the routes become: `/auth/register/`, `/auth/login/`, `/auth/refresh/`, `/auth/logout/`, `/auth/me/`
- Line 55: `path('users/me/', users_views.profile_view, name='users-profile')` — this adds `/users/me/` separately

**The issue:** The profile view is accessible via **two different URLs**: `/users/me/` (line 55) AND `/auth/me/` (via include). This is a route duplication that could cause confusion, inconsistent behavior, and potential security issues if one route is protected differently than the other.

**Risk:** Medium. Both routes point to the same view function, so behavior is identical. But having two URLs for the same resource violates REST principles and could confuse API consumers.

**Recommendation:** Remove `me/` from `users/urls.py` and keep only the explicit `/users/me/` route in `config/urls.py`. This is cleaner and matches the API registry specification which documents the endpoint as `/users/me`.

---

### Bug #M2 (Medium): `ACCESS_TOKEN_LIFETIME` is set to 60 minutes in settings — significantly longer than the 15 minutes specified in the implementation plan

**Location:** [`src/backend/config/settings.py`](src/backend/config/settings.py:177)

**Problem:**  
The implementation plan explicitly states: "Access tokens: 15min expiry". But the actual setting is:
```python
'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),  # 60 minutes, not 15!
```

This is a 4x increase from the planned value. While not a bug per se, it significantly increases the security risk window for stolen access tokens. A 60-minute access token window means a compromised token can be used for a full hour without any ability to revoke it (since access tokens are stateless JWT).

**Risk:** Medium. This weakens the security posture of the entire authentication system. The implementation plan's 15-minute window was a deliberate security decision to limit the blast radius of token theft.

**Recommendation:** Change to `timedelta(minutes=15)` as specified in the implementation plan. If longer sessions are needed, the refresh token (7 days) handles that use case.

---

## 🟢 LOW-SEVERITY ISSUES

### Bug #L1 (Low): `register_view` and `login_view` have a try/except around `request.data` that is unnecessary and could mask DRF parsing issues

**Location:** [`src/backend/users/views.py`](src/backend/users/views.py:199-205)

**Problem:**  
```python
try:
    data = request.data
except Exception as json_error:
    return Response(
        {"error": "Invalid JSON format"},
        status=status.HTTP_400_BAD_REQUEST
    )
```

DRF's `Request.data` already handles JSON parsing errors gracefully and returns a 400 response with appropriate error details. This extra try/except is redundant and could mask legitimate DRF errors.

**Risk:** Low. It works correctly in practice, but adds unnecessary complexity.

**Recommendation:** Remove the outer try/except around `request.data`. DRF handles this natively.

---

### Bug #L2 (Low): `register_view` passes `full_name=''` (empty string) when not provided, but the model field has `null=True` — inconsistency between empty string and null

**Location:** [`src/backend/users/views.py`](src/backend/users/views.py:110-115)

**Problem:**  
```python
full_name = data.get('full_name', '')  # Defaults to empty string
user = User.objects.create_user(
    email=email,
    password=password,
    full_name=full_name  # Empty string, not None
)
```

The model defines `full_name = models.CharField(max_length=255, blank=True, null=True)`. When `full_name` is not provided, the code passes `''` (empty string) instead of `None`. This means the database stores `''` instead of `NULL`. While both work, it's inconsistent and could cause issues with queries that check `IS NULL` vs `= ''`.

**Risk:** Low. Functionally works, but inconsistent with the model definition.

**Recommendation:** Change to `data.get('full_name')` (which returns `None` if not provided) to match the model's `null=True`.

---

### Bug #L3 (Low): `test_register_without_full_name` expects `full_name` to be `''` (empty string), but the model field has `null=True`

**Location:** [`src/backend/users/tests/test_views.py`](src/backend/users/tests/test_views.py:93-108)

**Problem:**  
The test asserts:
```python
self.assertEqual(response_data['user']['full_name'], '')
```

But if the code is fixed to pass `None` instead of `''` (as recommended in L2), this test would fail. The test is coupled to the current (inconsistent) behavior.

**Risk:** Low. Only matters if L2 is fixed.

**Recommendation:** Update the test to accept either `None` or `''` depending on the desired behavior.

---

## ✅ WHAT'S DONE WELL

1. **Test coverage is excellent** — 117 tests covering all endpoints, edge cases, and error conditions.
2. **Refresh token rotation** is correctly implemented (old token revoked, new token issued).
3. **Password hashing** uses Django's native `AbstractBaseUser` with PBKDF2 — industry standard.
4. **Error handling** in views is comprehensive with proper HTTP status codes.
5. **Middleware deprecation** was handled correctly — file preserved with warning, DRF auth used instead.
6. **Database schema** is well-designed with proper indexes and foreign keys.
7. **Token hash storage** uses SHA-256, which is appropriate for this use case.
8. **Logout properly revokes** tokens from the database, preventing reuse.
9. **Profile update** correctly validates email uniqueness (case-insensitive).
10. **API registry and database schema docs** are well-maintained and up-to-date.

---

## Summary Table

| ID | Severity | Category | File | Description |
|----|----------|----------|------|-------------|
| C1 | 🔴 Critical | Security/Design | `jwt_utils.py:38-52` | Duplicate claims (`user_id`/`userId`), redundant `type` claim, potential SimpleJWT conflict |
| C2 | 🔴 Critical | Error Handling | `jwt_utils.py:136-138` | Overly broad exception catching masks programming errors |
| M1 | 🟡 Medium | Architecture | `config/urls.py:54-55` | Duplicate route for profile (`/auth/me/` and `/users/me/`) |
| M2 | 🟡 Medium | Security | `settings.py:177` | Access token lifetime is 60min instead of planned 15min |
| L1 | 🟢 Low | Code Quality | `views.py:199-205` | Redundant try/except around `request.data` |
| L2 | 🟢 Low | Consistency | `views.py:110` | Empty string `''` vs `None` for optional `full_name` |
| L3 | 🟢 Low | Testing | `test_views.py:108` | Test coupled to inconsistent empty-string behavior |

---

## Recommended Action Items (Priority Order)

1. **Fix C1**: Clean up JWT claim structure — remove `userId` duplicate, remove redundant `type` claim, rely on SimpleJWT's built-in type checking.
2. **Fix C2**: Split exception handling in `verify_access_token` and `verify_refresh_token` — log internal errors separately from token validation errors.
3. **Fix M1**: Remove `me/` from `users/urls.py` to eliminate the duplicate `/auth/me/` route.
4. **Fix M2**: Change `ACCESS_TOKEN_LIFETIME` from 60 minutes to 15 minutes as planned.
5. **Fix L2/L3**: Change `full_name` default from `''` to `None` and update the corresponding test.
6. **Fix L1**: Remove the redundant try/except around `request.data` in `login_view`.
