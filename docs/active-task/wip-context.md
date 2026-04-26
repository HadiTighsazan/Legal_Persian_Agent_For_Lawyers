# WIP Context — Task 2 of Epic E-05 (Embedding & Vector Storage)

## Status: ✅ COMPLETED

## What Was Completed

### Source Code Created
1. **`src/backend/documents/services/embedding_service.py`** — Core embedding service with 5 functions:
   - `generate_embedding(text)` — Single text embedding with exponential backoff retry (3 retries, 2^retry seconds)
   - `batch_generate_embeddings(texts)` — Batch embedding with sub-batching (50 per sub-batch), maps results back by index
   - `generate_embeddings_for_document(document_id)` — Full-document embedding with ProcessingTask progress tracking
   - `batch_embed_chunks(chunk_ids)` — On-demand chunk embedding returning `{"processed": N, "skipped": M, "failed": K}`
   - `reembed_chunk(chunk_id)` — Single chunk re-embedding

2. **`src/backend/documents/tests/test_embedding_service.py`** — 24 test cases covering:
   - `generate_embedding`: success, empty text, rate-limit retry, rate-limit exhausted, APIError, AuthenticationError, APIConnectionError
   - `batch_generate_embeddings`: success, mixed failures, sub-batch splitting (120 texts → 3 sub-batches), all empty, rate-limit retry
   - `generate_embeddings_for_document`: success, no chunks, all already embedded, not found, partial failures, batch progress
   - `batch_embed_chunks`: mixed state, invalid IDs, all already embedded
   - `reembed_chunk`: success, not found, failure

### Key Design Decisions
- **OpenAI client**: Created per-call via `_get_openai_client()` helper (not global singleton) to avoid Django settings import-time issues
- **Retry strategy**: Manual exponential backoff (no `tenacity` dependency) — 3 retries with 2^attempt seconds delay
- **Error handling**: All API errors caught and logged; functions return `None` or error dicts (not exceptions)
- **Batch size**: 50 per sub-batch as specified in PRD
- **Queryset evaluation**: `generate_embeddings_for_document` evaluates chunks into a list upfront to avoid queryset re-evaluation issues when saving embeddings mid-batch

### Test Results
- **24/24 tests PASSED** with mocked OpenAI calls
- No new dependencies required

## Next Steps
- Proceed to Task 3 of Epic E-05 (Celery Task for Embedding)
