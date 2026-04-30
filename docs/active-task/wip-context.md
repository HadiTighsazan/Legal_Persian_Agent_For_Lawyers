# WIP Context — E05 Embedding & Vector Storage Refactoring

## What Was Completed

All 7 changes from the E05 refactoring prompt were applied:

### Change 1 — Fix silent API failures in `embed_batch()` (HIGH PRIORITY)
- Added [`EmbeddingBatchError`](src/backend/providers/base.py:12) exception class extending `ProviderError` in [`providers/base.py`](src/backend/providers/base.py:12).
- [`OpenAIEmbeddingProvider.embed_batch()`](src/backend/providers/openai_embedding.py:102): Changed `except` block to raise `EmbeddingBatchError` instead of silently returning `results`.
- [`OllamaEmbeddingProvider.embed_batch()`](src/backend/providers/ollama_embedding.py): Same change — raises `EmbeddingBatchError` on total API failure.
- [`GeminiEmbeddingProvider.embed_batch()`](src/backend/providers/gemini_embedding.py:208,235): Added `EmbeddingBatchError` raises after retry exhaustion for both `Timeout` and `RequestException` cases.

### Change 2 — Eliminate dead code — Remove `generate_embeddings_for_document()` (MEDIUM PRIORITY)
- Removed [`generate_embeddings_for_document()`](src/backend/documents/services/embedding_service.py) entirely from [`embedding_service.py`](src/backend/documents/services/embedding_service.py).
- Added [`_process_chunk_batch()`](src/backend/documents/services/embedding_service.py:42) shared helper function for batch-processing chunks.
- Updated imports (removed `Document`, `ProcessingTask`, `timezone`).
- Updated module docstring.

### Change 3 — Fix `autoretry_for` dead code in `embed_document` task (MEDIUM PRIORITY)
- Removed `autoretry_for`, `max_retries`, `retry_backoff`, `retry_backoff_max`, `retry_jitter` from [`@shared_task`](src/backend/documents/tasks/embedding_tasks.py:30) decorator.
- Simplified to `@shared_task(bind=True)`.
- Updated [`embed_document`](src/backend/documents/tasks/embedding_tasks.py:30) task to use `_process_chunk_batch()` with `_update_progress` callback.
- Added `EmbeddingBatchError` handling in the task.

### Change 4 — Deduplicate `SUB_BATCH_SIZE` (LOW PRIORITY)
- Added [`EMBEDDING_SUB_BATCH_SIZE`](src/backend/providers/base.py:20) constant to [`providers/base.py`](src/backend/providers/base.py:20).
- Updated [`embedding_service.py`](src/backend/documents/services/embedding_service.py:14) to import from `providers.base`.
- Updated [`gemini_embedding.py`](src/backend/providers/gemini_embedding.py:12) to import from `providers.base` (removed local definition).

### Change 5 — Fix `reembed_chunk()` error response consistency (MEDIUM PRIORITY)
- Changed [`reembed_chunk()`](src/backend/documents/services/embedding_service.py:97) to raise `EmbeddingError` instead of returning error dicts.
- Updated [`ChunkReEmbedView.post()`](src/backend/documents/views.py:118) to catch `EmbeddingError` and return 500 with `{"error": "embedding_failed", "message": "..."}`.

### Change 6 — Add ownership check to `ChunkBatchEmbedView` (LOW PRIORITY)
- Added ownership filtering in [`ChunkBatchEmbedView.post()`](src/backend/documents/views.py:99) to filter chunks by `document__user=request.user`.

### Change 7 — Update tests
- Removed `GenerateEmbeddingsForDocumentTests` class from [`test_embedding.py`](src/backend/documents/tests/test_embedding.py).
- Updated `ReembedChunkTests` to expect `EmbeddingError` exceptions.
- Updated `ChunkBatchEmbedViewTests` with ownership filtering test.
- Updated `EmbeddingCeleryTaskTests` mock paths from `documents.tasks.embedding_tasks` to `documents.services.embedding_service`.
- Added `test_reembed_embedding_failure_returns_500` test.
- Fixed OpenAI provider tests in [`test_embedding_providers.py`](src/backend/providers/tests/test_embedding_providers.py) — changed mock strategy from `@patch("providers.openai_embedding.openai")` to `setUp`-based `patch("openai.OpenAI")` with `self.mock_client` attribute, since `openai` is imported lazily inside `__init__`.
- Fixed Gemini `test_embed_batch_empty_texts` to match actual behavior (API returning fewer embeddings than valid texts leaves trailing positions as `None` rather than raising `EmbeddingBatchError`).

## Current State of the Code

All changes are applied and all **449 tests pass** (full suite).

### Files Modified
| File | Changes |
|------|---------|
| [`src/backend/providers/base.py`](src/backend/providers/base.py) | Added `EmbeddingBatchError` exception class and `EMBEDDING_SUB_BATCH_SIZE` constant |
| [`src/backend/providers/openai_embedding.py`](src/backend/providers/openai_embedding.py) | Change 1 — raise `EmbeddingBatchError` on API failure |
| [`src/backend/providers/ollama_embedding.py`](src/backend/providers/ollama_embedding.py) | Change 1 — raise `EmbeddingBatchError` on API failure |
| [`src/backend/providers/gemini_embedding.py`](src/backend/providers/gemini_embedding.py) | Changes 1, 4 — raise `EmbeddingBatchError`, import shared `EMBEDDING_SUB_BATCH_SIZE` |
| [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) | Changes 2, 4, 5 — removed dead code, added `_process_chunk_batch()`, `reembed_chunk()` raises `EmbeddingError` |
| [`src/backend/documents/tasks/embedding_tasks.py`](src/backend/documents/tasks/embedding_tasks.py) | Change 3 — removed `autoretry_for`, uses `_process_chunk_batch()` |
| [`src/backend/documents/views.py`](src/backend/documents/views.py) | Changes 5, 6 — ownership check in `ChunkBatchEmbedView`, `EmbeddingError` handling in `ChunkReEmbedView` |
| [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py) | Change 7 — updated tests for all refactored code |
| [`src/backend/providers/tests/test_embedding_providers.py`](src/backend/providers/tests/test_embedding_providers.py) | Change 7 — fixed OpenAI mock strategy and Gemini test |

## Remaining Items

- No remaining items — all 7 changes are complete.

## Reference Documentation Updates

- **`docs/references/database-schema.md`**: No changes — no database schema modifications were made.
- **`docs/references/api-registry.md`**: Updated to reflect:
  - `ChunkBatchEmbedView` now filters chunks by user ownership (403 if chunk belongs to another user's document).
  - `ChunkReEmbedView` now returns `500 Internal Server Error` with `{"error": "embedding_failed", "message": "..."}` when embedding generation fails (instead of returning 200 with `embedding_updated: false`).
