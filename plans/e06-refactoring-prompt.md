# E06 Semantic Search & Retrieval — Refactoring Prompt for Code Mode

## Context

This is a targeted refactoring of the E06 (Semantic Search & Retrieval) epic. All tests currently pass. The goal is to fix a real bug in error handling and add minor robustness improvements.

## Changes Required

### 1. Fix `embed_query()` — Wrap provider exceptions in `EmbeddingError` (HIGH PRIORITY)

**File:** [`src/backend/documents/services/embedding_service.py`](../src/backend/documents/services/embedding_service.py)

**Problem:** `embed_query()` calls `provider.embed_query(text)` directly. The providers raise `requests.exceptions.RequestException` (Gemini) or generic `Exception` (OpenAI), **not** `EmbeddingError`. The view layer (`DocumentSearchView`) catches `except EmbeddingError`, so embedding failures produce generic 500 errors instead of structured `{"error": "embedding_failed", "message": "..."}` responses.

**Fix:** Wrap the provider call in a try/except that catches all exceptions and re-raises as `EmbeddingError`.

```python
def embed_query(text: str) -> list[float]:
    """Convert a search query string into an embedding vector.

    Delegates to the configured :class:`~providers.base.BaseEmbeddingProvider`.

    Args:
        text: The search query text (must be non-empty).

    Returns:
        A list of floats representing the query embedding.

    Raises:
        ValueError: If *text* is empty or whitespace-only.
        EmbeddingError: If the provider API call fails.
    """
    if not text or not text.strip():
        raise ValueError("text must be non-empty")
    provider = get_embedding_provider()
    try:
        return provider.embed_query(text)
    except Exception as e:
        logger.exception("embed_query failed for text: %s...", text[:50])
        raise EmbeddingError(f"Failed to embed query: {e}") from e
```

**Note:** Update the docstring's `Raises` section to replace `Exception` with `EmbeddingError`.

---

### 2. Add error handling to `_set_probes()` (LOW PRIORITY)

**File:** [`src/backend/documents/services/search_service.py`](../src/backend/documents/services/search_service.py)

**Problem:** If the database connection is broken or the `ivfflat` extension is missing, the raw SQL `SET ivfflat.probes` raises an unhandled exception.

**Fix:** Wrap in try/except and log a warning. This is a performance optimization, not a correctness requirement.

```python
def _set_probes(probes: int | None = None) -> None:
    """Set ivfflat.probes for the current database session.

    This controls how many inverted lists are searched during an ivfflat
    index scan.  Higher values improve recall at the cost of speed.
    Failures are logged as warnings since this is a performance optimization.

    Args:
        probes: Number of probes (1-100).  Falls back to
            ``settings.VECTOR_SEARCH_PROBES`` if ``None``.
    """
    probes = probes if probes is not None else settings.VECTOR_SEARCH_PROBES
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET ivfflat.probes = %s", [probes])
    except Exception as e:
        logger.warning(
            "Failed to set ivfflat.probes=%d: %s. "
            "Search performance may be affected.",
            probes,
            e,
        )
```

---

### 3. Add `query_vector` dimension validation in `search_chunks()` (MEDIUM PRIORITY)

**File:** [`src/backend/documents/services/search_service.py`](../src/backend/documents/services/search_service.py)

**Problem:** If the embedding provider returns a wrong-dimension vector, pgvector raises an unhelpful `DataError`.

**Fix:** Add a dimension check with a clear error message.

Add this import at the top if not already present:
```python
from django.conf import settings
```

Add this validation after `_set_probes()` and before the queryset construction:
```python
    # Validate query vector dimension.
    expected_dim = settings.EMBEDDING_DIMENSION
    if len(query_vector) != expected_dim:
        raise ValueError(
            f"query_vector dimension {len(query_vector)} does not match "
            f"expected dimension {expected_dim}. "
            f"Check EMBEDDING_DIMENSION setting."
        )
```

**Note:** Since `search_chunks()` is called from both `DocumentSearchView` and `rag_service.run_rag_query()`, and both already have exception handling (`except Exception` in `rag_service.py`), this `ValueError` will be caught appropriately. In `DocumentSearchView`, it will result in a 500 error (which is correct — this is a configuration/misuse error).

---

### 4. Add test for embedding failure → 500 response (LOW PRIORITY)

**File:** [`src/backend/documents/tests/test_views.py`](../src/backend/documents/tests/test_views.py)

Add this test inside the `DocumentSearchViewTests` class (after `test_search_empty_results`):

```python
    @patch("documents.views.embed_query")
    def test_search_embedding_failure_returns_500(
        self,
        mock_embed_query: MagicMock,
    ) -> None:
        """When embed_query raises EmbeddingError, the view should return 500
        with the structured error format."""
        from documents.services.embedding_service import EmbeddingError

        mock_embed_query.side_effect = EmbeddingError("Gemini API failure")

        response = self.client.post(
            self.url,
            {"query": "test"},
            format="json",
            **_auth_header(self.user),
        )

        self.assertEqual(
            response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        self.assertEqual(response.data["error"], "embedding_failed")
        self.assertIn(
            "Failed to generate query embedding",
            response.data["message"],
        )
```

---

## Execution Order

1. **Fix `embed_query()`** in `embedding_service.py` — this is the real bug
2. **Add `_set_probes()` error handling** in `search_service.py`
3. **Add dimension validation** in `search_service.py`
4. **Add missing test** in `test_views.py`

## Verification

After making all changes, run the tests to confirm everything passes:

```bash
docker-compose exec backend pytest documents/tests/test_search_service.py documents/tests/test_search_integration.py documents/tests/test_views.py -v
```

Also run the full test suite to ensure no regressions:

```bash
docker-compose exec backend pytest
```

## WIP Update

After completing, update [`docs/active-task/wip-context.md`](../docs/active-task/wip-context.md) with:
- What was changed
- Current state
- Next steps
