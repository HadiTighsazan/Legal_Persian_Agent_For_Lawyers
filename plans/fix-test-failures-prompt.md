# Fix Test Failures — Complete Prompt for Code Mode

## Root Cause Analysis

### Issue 1: `page_start` / `page_end` NOT NULL Violation (9 failing tests)

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py) — `EmbedDocumentTaskTests` class (lines 753–1012)

**Root Cause:**
The [`_create_chunks()`](src/backend/documents/tests/test_tasks.py:789) helper method in `EmbedDocumentTaskTests` creates `DocumentChunk` records **without** providing `page_start` and `page_end` values:

```python
def _create_chunks(self, count: int, has_embedding: bool = False) -> list:
    chunks = []
    for i in range(count):
        chunk = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=i,
            content=f"Test chunk content {i}." * 20,
            token_count=50,
            embedding=None if not has_embedding else [0.1] * 1536,
        )
        chunks.append(chunk)
    return chunks
```

The [`DocumentChunk`](src/backend/documents/models.py:80) model defines both `page_start` and `page_end` as `models.IntegerField()` (NOT `null=True`), meaning they are required NOT NULL fields. The database migration [`0001_initial.py`](src/backend/documents/migrations/0001_initial.py:44-45) confirms these columns have no default and no null allowance.

**Contrast with production code:** The [`chunk_document`](src/backend/documents/tasks/document_processing.py:267-278) task correctly passes `chunk.page_start` and `chunk.page_end` from the `ChunkingService` results. The test helper simply omits them.

**Fix:** Add `page_start=1` and `page_end=1` (or appropriate values) to the `_create_chunks()` method.

---

### Issue 2: Unauthenticated Response Shape Mismatch (1 failing test)

**File:** [`src/backend/tests/test_upload_integration.py`](src/backend/tests/test_upload_integration.py) — `test_unauthenticated_request_returns_401` (line 257)

**Root Cause:**
The test expects the response to contain an `"error"` key:

```python
data = response.json()
self.assertIn(
    "error",
    data,
    msg="Response should contain an 'error' key for unauthenticated requests.",
)
```

However, the actual response from `rest_framework_simplejwt.authentication.JWTAuthentication` (configured in [`settings.py`](src/backend/config/settings.py:153-154)) returns:

```json
{"detail": "Authentication credentials were not provided."}
```

The old [`JWTAuthenticationMiddleware`](src/backend/users/middleware.py:183-196) (which is **deprecated and no longer in MIDDLEWARE**) returned `{"error": ...}`, but the current DRF-based auth returns `{"detail": ...}`.

**Fix:** Change the assertion in the test to check for `"detail"` instead of `"error"`.

---

## Required Changes

### Change 1: Fix `_create_chunks()` in test_tasks.py

**File:** [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py)

**Location:** Lines 789–801, the `_create_chunks` method inside `EmbedDocumentTaskTests` class.

**What to do:** Add `page_start` and `page_end` parameters to the `DocumentChunk.objects.create()` call.

**Search block (exact content to find):**

```python
    def _create_chunks(self, count: int, has_embedding: bool = False) -> list:
        """Create *count* DocumentChunk records for the test document."""
        chunks = []
        for i in range(count):
            chunk = DocumentChunk.objects.create(
                document=self.document,
                chunk_index=i,
                content=f"Test chunk content {i}." * 20,
                token_count=50,
                embedding=None if not has_embedding else [0.1] * 1536,
            )
            chunks.append(chunk)
        return chunks
```

**Replace with:**

```python
    def _create_chunks(self, count: int, has_embedding: bool = False) -> list:
        """Create *count* DocumentChunk records for the test document."""
        chunks = []
        for i in range(count):
            chunk = DocumentChunk.objects.create(
                document=self.document,
                chunk_index=i,
                page_start=1,
                page_end=1,
                content=f"Test chunk content {i}." * 20,
                token_count=50,
                embedding=None if not has_embedding else [0.1] * 1536,
            )
            chunks.append(chunk)
        return chunks
```

---

### Change 2: Fix assertion in test_upload_integration.py

**File:** [`src/backend/tests/test_upload_integration.py`](src/backend/tests/test_upload_integration.py)

**Location:** Lines 276–281, inside `test_unauthenticated_request_returns_401`.

**What to do:** Change the assertion from checking `"error"` key to checking `"detail"` key.

**Search block (exact content to find):**

```python
        # The middleware returns JSON with an 'error' key
        data = response.json()
        self.assertIn(
            "error",
            data,
            msg="Response should contain an 'error' key for unauthenticated requests.",
        )
```

**Replace with:**

```python
        # DRF's JWTAuthentication returns JSON with a 'detail' key
        data = response.json()
        self.assertIn(
            "detail",
            data,
            msg="Response should contain a 'detail' key for unauthenticated requests.",
        )
```

---

## Verification

After applying both changes, run the tests:

```bash
docker-compose exec backend pytest documents/tests/test_tasks.py::EmbedDocumentTaskTests -v
docker-compose exec backend pytest tests/test_upload_integration.py::DocumentUploadIntegrationTests::test_unauthenticated_request_returns_401 -v
```

Or run all tests to confirm no regressions:

```bash
docker-compose exec backend pytest -v
```

All 10 previously failing tests should now pass.
