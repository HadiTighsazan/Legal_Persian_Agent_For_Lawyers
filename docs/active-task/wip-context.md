# WIP Context — Epic E-04, Task 4

## What was just completed
- **Task 4 of Epic E-04 (Celery Tasks for Document Processing)** has been completed, including optimizations and debugging.
- Created `src/backend/documents/tasks/__init__.py` — exports the three task functions.
- Created `src/backend/documents/tasks/document_processing.py` with three Celery tasks.
- Created `src/backend/documents/tests/test_tasks.py` with 18 tests (all passing).

### Subtask 4a: `extract_text_from_pdf(document_id)` — `@shared_task(bind=True)`
- Fetches `Document` by ID; locates the `ProcessingTask` via `filter(document=document, task_type="extract").order_by('-created_at').first()` (fallback: creates one if not found).
- Sets `ProcessingTask.celery_task_id = self.request.id`, `status='running'`, `started_at=now()`.
- Sets `Document.processing_status = 'processing'`.
- Opens PDF via `fitz.open(os.path.join(settings.MEDIA_ROOT, document.file_path))` — uses `MEDIA_ROOT` + relative `file_path`.
- Checks for password protection by inspecting the error message for "password" keyword.
- Handles empty PDF (0 pages): marks as completed with `extracted_text_length=0`, returns `""`.
- Iterates through pages, extracts text with `[PAGE N]\n` markers (N starts from 1), joined by `"\n".join(...)`.
- Updates `Document.extracted_text_length`, `total_pages`.
- Marks `ProcessingTask` as `completed` with `completed_at=now()`.
- **Error handling**: Catches `fitz.FileDataError` → "PDF file is corrupted"; password-protected → "PDF is password-protected"; any other exception → logs full traceback. All failures call `_fail_extract()` which sets both `ProcessingTask` and `Document` to `failed` status.
- **Return type**: `str` (always returns a string, empty string on failure/empty PDF).

### Subtask 4b: `chunk_document(extracted_text, document_id)` — `@shared_task(bind=True)`
- Receives `extracted_text` from the previous task in the Celery chain (first positional argument).
- Locates the extract `ProcessingTask` via `filter(document=document, task_type="extract").first()`.
- Empty/whitespace-only text → sets `Document.total_chunks=0`, `processing_status='completed'`, marks extract task as completed.
- Calls `ChunkingService().chunk_text(extracted_text, chunk_size=1000, overlap=200)`.
- Builds `DocumentChunk` objects using a list comprehension with `enumerate(chunk_results)`.
- Bulk inserts via `DocumentChunk.objects.bulk_create(chunks_to_create)` inside `transaction.atomic()`.
- Updates `Document.total_chunks`, `processing_status='completed'`.
- Updates extract `ProcessingTask` to `status='completed'`, `completed_at=now()`.
- **Error handling**: Catches any exception → marks both `ProcessingTask` and `Document` as failed with full traceback in `error_message`.

### Subtask 4c: `process_document(document_id)` — `@shared_task(bind=True)` (Celery task, not a plain function)
- **Important architectural decision**: This is a `@shared_task(bind=True)` (not a plain helper function), so it can be called via `.delay()` from API views.
- Verifies `Document` exists and `processing_status != 'processing'` (prevents duplicate processing).
- Creates initial `ProcessingTask` with `task_type='extract'`, `status='pending'`.
- Builds Celery chain: `chain(extract_text_from_pdf.s(document_id), chunk_document.s(document_id))`.
- Executes chain via `chain_obj.apply_async()`, stores `celery_task_id` on the `ProcessingTask`.
- Returns the Celery task ID (or `None` on failure/duplicate).

### Helper: `_fail_extract(processing_task, document, error_message)`
- Dedicated helper for marking both `ProcessingTask` and `Document` as failed with the given error message and `completed_at=now()`.

### Key changes from original implementation
| Aspect | Original | Current (optimized) |
|--------|----------|---------------------|
| `process_document` type | Plain function | `@shared_task(bind=True)` |
| PDF path | `document.file_path` directly | `os.path.join(settings.MEDIA_ROOT, document.file_path)` |
| ProcessingTask lookup | `document.processing_tasks.get(task_type="extract")` | `filter(...).order_by('-created_at').first()` with fallback create |
| Empty PDF handling | Falls through to chunking task | Returns `""` immediately, marks as completed |
| Bulk insert wrapping | No transaction | `transaction.atomic()` |
| Error traceback | `logger.exception()` only | `traceback.format_exc()` stored in `error_message` |
| Return type (extract) | `Optional[str]` | `str` (always returns string) |
| Duplicate processing check | Not present | Added in `process_document` |
| Tests | Not present | 18 tests in `documents/tests/test_tasks.py` |

## Current state of the code
- `src/backend/documents/tasks/__init__.py` — created, exports all three tasks.
- `src/backend/documents/tasks/document_processing.py` — fully implemented with all three Celery tasks, optimized and debugged.
- `src/backend/documents/tests/test_tasks.py` — 18 tests, all passing.
- `src/backend/documents/tests/__init__.py` — created (empty).
- `src/backend/documents/services/chunking_service.py` — unchanged from Task 3.
- `src/backend/documents/models.py` — unchanged from Task 2 (has processing pipeline fields).
- `src/backend/tasks/models.py` — unchanged (has `ProcessingTask` model).
- `docs/references/database-schema.md` — unchanged.
- `docs/references/api-registry.md` — unchanged.

## Exact next step to be executed
- Proceed to Task 5 of Epic E-04 (Processing Status API — views, serializers, URLs).
