# Fix 3 Test Failures — Implementation Prompt for Code Mode

## Root Cause Analysis

### Failure 1: `test_rag_service_integration` — `AttributeError: module 'conversations.rag_service' has no attribute 'OpenAI'`

**File:** [`conversations/tests/test_integration.py`](src/backend/conversations/tests/test_integration.py:186)

**Problem:** The test mocks `conversations.rag_service.OpenAI` at line 186:
```python
@patch("conversations.rag_service.OpenAI")
```

But [`conversations/rag_service.py`](src/backend/conversations/rag_service.py) no longer imports or uses `OpenAI` directly. It was refactored to use the provider abstraction via [`get_chat_provider()`](src/backend/conversations/rag_service.py:232) from [`providers.registry`](src/backend/providers/registry.py:43). The mock path is stale.

**Fix:** Update the mock path to target the actual dependency used by `run_rag_query`. The function calls `get_chat_provider()` which is imported from `providers.registry`. The correct mock target is `conversations.rag_service.get_chat_provider`.

---

### Failure 2: `test_generate_embedding_empty_text_returns_none` — `ProviderNotRegisteredError: Embedding provider 'google' not registered. Available: []`

**File:** [`documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py:109)

**Problem:** The test at line 109 calls `generate_embedding("")` **without** patching `get_embedding_provider`. The real `get_embedding_provider()` is called, which reads `settings.EMBEDDING_PROVIDER` (defaults to `'google'`), but the provider registration code in [`providers/registration.py`](src/backend/providers/registration.py) is never imported during test execution, so the `_embedding_providers` dict is empty.

**Fix:** The `generate_embedding` function in [`embedding_service.py`](src/backend/documents/services/embedding_service.py:54) delegates directly to `provider.embed(text)` without any empty-text guard. The empty-text guard exists **only** inside the provider implementations (e.g., [`GeminiEmbeddingProvider.embed()`](src/backend/providers/gemini_embedding.py:56) returns `None` for empty text). So the test needs to either:
- (a) Add `@patch("documents.services.embedding_service.get_embedding_provider")` to the test, OR
- (b) Add an explicit empty-text guard in `generate_embedding()` itself.

**Recommended approach (b):** Add an explicit empty-text guard in `generate_embedding()` at [`embedding_service.py:54`](src/backend/documents/services/embedding_service.py:54) so the function is self-contained and doesn't depend on provider implementation details. This is more robust.

---

### Failure 3: `test_embed_query_raises_on_empty_text` — `AssertionError: ValueError not raised`

**File:** [`documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py:164)

**Problem:** The test mocks `get_embedding_provider` at line 164:
```python
@patch("documents.services.embedding_service.get_embedding_provider")
```

But the mock's `embed_query` method is a `MagicMock` that returns a `MagicMock` by default instead of raising `ValueError`. The test expects `embed_query("")` to raise `ValueError`, but the real validation happens inside the provider's `embed_query` method (e.g., [`GeminiEmbeddingProvider.embed_query()`](src/backend/providers/gemini_embedding.py:243)), which is bypassed by the mock.

**Fix:** The `embed_query` function in [`embedding_service.py`](src/backend/documents/services/embedding_service.py:70) also lacks an empty-text guard. It delegates directly to `provider.embed_query(text)` without validation. The fix is to add an explicit empty-text guard in `embed_query()` itself, before calling the provider. This way the test will work regardless of whether the provider is mocked or real.

---

## Implementation Steps

### Step 1: Add empty-text guards to `embedding_service.py`

**File:** [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py)

**1a. In `generate_embedding()` (line 54):** Add an early return `None` for empty/whitespace-only text before calling the provider.

```python
def generate_embedding(text: str) -> list[float] | None:
    if not text or not text.strip():
        return None
    provider = get_embedding_provider()
    return provider.embed(text)
```

**1b. In `embed_query()` (line 70):** Add a `ValueError` raise for empty/whitespace-only text before calling the provider.

```python
def embed_query(text: str) -> list[float]:
    if not text or not text.strip():
        raise ValueError("text must be non-empty")
    provider = get_embedding_provider()
    return provider.embed_query(text)
```

### Step 2: Fix the mock path in `test_rag_service_integration`

**File:** [`src/backend/conversations/tests/test_integration.py`](src/backend/conversations/tests/test_integration.py)

Change line 186 from:
```python
@patch("conversations.rag_service.OpenAI")
```
to:
```python
@patch("conversations.rag_service.get_chat_provider")
```

Then update the mock setup (lines 205-213) to work with the provider interface instead of the raw OpenAI client. The `get_chat_provider` returns a provider instance with a `.chat()` method. So instead of:

```python
mock_openai.return_value.chat.completions.create.return_value = mock_response
```

It should be:

```python
mock_provider = MagicMock()
mock_provider.chat.return_value = {
    "content": "Based on [Source 1], machine learning is a subset of AI.",
    "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
}
mock_get_chat_provider.return_value = mock_provider
```

### Step 3: Verify the fixes

Run the 3 specific tests to confirm they pass:

```bash
docker-compose exec backend python -m pytest conversations/tests/test_integration.py::ConversationIntegrationTests::test_rag_service_integration documents/tests/test_embedding.py::GenerateEmbeddingTests::test_generate_embedding_empty_text_returns_none documents/tests/test_embedding.py::EmbedQueryTests::test_embed_query_raises_on_empty_text -v
```

Then run the full test suite to ensure no regressions:

```bash
docker-compose exec backend pytest
```

---

## Summary of Changes

| # | File | Change |
|---|------|--------|
| 1 | [`documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) | Add empty-text guard to `generate_embedding()` returning `None` |
| 2 | [`documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) | Add empty-text guard to `embed_query()` raising `ValueError` |
| 3 | [`conversations/tests/test_integration.py`](src/backend/conversations/tests/test_integration.py) | Fix mock path from `OpenAI` to `get_chat_provider` and adapt mock setup |
