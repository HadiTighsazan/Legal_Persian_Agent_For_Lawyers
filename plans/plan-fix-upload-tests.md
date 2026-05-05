# Fix Plan: 4 Failing Upload Integration Tests

## Root Cause Analysis

### The Problem

All 4 failing tests in [`tests/test_upload_integration.py`](src/backend/tests/test_upload_integration.py) send POST requests **without** a `title` field:

```python
# All 4 failing tests do this:
response = self.client.post(
    self.upload_url,
    {"file": uploaded_file},  # <-- no "title" key
    format="multipart",
)
```

The [`DocumentUploadSerializer`](src/backend/documents/serializers.py:25) defines `title` as `required=True`:

```python
title = serializers.CharField(
    required=True,
    allow_blank=False,
    max_length=255,
)
```

Because `title` is required, DRF's serializer validation fails **before** any view logic runs. The response is always:

```json
{"title": ["This field is required."]}
```

...with HTTP 400, regardless of what the test expects.

### Failure-by-Failure Breakdown

| Test | Expected | Actual | Why |
|------|----------|--------|-----|
| `test_valid_pdf_upload_returns_201` | 201 | 400 `{'title': ['This field is required.']}` | Serializer rejects missing `title` before upload logic runs |
| `test_invalid_file_type_returns_400` | 400 with `'detail'` key mentioning `.exe` | 400 with `{'title': ['This field is required.']}` | Same — serializer fails first |
| `test_file_too_large_returns_400` | 400 with `'detail'` key mentioning `MB` | 400 with `{'title': ['This field is required.']}` | Same |
| `test_storage_failure_returns_500` | 500 with `'detail'` key mentioning `Storage error` | 400 with `{'title': ['This field is required.']}` | Same — never reaches storage logic |

### The Fix Options

**Option A — Make `title` optional in the serializer** (recommended ✅)

The [`upload_document`](src/backend/documents/services/upload_service.py:131) service already handles a missing/empty `title` gracefully:

```python
document = create_document(
    ...
    title=title or unique_filename,  # <-- falls back to unique_filename
    ...
)
```

Making `title` `required=False` in the serializer is the correct fix because:
1. The service layer already supports it.
2. The API becomes more flexible (title is a display label, not a technical requirement).
3. All 4 tests pass without modification.
4. No frontend changes needed (the frontend can still send `title` if it wants).

**Option B — Add `title` to all test requests**

This would fix the tests but leave a usability issue: the API would **require** a `title` even though the service layer doesn't need one. This is inconsistent.

---

## Action Plan

### Step 1: Make `title` optional in `DocumentUploadSerializer`

**File:** [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py:25)

Change:
```python
title = serializers.CharField(
    required=True,
    allow_blank=False,
    max_length=255,
)
```

To:
```python
title = serializers.CharField(
    required=False,
    allow_blank=True,
    max_length=255,
    default="",
)
```

**Why these specific changes:**
- `required=False` — the field is no longer mandatory
- `allow_blank=True` — allows empty string (which the service handles via `title or unique_filename`)
- `default=""` — when omitted entirely, defaults to empty string

### Step 2: Verify the fix

Run the 4 failing tests to confirm they pass:

```bash
docker-compose exec backend python -m pytest tests/test_upload_integration.py -v
```

Expected output:
```
tests/test_upload_integration.py::DocumentUploadIntegrationTests::test_valid_pdf_upload_returns_201 PASSED
tests/test_upload_integration.py::DocumentUploadIntegrationTests::test_invalid_file_type_returns_400 PASSED
tests/test_upload_integration.py::DocumentUploadIntegrationTests::test_file_too_large_returns_400 PASSED
tests/test_upload_integration.py::DocumentUploadIntegrationTests::test_storage_failure_returns_500 PASSED
tests/test_upload_integration.py::DocumentUploadIntegrationTests::test_unauthenticated_request_returns_401 PASSED
```

### Step 3: Run the full test suite to check for regressions

```bash
docker-compose exec backend pytest
```

All 450 tests should pass (446 previously passing + 4 now fixed).

### Step 4: Update reference documentation

If the API contract in [`docs/references/api-registry.md`](docs/references/api-registry.md) documents the `title` field as required, update it to reflect that `title` is now optional.

---

## Summary

| Item | Detail |
|------|--------|
| **Root cause** | `title` is `required=True` in `DocumentUploadSerializer`, but tests don't send it |
| **Fix** | Make `title` `required=False, allow_blank=True, default=""` in the serializer |
| **Files to change** | `src/backend/documents/serializers.py` (1 line change) |
| **Tests to verify** | `tests/test_upload_integration.py` (all 5 tests) |
| **Risk** | Low — the service layer already handles empty titles |
