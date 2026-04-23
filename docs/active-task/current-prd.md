# PRD: E-04 Document Processing Pipeline

**Epic:** E-04 Document Processing Pipeline  
**Status:** Todo  
**Dependencies:** E-03 (Document Upload & Storage) ✅ Done  
**Downstream:** E-05 (Embedding & Vector Storage)

---

## Objective

Implement asynchronous Celery-based document processing pipeline that extracts text from uploaded PDFs using PyMuPDF, applies intelligent chunking strategy, tracks processing status, and handles errors gracefully.

---

## Database Changes

### New Table: `processing_tasks`

```sql
CREATE TABLE processing_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, processing, completed, failed
    task_id VARCHAR(255), -- Celery task ID
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_processing_tasks_document_id ON processing_tasks(document_id);
CREATE INDEX idx_processing_tasks_status ON processing_tasks(status);
CREATE INDEX idx_processing_tasks_task_id ON processing_tasks(task_id);
```

### New Table: `document_chunks`

```sql
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    page_number INT,
    char_count INT,
    token_count INT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX idx_document_chunks_chunk_index ON document_chunks(document_id, chunk_index);
```

### Update `documents` table

```sql
ALTER TABLE documents 
ADD COLUMN processing_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN total_chunks INT DEFAULT 0,
ADD COLUMN extracted_text_length INT DEFAULT 0,
ADD COLUMN processing_error TEXT;
```

---

## API Changes

### New Endpoints

**POST `/api/v1/documents/{document_id}/process`**  
Trigger processing for uploaded document.

**GET `/api/v1/documents/{document_id}/processing-status`**  
Get current processing status and progress.

**GET `/api/v1/documents/{document_id}/chunks`**  
Retrieve all chunks for a document (paginated).

**POST `/api/v1/processing-tasks/{task_id}/retry`**  
Retry failed processing task.

---

## Micro-Tasks

### Task 1: Setup Celery Infrastructure

**File:** `app/celery_app.py` (new)

- Initialize Celery app with Redis broker
- Configure task routes, result backend, serialization
- Add retry policy and error handling config
- Register task modules

**Acceptance Criteria:**
- Celery worker starts without errors
- Redis connection established
- Task discovery works

---

### Task 2: Create Processing Task Models

**Files:** `app/models/processing_task.py`, `app/models/document_chunk.py`

- Create `ProcessingTask` SQLAlchemy model matching schema
- Create `DocumentChunk` SQLAlchemy model matching schema
- Add relationships to `Document` model
- Create Alembic migration for new tables and columns

**Acceptance Criteria:**
- Migration runs successfully
- Models have proper relationships
- Indexes created

---

### Task 3: Implement Text Extraction Task

**File:** `app/tasks/document_processing.py`

- Create Celery task `extract_text_from_pdf(document_id)`
- Use PyMuPDF (fitz) to extract text page-by-page
- Store extracted text temporarily
- Update `processing_tasks` status to 'processing'
- Handle PyMuPDF exceptions (corrupted PDF, password-protected, etc.)
- Update `documents.extracted_text_length`

**Acceptance Criteria:**
- Task extracts text from valid PDF
- Page numbers preserved
- Handles corrupted PDFs gracefully
- Status updates in DB

---

### Task 4: Implement Chunking Strategy

**File:** `app/services/chunking_service.py`

- Implement recursive character-based chunking
- Chunk size: 1000 characters, overlap: 200 characters
- Preserve sentence boundaries (don't split mid-sentence)
- Track page numbers for each chunk
- Calculate token count using `tiktoken` (cl100k_base)
- Store metadata (page_number, char_count, token_count)

**Acceptance Criteria:**
- Chunks respect max size
- Overlap implemented correctly
- Sentence boundaries preserved
- Token count accurate

---

### Task 5: Create Chunking Task

**File:** `app/tasks/document_processing.py`

- Create Celery task `chunk_document(document_id, extracted_text)`
- Call `ChunkingService` to split text
- Bulk insert chunks into `document_chunks` table
- Update `documents.total_chunks`
- Update `processing_tasks.status` to 'completed'

**Acceptance Criteria:**
- Chunks saved to DB
- Bulk insert efficient (< 2s for 100 chunks)
- `total_chunks` accurate

---

### Task 6: Create Processing Orchestration Task

**File:** `app/tasks/document_processing.py`

- Create main task `process_document(document_id)` using Celery chain
- Chain: extract_text → chunk_document
- Create `processing_tasks` record with Celery task_id
- Update `documents.processing_status` to 'processing'
- Handle task failures and update status to 'failed'
- Store error messages in `processing_tasks.error_message`

**Acceptance Criteria:**
- Tasks execute in sequence
- Status tracking works end-to-end
- Failures logged properly

---

### Task 7: Implement Processing Status Tracking API

**File:** `app/api/v1/endpoints/documents.py`

- Add endpoint `POST /api/v1/documents/{document_id}/process`
  - Trigger `process_document.delay(document_id)`
  - Return task_id and initial status
- Add endpoint `GET /api/v1/documents/{document_id}/processing-status`
  - Query `processing_tasks` by document_id
  - Return status, progress, error if any
  - Include Celery task state from `AsyncResult`

**Acceptance Criteria:**
- Endpoints follow API registry schema
- Returns proper HTTP status codes
- Handles non-existent document_id

---

### Task 8: Implement Chunks Retrieval API

**File:** `app/api/v1/endpoints/documents.py`

- Add endpoint `GET /api/v1/documents/{document_id}/chunks`
- Pagination: `page`, `page_size` query params (default 20)
- Order by `chunk_index` ASC
- Return chunk content, metadata, page_number

**Acceptance Criteria:**
- Pagination works correctly
- Returns chunks in order
- Handles empty results

---

### Task 9: Implement Retry Mechanism

**File:** `app/api/v1/endpoints/processing.py`

- Add endpoint `POST /api/v1/processing-tasks/{task_id}/retry`
- Check if task status is 'failed'
- Increment `retry_count` (max 3 retries)
- Re-trigger `process_document.delay(document_id)`
- Reset status to 'pending'

**Acceptance Criteria:**
- Retry limit enforced
- New task_id generated
- Old error cleared

---

### Task 10: Error Handling & Edge Cases

**Files:** `app/tasks/document_processing.py`, `app/services/error_handler.py`

- Handle password-protected PDFs → status 'failed', error message
- Handle corrupted PDFs → status 'failed', error message
- Handle empty PDFs → status 'completed', 0 chunks
- Handle non-PDF files → status 'failed', error message
- Add Celery task retry with exponential backoff (max 3 retries)
- Log all errors to application logs

**Acceptance Criteria:**
- All edge cases handled
- Error messages user-friendly
- Logs contain stack traces

---

## Acceptance Criteria (Overall)

1. ✅ Document uploaded via E-03 triggers processing automatically
2. ✅ Text extracted from PDF using PyMuPDF
3. ✅ Text chunked with 1000 char size, 200 char overlap
4. ✅ Chunks stored in `document_chunks` table
5. ✅ Processing status tracked in `processing_tasks` table
6. ✅ API returns real-time processing status
7. ✅ Failed tasks can be retried (max 3 times)
8. ✅ Error messages stored and returned via API
9. ✅ Celery tasks run asynchronously without blocking API
10. ✅ All changes comply with `.clinerules`

---

## Technical Notes

- Use PyMuPDF (`fitz`) version 1.23+
- Redis required for Celery broker
- Celery worker command: `celery -A app.celery_app worker --loglevel=info`
- Token counting uses OpenAI's `tiktoken` library
- Chunking preserves markdown/structure if present

---

