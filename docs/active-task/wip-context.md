# WIP Context — Epic E-04, Task 4

## What was just completed
- **Task 4 of Epic E-04 (Document Processing Pipeline)** has been completed.
- Created `src/backend/documents/tasks/__init__.py` — exports the three task functions.
- Created `src/backend/documents/tasks/document_processing.py` with three Celery tasks:

### Subtask 4a: `extract_text_from_pdf(document_id)`
- Fetches `Document` by ID, creates/updates `ProcessingTask` with `task_type='extract'`, `celery_task_id=self.request.id`, `status='running'`, `started_at=now()`.
- Sets `Document.processing_status = 'processing'`.
- Opens PDF via `fitz.open(document.file_path)`, iterates pages, extracts text with `[PAGE N]` markers.
- Updates `Document.extracted_text_length`, `total_pages`.
- Marks `ProcessingTask` as `completed` with `completed_at=now()`.
- **Error handling**: Catches `fitz.FileDataError` → "PDF file is corrupted"; catches password-protected PDFs (detected via "password" in error message); empty PDF (0 pages) → returns empty string; any other exception → logs full traceback.

### Subtask 4b: `chunk_document(document_id, extracted_text)`
- Receives `extracted_text` from the previous task in the chain.
- Empty/whitespace-only text → sets `Document.total_chunks=0`, `processing_status='completed'`, marks extract task as completed.
- Calls `ChunkingService().chunk_text(extracted_text, chunk_size=1000, overlap=200)`.
- Builds `DocumentChunk` objects and bulk inserts via `DocumentChunk.objects.bulk_create(chunks)` inside `@transaction.atomic`.
- Updates `Document.total_chunks`, `processing_status='completed'`.
- Updates extract `ProcessingTask` to `status='completed'`.
- **Error handling**: Catches any exception → marks both `ProcessingTask` and `Document` as failed with error message and full traceback.

### Subtask 4c: `process_document(document_id)` (Orchestration)
- Verifies `Document` exists and `processing_status != 'processing'` (prevents duplicate processing).
- Creates initial `ProcessingTask` with `task_type='extract'`, `status='pending'`.
- Builds Celery chain: `chain(extract_text_from_pdf.s(document_id), chunk_document.s(document_id))`.
- Executes chain via `chain_obj.apply_async()`, stores `celery_task_id`.
- Returns the Celery task ID.

### Test file created
- Created `src/backend/documents/tests/test_tasks.py` with 18 tests across 3 test classes:
  - `ExtractTextFromPdfTests` (7 tests): happy path (page markers, ProcessingTask creation, document field updates), empty PDF, corrupted PDF, nonexistent document.
  - `ChunkDocumentTests` (7 tests): chunk creation, document field updates, extract task status update, empty text, whitespace-only text, exception handling, nonexistent document.
  - `ProcessDocumentTests` (4 tests): pending task creation, return value, chain building, duplicate processing prevention, nonexistent document.
- All 18 tests pass: `docker compose exec backend python manage.py test documents.tests.test_tasks --verbosity=2` → **OK**.
- Syntax verified: `docker compose exec backend python -m py_compile documents/tasks/document_processing.py` → exit code 0.

## Current state of the code
- `src/backend/documents/tasks/__init__.py` — created, exports all three tasks.
- `src/backend/documents/tasks/document_processing.py` — fully implemented with all three Celery tasks.
- `src/backend/documents/tests/test_tasks.py` — 18 tests, all passing.
- `src/backend/documents/tests/__init__.py` — created (empty).
- `src/backend/documents/services/chunking_service.py` — unchanged from Task 3.
- `src/backend/documents/models.py` — unchanged from Task 2 (has processing pipeline fields).
- `src/backend/tasks/models.py` — unchanged (has `ProcessingTask` model).

## Exact next step to be executed
- Proceed to Task 5 of Epic E-04 (e.g., embedding generation or pipeline integration with API endpoints).
