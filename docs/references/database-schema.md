# Database Schema

## Core Tables

### 1. users
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | User unique identifier |
| email | VARCHAR(255) | UNIQUE, NOT NULL | User email |
| password | VARCHAR(128) | NOT NULL | Hashed password (Django AbstractBaseUser field, migrated from password_hash in E04-T4-T5) |
| full_name | VARCHAR(255) | NULL | User full name |
| is_active | BOOLEAN | DEFAULT TRUE | Account status |
| is_staff | BOOLEAN | DEFAULT FALSE | Staff access |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

**Indexes:**
- `idx_users_email` on `email`

---

### 2. documents
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Document unique identifier |
| user_id | UUID | FOREIGN KEY (users.id) ON DELETE CASCADE | Owner of document |
| title | VARCHAR(500) | NOT NULL | Document title |
| original_filename | VARCHAR(500) | NOT NULL | Original file name |
| **filename** | **VARCHAR(255)** | **NOT NULL** | **Sanitized storage filename (added in E03-P1)** |
| file_path | VARCHAR(1000) | NOT NULL | Storage path |
| file_size | BIGINT | NOT NULL | File size in bytes |
| mime_type | VARCHAR(100) | NOT NULL | File MIME type |
| total_pages | INTEGER | NULL | Total page count |
| status | VARCHAR(50) | DEFAULT 'uploaded' | Upload lifecycle status: uploaded → processing → completed/failed. This is the **authoritative** status for external consumers. Updated by pipeline tasks. |
| error_message | TEXT | NULL | Error details if failed |
| **storage_type** | **VARCHAR(20)** | **DEFAULT 'local', INDEXED** | **Storage backend: local / s3 (added in E03-P1)** |
| **processing_status** | **VARCHAR(20)** | **DEFAULT 'pending'** | **Pipeline granular status: pending → processing → completed/failed. Internal field for pipeline tracking; NOT authoritative for external consumers (use `status` instead). (added in E04-T2)** |
| **total_chunks** | **INTEGER** | **DEFAULT 0** | **Total number of text chunks after splitting (added in E04-T2)** |
| **extracted_text_length** | **INTEGER** | **DEFAULT 0** | **Length of extracted text in characters (added in E04-T2)** |
| **processing_error** | **TEXT** | **NULL** | **Error details from pipeline processing (added in E04-T2)** |
| **document_type** | **VARCHAR(20)** | **DEFAULT 'user_upload', INDEXED** | **Document type: 'user_upload' for regular files, 'reference_law' for system reference legal texts. Used by RAG service to determine whether to apply legal_status filters. (added in migration 0007)** |
| created_at | TIMESTAMP | DEFAULT NOW() | Upload timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

**Indexes:**
- `idx_documents_user_id` on `user_id`
- `idx_documents_status` on `status`
- `idx_documents_created_at` on `created_at`
- `idx_documents_storage_type` on `storage_type`
- `idx_documents_document_type` on `document_type`

---

### 3. document_chunks
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Chunk unique identifier |
| document_id | UUID | FOREIGN KEY (documents.id) ON DELETE CASCADE | Parent document |
| chunk_index | INTEGER | NOT NULL | Sequential chunk number |
| page_start | INTEGER | NOT NULL | Starting page number |
| page_end | INTEGER | NOT NULL | Ending page number |
| content | TEXT | NOT NULL | Extracted text content |
| token_count | INTEGER | NULL | Token count for LLM |
| embedding | VECTOR(768) | NULL | Ollama nomic-embed-text embedding vector |
| metadata | JSONB | DEFAULT '{}' | Additional metadata |
| **search_vector** | **TSVECTOR** | **NULL** | **Full-text search vector, auto-populated by DB trigger on INSERT/UPDATE of content using `to_tsvector('simple', ...)`. Added in Epic 6 (migration 0006).** |
| **law_name** | **VARCHAR(500)** | **NULL, INDEXED** | **Denormalized law name for efficient filtering. Populated from `metadata['law_name']` during chunking. Added in Epic 6 (migration 0006).** |
| **legal_status** | **VARCHAR(50)** | **NULL, INDEXED** | **Denormalized legal status for filtering (e.g., "valid", "obsolete"). Populated from `metadata['legal_status']` during chunking. Added in Epic 6 (migration 0006).** |
| **approval_date** | **DATE** | **NULL, INDEXED** | **Denormalized approval date for date-range filtering. Populated from `metadata['approval_date']` during chunking. Added in Epic 6 (migration 0006).** |
| **legal_type** | **VARCHAR(50)** | **NULL, INDEXED** | **Denormalized legal segment type (e.g., "article", "note", "chapter"). Populated from `metadata['legal_type']` during chunking. Added in Epic 6 (migration 0006).** |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |

**Indexes:**
- `idx_chunks_document_id` on `document_id`
- `idx_chunks_embedding` on `embedding` USING ivfflat (for pgvector similarity search)
- `idx_chunks_document_chunk` on `(document_id, chunk_index)`
- **`chunk_search_vector_gin`** on **`search_vector`** USING **GIN** (for PostgreSQL Full-Text Search, added in Epic 6)
- `idx_chunks_law_name` on `law_name` (added in Epic 6)
- `idx_chunks_legal_status` on `legal_status` (added in Epic 6)
- `idx_chunks_approval_date` on `approval_date` (added in Epic 6)
- `idx_chunks_legal_type` on `legal_type` (added in Epic 6)

**Constraints:**
- UNIQUE(`document_id`, `chunk_index`)

**Triggers:**
- **`trg_chunk_search_vector`** — BEFORE INSERT OR UPDATE OF `content`, calls `update_chunk_search_vector()` function to auto-populate `search_vector` using `to_tsvector('simple', COALESCE(NEW.content, ''))`. Added in Epic 6 (migration 0006).

---

### 4. conversations
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Conversation unique identifier |
| user_id | UUID | FOREIGN KEY (users.id) ON DELETE CASCADE | Conversation owner |
| document_id | UUID | FOREIGN KEY (documents.id) ON DELETE CASCADE | Related document |
| title | VARCHAR(500) | NULL | Conversation title |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last message timestamp |

**Indexes:**
- `idx_conversations_user_id` on `user_id`
- `idx_conversations_document_id` on `document_id`
- `idx_conversations_updated_at` on `updated_at`

---

### 5. messages
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Message unique identifier |
| conversation_id | UUID | FOREIGN KEY (conversations.id) ON DELETE CASCADE | Parent conversation |
| role | VARCHAR(20) | NOT NULL | Message role: user, assistant, system |
| content | TEXT | NOT NULL | Message content |
| sources | JSONB | DEFAULT '[]' | Array of source chunks used |
| token_usage | JSONB | NULL | Token usage stats |
| created_at | TIMESTAMP | DEFAULT NOW() | Message timestamp |

**Indexes:**
- `idx_messages_conversation_id` on `conversation_id`
- `idx_messages_created_at` on `created_at`

---

### 6. processing_tasks
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Task unique identifier |
| document_id | UUID | FOREIGN KEY (documents.id) ON DELETE CASCADE | Related document |
| task_type | VARCHAR(50) | NOT NULL | Task type: extract, chunk, embed |
| celery_task_id | VARCHAR(255) | INDEXED, NULL | Celery task ID (removed UNIQUE constraint in E04-T4 fix) |
| status | VARCHAR(50) | DEFAULT 'pending' | Task status: pending, running, completed, failed |
| progress | INTEGER | DEFAULT 0 | Progress percentage (0-100) |
| result | JSONB | NULL | Task result data |
| error_message | TEXT | NULL | Error details if failed |
| **retry_count** | **INTEGER** | **DEFAULT 0** | **Number of retry attempts (max 3, added in Task 7)** |
| started_at | TIMESTAMP | NULL | Task start time |
| completed_at | TIMESTAMP | NULL | Task completion time |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |

**Indexes:**
- `idx_tasks_document_id` on `document_id`
- `idx_tasks_celery_task_id` on `celery_task_id`
- `idx_tasks_status` on `status`

---

### 7. api_keys
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | API key unique identifier |
| user_id | UUID | FOREIGN KEY (users.id) ON DELETE CASCADE | Key owner |
| key_hash | VARCHAR(255) | UNIQUE, NOT NULL | Hashed API key |
| name | VARCHAR(255) | NOT NULL | Key name/description |
| is_active | BOOLEAN | DEFAULT TRUE | Key status |
| last_used_at | TIMESTAMP | NULL | Last usage timestamp |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |
| expires_at | TIMESTAMP | NULL | Expiration timestamp |

**Indexes:**
- `idx_api_keys_user_id` on `user_id`
- `idx_api_keys_key_hash` on `key_hash`

---

### 8. refresh_tokens
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Refresh token unique identifier |
| user_id | UUID | FOREIGN KEY (users.id) ON DELETE CASCADE | Token owner |
| token_hash | VARCHAR(255) | UNIQUE, NOT NULL | Hashed refresh token (SHA-256) |
| expires_at | TIMESTAMP | NOT NULL | Expiration timestamp |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |

**Indexes:**
- `idx_refresh_tokens_user_id` on `user_id`
- `idx_refresh_tokens_token_hash` on `token_hash`
- `idx_refresh_tokens_expires_at` on `expires_at`

**Model Methods (RefreshTokenManager):**
- `create_refresh_token(user, token_hash, expires_at)` — Create and persist a new refresh token
- `get_by_token_hash(token_hash)` — Look up a token by its SHA-256 hash
- `get_valid_tokens_for_user(user)` — Get all non-expired tokens for a user
- `cleanup_expired_tokens()` — Delete all expired tokens (for cron/scheduled task)
- `revoke_all_for_user(user)` — Delete all tokens for a user (e.g., force logout)
- `is_token_valid(token_hash)` — Check if a token exists and is valid

**Instance Methods:**
- `is_expired()` — Check if token has expired
- `is_valid()` — Check if token is not expired and user is active
- `get_remaining_lifetime()` — Get timedelta until expiration
- `revoke()` — Delete the token from database (permanent revocation)

**Implementation Notes:**
- Token hash is generated using `hashlib.sha256(token.encode()).hexdigest()`
- Tokens are deleted (not soft-deleted) on revocation/logout
- Access tokens are stateless JWT and remain valid until natural expiry
- Expired tokens can be cleaned up via `cleanup_expired_tokens()` manager method

---

## PostgreSQL Extensions Required
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
```

.. note::

   Full-Text Search (``tsvector``/``tsquery``) is built into PostgreSQL core
   and does **not** require a separate extension. The ``simple`` text search
   configuration is also available by default.

---

---

## Migration Notes

- Use pgvector extension for similarity search on embeddings
- Default embedding dimension: 768 (Ollama nomic-embed-text)
- All timestamps in UTC
- Use CASCADE delete for related records
- **Epic 6 (migration 0006):** Added `search_vector` (TSVECTOR with GIN index), denormalized metadata columns (`law_name`, `legal_status`, `approval_date`, `legal_type`), and a DB trigger `trg_chunk_search_vector` that auto-populates `search_vector` from `content` using `to_tsvector('simple', ...)` on INSERT/UPDATE.
- JSONB for flexible metadata storage

### Migration 0007 — Add `document_type` to `documents` Table
- **File:** `src/backend/documents/migrations/0007_add_document_type.py`
- **Changes:**
  - Added `document_type` column to `documents` table: `VARCHAR(20)`, default `'user_upload'`, indexed
  - Choices: `'user_upload'` (regular user-uploaded files), `'reference_law'` (system reference legal texts)
  - All existing rows default to `'user_upload'` (backward compatible)
  - Created `idx_documents_document_type` index on `document_type`
  - **Purpose:** Enables the RAG service to conditionally apply `legal_status` filters — only for `reference_law` documents

### Migration 0004 (E05-T1 — pgvector Embedding Support)
- **File:** `src/backend/documents/migrations/0004_alter_documentchunk_embedding.py`
- **Changes:**
  - Added `pgvector.django` to `INSTALLED_APPS`
  - Changed `embedding` column in `document_chunks` table from `TEXT` to `VECTOR(1536)` via `VectorField`
  - Created `idx_chunks_embedding` ivfflat index on `embedding` for cosine similarity search
  - Added `openai>=1.0.0` and `pgvector>=0.2.0` to `requirements.txt`

### System Check: pgvector Index Verification (Task 7)
- **File:** `src/backend/documents/checks.py`
- **Check IDs:** `documents.E001`–`E004`
- **Purpose:** Verifies `idx_chunks_embedding` ivfflat index exists on `document_chunks.embedding`
- **Trigger:** Runs automatically on `python manage.py check`, `runserver`, `migrate`
- **Test file:** `src/backend/documents/tests/test_pgvector_checks.py`

### Migration 0002 (E04-T4-T5 Bug Fixes)
- **File:** `src/backend/users/migrations/0002_rename_password_hash_to_password.py`
- **Changes:**
  - Renamed `password_hash` → `password` in `users` table via `RenameField`
  - Changed `password` column type from `VARCHAR(255)` to `VARCHAR(128)` (Django's standard for `AbstractBaseUser`)
  - This migration aligns the User model with Django's native `AbstractBaseUser` password handling
- `refresh_tokens` table created in Epic E02 (Authentication & User Management)
- `filename` and `storage_type` columns added to `documents` table in Epic E03 Phase 1 (migration `0002_add_storage_fields.py`)

### Epic 4 (E04) — Persian Legal Text Optimization (2026-05-05)
- **No schema changes required.** All legal metadata is stored in the existing `document_chunks.metadata` JSONB field.
- **`metadata` JSONB field usage for legal context:**
  ```json
  {
    "legal_type": "article",
    "legal_number": "1",
    "chapter": "اول",
    "law_name": "قانون مجازات اسلامی",
    "parent_article": null
  }
  ```
  - `legal_type`: One of `"article"`, `"note"`, `"clause"`, `"chapter"`, or `null` for non-legal chunks
  - `legal_number`: The article/note/clause number (e.g., `"1"`, `"2"`, `"الف"`)
  - `chapter`: Chapter heading if detected (e.g., `"اول"`, `"دوم"`)
  - `law_name`: Law name extracted from document title or first page
  - `parent_article`: For notes/clauses, the parent article number they belong to
- **`legal_context` property** added to `DocumentChunk` model (computed from `metadata`, not stored in DB):
  - Returns a formatted Persian string like `"قانون: قانون مجازات اسلامی | فصل: اول | ماده: 1"`
  - Used by search results and RAG context to provide legal provenance
- **New services** (no DB changes):
  - `documents/services/persian_normalizer.py` — Persian text normalization (Tatweel stripping, character normalization, half-space fixes)
  - `documents/services/legal_structure_detector.py` — Legal document structure parsing (مواد, تبصره, بند, فصل)
  - `documents/services/chunking_service.py` — Refactored with legal structural chunking and clause-boundary-aware overlap
- **New dependencies** (added to `requirements.txt`):
  - `hazm>=0.10.0` — Persian NLP library for character normalization
  - `pdfplumber>=0.11.0` — Fallback PDF extraction for RTL text
  - `pytesseract>=0.3.10` — OCR fallback for scanned Persian PDFs
