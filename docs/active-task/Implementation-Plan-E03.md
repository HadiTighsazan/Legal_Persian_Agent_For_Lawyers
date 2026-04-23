
### 📋 Step-by-Step Implementation Plan

#### Phase 0: Prerequisites & Configuration Fixes

**Task P0.1 — Update `requirements.txt`**
- **File:** [`src/backend/requirements.txt`](src/backend/requirements.txt)
- **Action:** Add `boto3>=1.34.0` and `python-magic>=0.4.27`
- **Why:** Needed for S3 storage backend and MIME type detection.

**Task P0.2 — Update `.env.example`**
- **File:** [`.env.example`](.env.example)
- **Action:** Add storage-related env vars under a new "Storage Configuration" section:
  - `STORAGE_TYPE=local` (values: `local` or `s3`)
  - `LOCAL_STORAGE_PATH=./media/documents`
  - `S3_BUCKET_NAME=docuchat-uploads`
  - `S3_REGION=us-east-1`
  - `AWS_ACCESS_KEY_ID=`
  - `AWS_SECRET_ACCESS_KEY=`

**Task P0.3 — Update `config/settings.py`**
- **File:** [`src/backend/config/settings.py`](src/backend/config/settings.py)
- **Actions:**
  1. Add storage config vars after the existing file upload settings (line ~231):
     ```python
     STORAGE_TYPE = env('STORAGE_TYPE', default='local')
     LOCAL_STORAGE_PATH = env('LOCAL_STORAGE_PATH', default=os.path.join(BASE_DIR, 'media/documents'))
     S3_BUCKET_NAME = env('S3_BUCKET_NAME', default='docuchat-uploads')
     S3_REGION = env('S3_REGION', default='us-east-1')
     ```
  2. Update `MAX_UPLOAD_SIZE` from 500MB to 50MB (per PRD spec): `50 * 1024 * 1024`
  3. Update `ALLOWED_FILE_TYPES` to include DOCX and TXT:
     ```python
     ALLOWED_FILE_TYPES = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain']
     ```

---

#### Phase 1: Database Migration (Task 1)

**Task 1.1 — Create migration `0002_add_storage_fields`**
- **File:** [`src/backend/documents/migrations/0002_add_storage_fields.py`](src/backend/documents/migrations/0002_add_storage_fields.py) (new)
- **Actions:**
  - Add `filename` field (`VARCHAR(255)`, nullable initially, then populate from `original_filename`, then make non-null)
  - Add `storage_type` field (`VARCHAR(20)`, default `'local'`)
  - Add index on `storage_type`
- **Note:** The existing `file_path` field serves as `storage_path`. No need to rename it (would break existing data). The PRD's `storage_path` maps to existing `file_path`.

**Files modified:** 1 new migration file.

---

#### Phase 2: Storage Abstraction Layer (Task 2)

**Task 2.1 — Create `documents/storage/__init__.py`**
- **File:** [`src/backend/documents/storage/__init__.py`](src/backend/documents/storage/__init__.py) (new)
- **Action:** Factory function `get_storage_backend()` that reads `settings.STORAGE_TYPE` and returns the appropriate backend instance.

**Task 2.2 — Create `documents/storage/base.py`**
- **File:** [`src/backend/documents/storage/base.py`](src/backend/documents/storage/base.py) (new)
- **Action:** Abstract `StorageBackend` class with:
  - `save_file(uploaded_file, relative_path) -> str` — saves file, returns storage path
  - `get_file_url(storage_path) -> str` — returns URL/path for retrieval
  - `delete_file(storage_path) -> bool` — deletes file

**Task 2.3 — Create `documents/storage/local.py`**
- **File:** [`src/backend/documents/storage/local.py`](src/backend/documents/storage/local.py) (new)
- **Action:** `LocalStorageBackend` implementing the abstract class using `settings.LOCAL_STORAGE_PATH`.

**Task 2.4 — Create `documents/storage/s3.py`**
- **File:** [`src/backend/documents/storage/s3.py`](src/backend/documents/storage/s3.py) (new)
- **Action:** `S3StorageBackend` implementing the abstract class using `boto3` client.

**Files created:** 4 new files.

---

#### Phase 3: File Validation Utility (Task 3)

**Task 3.1 — Create `documents/utils/__init__.py`**
- **File:** [`src/backend/documents/utils/__init__.py`](src/backend/documents/utils/__init__.py) (new, empty)

**Task 3.2 — Create `documents/utils/file_validator.py`**
- **File:** [`src/backend/documents/utils/file_validator.py`](src/backend/documents/utils/file_validator.py) (new)
- **Actions:**
  - `validate_file_type(filename, allowed_types=None)` — checks extension against `['.pdf', '.docx', '.txt']`
  - `validate_file_size(file, max_size_mb=50)` — checks file.size ≤ 50MB
  - Both raise descriptive `ValidationError` exceptions on failure

**Files created:** 2 new files.

---

#### Phase 4: Document Repository (Task 4)

**Task 4.1 — Create `documents/repositories/__init__.py`**
- **File:** [`src/backend/documents/repositories/__init__.py`](src/backend/documents/repositories/__init__.py) (new, empty)

**Task 4.2 — Create `documents/repositories/document_repository.py`**
- **File:** [`src/backend/documents/repositories/document_repository.py`](src/backend/documents/repositories/document_repository.py) (new)
- **Actions:**
  - `create_document(user, filename, original_filename, file_size, mime_type, file_path, storage_type)` → `Document` instance
  - `get_document_by_id(document_id)` → `Document` or `None`
  - `get_user_documents(user, page, page_size)` → paginated queryset

**Files created:** 2 new files.

---

#### Phase 5: Upload Service Layer (Task 5)

**Task 5.1 — Create `documents/services/__init__.py`**
- **File:** [`src/backend/documents/services/__init__.py`](src/backend/documents/services/__init__.py) (new, empty)

**Task 5.2 — Create `documents/services/upload_service.py`**
- **File:** [`src/backend/documents/services/upload_service.py`](src/backend/documents/services/upload_service.py) (new)
- **Actions:**
  - `upload_document(user, file)` method orchestrating:
    1. Validate file type (Task 3)
    2. Validate file size (Task 3)
    3. Generate unique filename: `{uuid}{ext}`
    4. Save file via storage backend (Task 2)
    5. Create DB record via repository (Task 4)
    6. Return document metadata dict
  - Proper exception handling → meaningful error messages

**Files created:** 2 new files.

---

#### Phase 6: Upload API Endpoint (Task 6)

**Task 6.1 — Create `documents/serializers.py`**
- **File:** [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) (new)
- **Action:** `DocumentUploadSerializer` and `DocumentResponseSerializer` using DRF serializers.

**Task 6.2 — Create `documents/views.py`**
- **File:** [`src/backend/documents/views.py`](src/backend/documents/views.py) (new)
- **Action:** `DocumentUploadView` (APIView or ViewSet) implementing `POST /documents/upload/`:
  - Accepts `multipart/form-data` with `file` field
  - Uses `JWTAuthentication` (auth required)
  - Returns 201 with metadata, 400 for validation errors, 500 for storage errors

**Task 6.3 — Create `documents/urls.py`**
- **File:** [`src/backend/documents/urls.py`](src/backend/documents/urls.py) (new)
- **Action:** Register `upload/` route.

**Task 6.4 — Update `config/urls.py`**
- **File:** [`src/backend/config/urls.py`](src/backend/config/urls.py)
- **Action:** Uncomment and update the documents include:
  ```python
  path('documents/', include('documents.urls')),
  ```
  (Note: Nginx routes `/api/` prefix, so internally it's just `documents/`)

**Files created:** 3 new files. **Files modified:** 1.

---

#### Phase 7: Integration Test (Task 7)

**Task 7.1 — Create `src/backend/tests/test_upload_integration.py`**
- **File:** [`src/backend/tests/test_upload_integration.py`](src/backend/tests/test_upload_integration.py) (new)
- **Test cases:**
  1. Valid PDF upload → 201, file stored, DB record created
  2. Invalid file type (e.g., `.exe`) → 400
  3. File too large → 400
  4. Storage failure simulation → 500
  5. Unauthenticated request → 401

**Files created:** 1 new file.

---

### 📁 Complete File Inventory

#### New Files to Create (15 total):
| # | File Path | Purpose |
|---|-----------|---------|
| 1 | `src/backend/documents/storage/__init__.py` | Storage factory |
| 2 | `src/backend/documents/storage/base.py` | Abstract storage backend |
| 3 | `src/backend/documents/storage/local.py` | Local filesystem backend |
| 4 | `src/backend/documents/storage/s3.py` | S3 backend |
| 5 | `src/backend/documents/utils/__init__.py` | Utils package |
| 6 | `src/backend/documents/utils/file_validator.py` | File validation |
| 7 | `src/backend/documents/repositories/__init__.py` | Repositories package |
| 8 | `src/backend/documents/repositories/document_repository.py` | Document CRUD |
| 9 | `src/backend/documents/services/__init__.py` | Services package |
| 10 | `src/backend/documents/services/upload_service.py` | Upload orchestration |
| 11 | `src/backend/documents/serializers.py` | DRF serializers |
| 12 | `src/backend/documents/views.py` | API views |
| 13 | `src/backend/documents/urls.py` | URL routing |
| 14 | `src/backend/documents/migrations/0002_add_storage_fields.py` | Schema migration |
| 15 | `src/backend/tests/test_upload_integration.py` | Integration tests |

#### Existing Files to Modify (4 total):
| # | File Path | Changes |
|---|-----------|---------|
| 1 | `src/backend/requirements.txt` | Add `boto3`, `python-magic` |
| 2 | `.env.example` | Add storage env vars |
| 3 | `src/backend/config/settings.py` | Add storage config, fix MAX_UPLOAD_SIZE, fix ALLOWED_FILE_TYPES |
| 4 | `src/backend/config/urls.py` | Uncomment documents URL include |

---

### 📊 Execution Order (Recommended)

```
Phase 0 (Prerequisites)
  ├── P0.1: requirements.txt  ← Do FIRST (needed for imports)
  ├── P0.2: .env.example
  └── P0.3: settings.py

Phase 1 (Migration)
  └── Task 1: 0002_add_storage_fields.py

Phase 2 (Storage)
  ├── Task 2.1: storage/__init__.py
  ├── Task 2.2: storage/base.py
  ├── Task 2.3: storage/local.py
  └── Task 2.4: storage/s3.py

Phase 3 (Validation)
  ├── Task 3.1: utils/__init__.py
  └── Task 3.2: utils/file_validator.py

Phase 4 (Repository)
  ├── Task 4.1: repositories/__init__.py
  └── Task 4.2: repositories/document_repository.py

Phase 5 (Service)
  ├── Task 5.1: services/__init__.py
  └── Task 5.2: services/upload_service.py

Phase 6 (API)
  ├── Task 6.1: serializers.py
  ├── Task 6.2: views.py
  ├── Task 6.3: urls.py
  └── Task 6.4: config/urls.py (modify)

Phase 7 (Tests)
  └── Task 7.1: tests/test_upload_integration.py
```

---

### ⚠️ Key Design Decisions

1. **Reuse existing `file_path` field** instead of renaming to `storage_path` — avoids data migration complexity. The PRD's `storage_path` maps to `file_path`.
2. **Add `filename` (internal UUID-based name)** and **`storage_type`** as new fields via a new migration — the existing `0001_initial.py` already exists and is applied.
3. **Use Django's `File` upload handler** for the API — DRF handles `multipart/form-data` natively.
4. **Keep the `documents` app as the single source** for all document-related code (storage, utils, repos, services) rather than scattering across the project.
5. **Auth is required** for the upload endpoint (matching the existing JWT pattern in the project).

---

