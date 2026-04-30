# E02 Authentication & User Management — Refactoring Prompt for Code Mode

## Context

This is a refactoring task for Epic E02 (Authentication & User Management) of the DocuChat project. All 108 tests currently pass. The goal is to improve code quality, maintainability, and security without changing any behavior or breaking existing tests.

**Tech Stack:** Django 4.2, Django REST Framework, SimpleJWT

**Key Files:**
- [`src/backend/users/models.py`](../src/backend/users/models.py)
- [`src/backend/users/views.py`](../src/backend/users/views.py)
- [`src/backend/users/serializers.py`](../src/backend/users/serializers.py)
- [`src/backend/users/jwt_utils.py`](../src/backend/users/jwt_utils.py)
- [`src/backend/users/urls.py`](../src/backend/users/urls.py)
- [`src/backend/users/tests/test_views.py`](../src/backend/users/tests/test_views.py)
- [`src/backend/users/tests/test_jwt_utils.py`](../src/backend/users/tests/test_jwt_utils.py)
- [`src/backend/users/tests/test_models.py`](../src/backend/users/tests/test_models.py)

**Reference Docs:**
- [`docs/references/api-registry.md`](../docs/references/api-registry.md) — API contract details
- [`docs/references/database-schema.md`](../docs/references/database-schema.md) — DB schema
- [`plans/e02-code-review.md`](../plans/e02-code-review.md) — Full code review with all issues

---

## Refactoring Tasks (in order)

### Priority 1 — High (Code Quality & Maintainability)

#### Task 1.1: Create `RegisterSerializer` in `serializers.py`

Add a new serializer class `RegisterSerializer` that validates registration input:

```python
class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, max_length=255)
    password = serializers.CharField(required=True, write_only=True, min_length=8)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=255, trim_whitespace=True)

    def validate_email(self, value):
        # Check email uniqueness (case-insensitive)
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email already exists")
        return value

    def validate_password(self, value):
        # Apply Django's built-in password validators from settings
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value
```

#### Task 1.2: Create `LoginSerializer` in `serializers.py`

```python
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
```

#### Task 1.3: Create `UserSerializer` in `serializers.py`

A read-only serializer for user data output, used by register, login, and profile views:

```python
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_active', 'created_at', 'updated_at']
```

#### Task 1.4: Refactor `views.py` to Use Serializers

**`register_view`:**
- Replace manual validation with `RegisterSerializer(data=request.data)`
- On validation error, return `serializer.errors` with 400 status
- On email conflict (already exists), return 409
- Use `UserSerializer` for the response user data
- Keep the same response structure: `{user, accessToken, refreshToken}`

**`login_view`:**
- Replace manual validation with `LoginSerializer(data=request.data)`
- Keep the authentication logic (find user, check active, verify password)
- Use `UserSerializer` for the response user data
- Keep the same response structure

**`profile_view` (GET):**
- Replace manual dict construction with `UserSerializer(user).data`

**`profile_view` (PATCH):**
- Keep using `ProfileUpdateSerializer` for validation
- Use `UserSerializer(user).data` for the response

**Important:** Do NOT change the response JSON structure. The frontend expects:
- Register/Login: `{user: {...}, accessToken: "...", refreshToken: "..."}`
- Profile GET/PATCH: `{id, email, full_name, is_active, created_at, updated_at}`

#### Task 1.5: Move `import logging` to Module Level in `views.py`

- Add `import logging` at the top of the file
- Create module-level logger: `logger = logging.getLogger(__name__)`
- Remove all inline `import logging` and `logger = logging.getLogger(__name__)` from inside `except` blocks
- Use `logger.exception("Registration error")` instead of `logger.error(f"...")` to capture stack traces

---

### Priority 2 — Medium (Security & Robustness)

#### Task 2.1: Remove Dead Code from `jwt_utils.py`

1. **Remove `is_token_blacklisted()` function** (lines 177-191) — it always returns False
2. **Remove calls to `is_token_blacklisted()`** from:
   - `verify_access_token()` (line 112)
   - `verify_refresh_token()` (line 152)
3. **Remove `get_token_payload()` function** (lines 194-210) — it's never called anywhere

#### Task 2.2: Move Local `timezone` Imports in `models.py`

In `RefreshTokenManager` methods and `RefreshToken` instance methods:
- `timezone` is already imported at module level (line 8)
- Remove local `from django.utils import timezone` from:
  - `get_valid_tokens_for_user()` (line 99)
  - `cleanup_expired_tokens()` (line 115)
  - `is_expired()` (line 262)
  - `is_valid()` (line 272)
  - `get_remaining_lifetime()` (line 291)

---

### Priority 3 — Low (Cleanup & Consistency)

#### Task 3.1: Fix `full_name` Default in `register_view`

Change:
```python
full_name = data.get('full_name', '')
```
To:
```python
full_name = data.get('full_name') or ''
```

This ensures consistency — if `full_name` is not provided, it defaults to empty string (matching the current behavior expected by tests).

#### Task 3.2: Remove TDD Comments from `test_views.py`

Remove comments like:
- `# This test should fail initially (RED phase)` (lines 45, 304)
- `# Expected: 200 OK, but endpoint doesn't exist yet` (line 305)
- `# Currently returns 501 Not Implemented, but should return 201` (line 56)

---

## Important Rules

1. **DO NOT change any test files.** All 108 tests must continue to pass.
2. **DO NOT change the API response structure.** The frontend depends on the exact JSON format.
3. **DO NOT change model fields or database schema.**
4. **DO NOT change URL patterns.**
5. **Run tests after each task** to verify nothing is broken.
6. **Update `docs/references/api-registry.md`** if any endpoint documentation needs updating.
7. **Update `docs/active-task/wip-context.md`** after completing each task.

## Execution Order

1. Task 1.1 → Task 1.2 → Task 1.3 (add serializers)
2. Task 1.4 (refactor views to use serializers)
3. Task 1.5 (fix logging imports)
4. Task 2.1 (remove dead code)
5. Task 2.2 (fix local imports)
6. Task 3.1 → Task 3.2 (minor cleanup)
7. Run ALL tests to confirm everything passes
8. Update reference docs if needed
