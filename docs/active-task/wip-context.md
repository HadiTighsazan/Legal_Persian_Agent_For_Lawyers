# WIP Context — Switch Embedding Provider from Ollama to Google Gemini

## What Was Just Completed

Replaced the Ollama-based embedding service (`nomic-embed-text`) with Google Gemini API (`gemini-embedding-001`). All 5 specified files were modified, tests pass (59/59), and a real API smoke test confirmed 768-dim embeddings are generated correctly.

### Files Modified

1. **`src/backend/config/settings.py`** — Added `GOOGLE_API_KEY` and `GEMINI_EMBEDDING_MODEL` env vars, changed `EMBEDDING_PROVIDER` default from `'ollama'` to `'google'`, updated comment from "Ollama Configuration" to "Embedding Provider Configuration". Default model: `gemini-embedding-001`.

2. **`src/backend/documents/services/embedding_service.py`** — Complete rewrite from Ollama to Gemini API:
   - Model: `gemini-embedding-001` (not `text-embedding-004` as originally planned — that model doesn't exist)
   - Single endpoint: `POST :embedContent` with `outputDimensionality: 768`
   - Batch endpoint: `POST :batchEmbedContents` with `outputDimensionality: 768` per request
   - `SUB_BATCH_SIZE`: 100 (Gemini max)
   - Retry logic preserved (3 attempts, exponential backoff)

3. **`.env.example`** — Added Google Gemini config section with `GOOGLE_API_KEY`, `GEMINI_EMBEDDING_MODEL=gemini-embedding-001`, `EMBEDDING_PROVIDER=google`. Updated `EMBEDDING_DIMENSION` comment.

4. **`docker-compose.yml`** — Added `GOOGLE_API_KEY`, `GEMINI_EMBEDDING_MODEL`, `EMBEDDING_PROVIDER` to both `backend` and `celery_worker` services.

5. **`src/backend/documents/tests/test_embedding.py`** — Replaced Ollama mock helpers with Gemini mock helpers, updated all URL assertions, request body assertions (added `outputDimensionality: 768`), sub-batch sizes from 50→100.

6. **`src/backend/documents/tests/test_search_service.py`** — Updated comment from "text-embedding-004" to "gemini-embedding-001".

### Key Findings During Implementation

- **Model name**: The originally specified `text-embedding-004` does not exist in the Gemini API. The correct model is `models/gemini-embedding-001`.
- **Default dimension**: `gemini-embedding-001` returns 3072-dim vectors by default.
- **`outputDimensionality`**: Supported in both `embedContent` (single) and `batchEmbedContents` (per-request) endpoints. Set to 768 to match the existing pgvector schema.
- **Batch endpoint**: `outputDimensionality` must be passed inside each request object, not at the top level.

### Test Results

- **59/59 tests pass** in `test_embedding.py`
- **Real API smoke test**: Successfully generated a 768-dim embedding vector via the live Gemini API

## Current State of Code

- [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) — Gemini API implementation with `generate_embedding`, `embed_query`, `batch_generate_embeddings`, `generate_embeddings_for_document`, `batch_embed_chunks`, `reembed_chunk`
- [`src/backend/config/settings.py`](src/backend/config/settings.py) — Google Gemini settings configured
- [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py) — All 59 tests updated for Gemini API
- [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) — Comment updated
- [`.env.example`](.env.example) — Google Gemini config documented
- [`docker-compose.yml`](docker-compose.yml) — Environment variables propagated

## Next Step

No further steps. The migration is complete and verified.

### Acceptance Criteria

- [x] Embedding service uses Google Gemini API instead of Ollama
- [x] `generate_embedding()` calls `POST :embedContent` with `outputDimensionality: 768`
- [x] `embed_query()` calls `POST :embedContent` with `outputDimensionality: 768`
- [x] `batch_generate_embeddings()` calls `POST :batchEmbedContents` with `outputDimensionality: 768` per request
- [x] `SUB_BATCH_SIZE` is 100 (Gemini max)
- [x] All existing tests pass (59/59)
- [x] Real API smoke test confirms 768-dim embeddings
- [x] `.env.example` documents the new Google Gemini config
- [x] `docker-compose.yml` propagates `GOOGLE_API_KEY` and `GEMINI_EMBEDDING_MODEL`
- [x] No database migration needed (768-dim vectors unchanged)
