# WIP Context — Task 4 of Epic E-05 (Embedding Views)

## Status: ✅ COMPLETED

## What Was Completed

### Source Code Modified

1. **`src/backend/documents/tasks/document_processing.py`** — Added `embed_document` Celery task (Subtask 4d) that:
   - Accepts `document_id` and `processing_task_id` as arguments
   - Looks up the `ProcessingTask` by ID, updates it with Celery task ID and `status='running'`
   - Delegates to `generate_embeddings_for_document(document_id)` from the embedding service
   - Has `autoretry_for` on transient DB/storage errors with exponential backoff

2. **`src/backend/documents/tasks/__init__.py`** — Added `embed_document` to imports and `__all__`

3. **`src/backend/documents/views.py`** — Added 4 new view classes:
   - `DocumentEmbedView` — `POST /documents/{document_id}/embed/` — Triggers embedding for all un-embedded chunks. Returns `202 Accepted` with `DocumentEmbedResponseSerializer` data. Creates `ProcessingTask` and dispatches `embed_document.delay()`.
   - `ChunkBatchEmbedView` — `POST /chunks/batch-embed/` — Batch-embeds chunks by ID. Validates with `ChunkBatchEmbedRequestSerializer`, calls `batch_embed_chunks()`, returns `200 OK` with counts.
   - `ChunkReEmbedView` — `POST /chunks/{chunk_id}/re-embed/` — Re-embeds a single chunk. Checks ownership via `chunk.document.user`, calls `reembed_chunk()`, returns `200 OK`.
   - `TaskStatusView` — `GET /tasks/{task_id}/` — Retrieves processing task status. Returns all task fields including `id`, `document_id`, `task_type`, `status`, `progress`, `result`, `error_message`, `started_at`, `completed_at`.

4. **`src/backend/documents/urls.py`** — Registered 4 new URL routes:
   - `<uuid:document_id>/embed/` → `DocumentEmbedView`
   - `chunks/batch-embed/` → `ChunkBatchEmbedView`
   - `chunks/<uuid:chunk_id>/re-embed/` → `ChunkReEmbedView`
   - `tasks/<uuid:task_id>/` → `TaskStatusView`

5. **`src/backend/documents/tests/test_views.py`** — Added 4 new test classes (17 test methods total):
   - `DocumentEmbedViewTests` — 7 tests (404, 403, 401, 202 happy path, creates ProcessingTask, counts un-embedded chunks, skips already-embedded chunks)
   - `ChunkBatchEmbedViewTests` — 3 tests (401, 400 invalid chunk_ids, 200 happy path)
   - `ChunkReEmbedViewTests` — 4 tests (404, 403, 401, 200 happy path)
   - `TaskStatusViewTests` — 5 tests (404, 403, 401, 200 with task details, all expected fields)

6. **`docs/references/api-registry.md`** — Added documentation for all 4 new endpoints under a new "✅ Implemented Endpoints — Embedding Views (Epic E-05, Task 4)" section

### Test Results
- **67/67 tests PASSED** (50 existing + 17 new)
- All new views follow the existing patterns: `APIView` base class, `IsAuthenticated` permission class, ownership checks, consistent error format `{"error": "...", "message": "..."}`

## Next Steps
- Proceed to Task 5 of Epic E-05 (or next planned task)
