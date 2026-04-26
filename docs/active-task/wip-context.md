# WIP Context — Task 6 of Epic E-05 (Embedding Celery Task)

## Status: ✅ COMPLETED

## What Was Completed

### New File Created

1. **`src/backend/documents/tasks/embedding_tasks.py`** (NEW FILE) — Self-contained Celery task for generating document chunk embeddings:
   - `embed_document(document_id, task_id)` — Manages `ProcessingTask` lifecycle directly (no delegation to `generate_embeddings_for_document()`)
   - Fetches `ProcessingTask` by `task_id`, sets status → `"running"`, `started_at` = now
   - Fetches un-embedded chunks (`embedding__isnull=True`), processes in batches of 50
   - Uses `time.monotonic()` for batch timing logs
   - Progress calculated as `int((batch_index + 1) / total_batches * 100)` — reaches 100% on last batch even if some chunks failed
   - On success: status → `"completed"`, `completed_at` = now
   - On failure: status → `"failed"`, `error_message` = str(e)
   - `autoretry_for` on transient DB/network errors (consistent with other tasks)

### Source Code Modified

2. **`src/backend/documents/tasks/__init__.py`** — Updated import:
   - Changed `from .document_processing import chunk_document, embed_document, extract_text_from_pdf`
   - To `from .document_processing import chunk_document, extract_text_from_pdf`
   - Added `from .embedding_tasks import embed_document`
   - `__all__` unchanged (still exports `embed_document`)

3. **`src/backend/documents/tasks/document_processing.py`** — Removed old `embed_document` task:
   - Removed lines 371-421 (the old `embed_document` task and its section comment)
   - Updated module docstring with a `.. note::` pointing to the new location in `embedding_tasks.py`

4. **`src/backend/documents/tests/test_tasks.py`** — Added `EmbedDocumentTaskTests` class with 13 test cases:
   - `test_successful_embedding` — 3 un-embedded chunks → all get embeddings, task → completed
   - `test_no_unembedded_chunks` — All chunks already embedded → task completes immediately
   - `test_empty_document_no_chunks` — Document with 0 chunks → task completes immediately
   - `test_processing_task_not_found` — Invalid task_id → logs error, returns gracefully
   - `test_document_not_found` — Invalid document_id → task marked as failed
   - `test_partial_batch_failures` — Some embeddings fail → remaining chunks still get embeddings
   - `test_task_marked_failed_on_error` — API error → task marked as failed with error_message
   - `test_progress_updates` — Verify progress goes from 0 → 50 → 100 for 2 batches of 50
   - `test_single_batch_progress` — A single batch (< 50 chunks) should go from 0 → 100
   - `test_sets_celery_task_id` — The celery_task_id should be set to the mock request ID
   - `test_sets_started_at` — The started_at timestamp should be set when task begins running
   - `test_exactly_one_batch` — Exactly 50 chunks → processed in a single batch call
   - `test_uneven_batch` — 75 chunks (1.5 batches) → processed correctly with 2 batch calls

### No Import Breakage Verified

- `src/backend/documents/views.py` imports `embed_document` from `documents.tasks` — still works via `__init__.py` re-export
- `src/backend/documents/views.py:470` calls `embed_document.delay(...)` — no change needed
- `src/backend/documents/tests/test_views.py:958` mocks `documents.views.embed_document` — no change needed

## Next Steps
- Proceed to Task 7 (Retry API) or next planned task
