# PRD: E-03 Document Upload & Storage

**Epic ID:** E-03  
**Status:** Todo  
**Owner:** AI Coding Assistant (Cline)

---

## Overview
Implement a secure document upload system with storage abstraction (S3/local), metadata tracking, and file validation. This epic enables users to upload documents that will later be processed, chunked, and embedded (E04, E05).

---

## Acceptance Criteria
- [ ] Users can upload documents via REST API endpoint
- [ ] Files are validated for type (PDF, DOCX, TXT) and size (max 50MB)
- [ ] Files are stored in configurable storage (S3 or local filesystem)
- [ ] Document metadata is persisted in PostgreSQL
- [ ] API returns document ID and metadata after successful upload
- [ ] Proper error responses for validation failures
- [ ] Storage path/URL is stored for retrieval

---

## Database Changes

**New Table: `documents`**
```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename VARCHAR(255) NOT NULL,
  original_filename VARCHAR(255) NOT NULL,
  file_size BIGINT NOT NULL,
  mime_type VARCHAR(100) NOT NULL,
  storage_path TEXT NOT NULL,
  storage_type VARCHAR(20) NOT NULL, -- 's3' or 'local'
  status VARCHAR(50) DEFAULT 'uploaded', -- 'uploaded', 'processing', 'completed', 'failed'
  uploaded_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_documents_status ON documents(status);
```

---

## API Changes

**New Endpoint:**

POST /api/v1/documents/upload
Content-Type: multipart/form-data

Request:
- file: binary (required)
- user_id: UUID (required, from auth context or body)

Response 201:
{
  "document_id": "uuid",
  "filename": "string",
  "file_size": number,
  "mime_type": "string",
  "uploaded_at": "ISO8601",
  "status": "uploaded"
}

Response 400:
{
  "error": "Invalid file type. Allowed: PDF, DOCX, TXT"
}
OR
{
  "error": "File size exceeds 50MB limit"
}

Response 500:
{
  "error": "Storage operation failed"
}


---

## Micro-Tasks

### **Task 1: Database Migration**
- Create migration file for `documents` table
- Apply schema from Database Changes section above
- Verify indexes are created
- **Files to modify:** `migrations/` (new file)
- **Acceptance:** Migration runs successfully, table exists with correct columns and indexes

---

### **Task 2: Storage Abstraction Layer**
- Create `storage/base.py` with abstract `StorageBackend` class
- Implement `storage/local.py` for local filesystem storage
- Implement `storage/s3.py` for S3 storage (boto3)
- Add config loader in `storage/__init__.py` to select backend based on env var `STORAGE_TYPE`
- **Files to create:** `storage/base.py`, `storage/local.py`, `storage/s3.py`, `storage/__init__.py`
- **Config required:** `STORAGE_TYPE`, `LOCAL_STORAGE_PATH`, `S3_BUCKET_NAME`, `S3_REGION`
- **Acceptance:** Can instantiate storage backend, call `save_file(file, path)` and `get_file_url(path)` methods

---

### **Task 3: File Validation Utility**
- Create `utils/file_validator.py`
- Implement `validate_file_type(filename, allowed_types)` → checks extension against `['.pdf', '.docx', '.txt']`
- Implement `validate_file_size(file, max_size_mb)` → checks file size ≤ 50MB
- **Files to create:** `utils/file_validator.py`
- **Acceptance:** Validation functions return `True/False` or raise descriptive exceptions

---

### **Task 4: Document Model & Repository**
- Create `models/document.py` with `Document` SQLAlchemy model matching schema
- Create `repositories/document_repository.py` with methods:
  - `create_document(user_id, filename, original_filename, file_size, mime_type, storage_path, storage_type)` → returns Document
  - `get_document_by_id(document_id)` → returns Document or None
- **Files to create:** `models/document.py`, `repositories/document_repository.py`
- **Acceptance:** Can insert and retrieve document records from database

---

### **Task 5: Upload Service Layer**
- Create `services/upload_service.py`
- Implement `upload_document(user_id, file)` method:
  1. Validate file type and size (use Task 3 utilities)
  2. Generate unique filename (UUID + extension)
  3. Save file using storage backend (Task 2)
  4. Create document record in DB (Task 4)
  5. Return document metadata
- Handle exceptions and return meaningful error messages
- **Files to create:** `services/upload_service.py`
- **Acceptance:** Service orchestrates validation, storage, and DB persistence correctly

---

### **Task 6: Upload API Endpoint**
- Create `routes/documents.py` (or add to existing routes file)
- Implement `POST /api/v1/documents/upload` endpoint:
  - Accept `multipart/form-data` with `file` field
  - Extract `user_id` from auth context (or request body for now)
  - Call `upload_service.upload_document(user_id, file)`
  - Return 201 with document metadata JSON
  - Return 400 for validation errors
  - Return 500 for storage/DB errors
- **Files to modify:** `routes/documents.py`, `app.py` (register blueprint)
- **Acceptance:** Endpoint responds correctly per API spec, returns proper status codes

---

### **Task 7: Integration Test**
- Create `tests/test_upload_integration.py`
- Test cases:
  - Valid PDF upload → 201 response, file stored, DB record created
  - Invalid file type → 400 response
  - File too large → 400 response
  - Storage failure simulation → 500 response
- **Files to create:** `tests/test_upload_integration.py`
- **Acceptance:** All tests pass, coverage ≥ 80% for upload flow

---

## Dependencies
- **Python packages:** `boto3` (S3), `python-magic` or `mimetypes` (MIME detection), `werkzeug` (file handling)
- **Environment variables:** `STORAGE_TYPE`, `LOCAL_STORAGE_PATH`, `S3_BUCKET_NAME`, `S3_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

---

## Notes for AI Assistant
- Strictly follow `.clinerules` for code style, error handling, and logging
- Use existing database connection patterns from `database-schema.md`
- Ensure all file paths are sanitized to prevent directory traversal
- Log all upload attempts (success/failure) for audit trail
- Do NOT implement authentication in this epic (assume `user_id` is provided)
- Storage backend selection must be runtime-configurable via env var

---

