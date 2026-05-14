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
| **hub_type** | **VARCHAR(50)** | **NULL, INDEXED** | **Legal knowledge hub type: 'legislation', 'judicial_precedent', 'advisory_opinion'. Only set for reference_law documents. Used by Global RAG (Phase 2a) to route queries to the correct hub. (added in migration 0015)** |
| **extracted_text** | **TEXT** | **BLANK, DEFAULT ''** | **Full extracted PDF text for monitoring/debug (added in migration 0012)** |
| **extraction_method** | **VARCHAR(20)** | **NULL** | **Which extractor succeeded: pymupdf, pdfplumber, tesseract (added in migration 0012)** |
| **garbled_score** | **FLOAT** | **NULL** | **Garbled detection ratio (0.0–1.0) from `_compute_garbled_ratio()` (added in migration 0012)** |
| **tables_data** | **JSONB** | **DEFAULT '[]', BLANK** | **Extracted table data as a list of dicts with keys: 'page', 'bbox', 'markdown', 'semantic_text'. Populated during `extract_text_from_pdf` when `TABLE_EXTRACTION_ENABLED=True`. Used by `chunk_document` to attach tables as metadata on chunks. (added in migration 0016)** |
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
| embedding | VECTOR(1024) | NULL | Ollama bge-m3 embedding vector |
| metadata | JSONB | DEFAULT '{}' | Additional metadata |
| **search_vector** | **TSVECTOR** | **NULL** | **Full-text search vector, auto-populated by DB trigger on INSERT/UPDATE of content using `to_tsvector('simple', ...)`. Added in Epic 6 (migration 0006).** |
| **law_name** | **VARCHAR(500)** | **NULL, INDEXED** | **Denormalized law name for efficient filtering. Populated from `metadata['law_name']` during chunking. Added in Epic 6 (migration 0006).** |
| **legal_status** | **VARCHAR(50)** | **NULL, INDEXED** | **Denormalized legal status for filtering (e.g., "valid", "obsolete"). Populated from `metadata['legal_status']` during chunking. Added in Epic 6 (migration 0006).** |
| **approval_date** | **DATE** | **NULL, INDEXED** | **Denormalized approval date for date-range filtering. Populated from `metadata['approval_date']` during chunking. Added in Epic 6 (migration 0006).** |
| **legal_type** | **VARCHAR(50)** | **NULL, INDEXED** | **Denormalized legal segment type (e.g., "article", "note", "chapter"). Populated from `metadata['legal_type']` during chunking. Added in Epic 6 (migration 0006).** |
| **hub_type** | **VARCHAR(50)** | **NULL, INDEXED** | **Denormalized hub type for efficient per-hub filtering. Populated from parent document's `hub_type` during chunking. Used by Global RAG (Phase 2a) cross-document hybrid search. (added in migration 0015)** |
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
- **`idx_chunks_content_trgm`** on **`content`** USING **GIN** with **`gin_trgm_ops`** (for PostgreSQL `pg_trgm` trigram similarity search, added in migration 0010)
- **`idx_chunks_hub_type`** on **`hub_type`** (for per-hub filtering in Global RAG, added in migration 0015)

**Constraints:**
- UNIQUE(`document_id`, `chunk_index`)

**Triggers:**
- **`trg_chunk_search_vector`** — BEFORE INSERT OR UPDATE OF `content`, calls `update_chunk_search_vector()` function to auto-populate `search_vector` using `to_tsvector('simple', COALESCE(NEW.content, ''))`. Added in Epic 6 (migration 0006).
  - **IMPORTANT:** The `simple` configuration does NOT convert Persian digits (۰۱۲۳۴۵۶۷۸۹) to English digits (0123456789). Content must be normalized at the application layer via `PersianNormalizer.normalize_for_fts()` before saving. This normalization was added in migration 0009 (see below).
  - **Migration 0010** (see below) adds the `pg_trgm` extension and a GIN index on `content` for trigram similarity search, which provides fuzzy matching for OCR errors and spelling variations.

---

### 4. conversations
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | Conversation unique identifier |
| user_id | UUID | FOREIGN KEY (users.id) ON DELETE CASCADE | Conversation owner |
| **document_id** | **UUID** | **FOREIGN KEY (documents.id) ON DELETE CASCADE, NULL** | **Related document (NULL for Global RAG conversations). Made nullable in Phase 3 (migration 0003 of conversations app).** |
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
| **hub_metadata** | **JSONB** | **NULL** | **Global RAG metadata: stores per-hub search results, sub-queries, hub-level source counts, and Phase 2b per-hub partial answers (content, token_usage, error). Only populated when `mode='global_rag'`. (added in migration 0002 of conversations app; Phase 2b partial_answer fields added 2026-05-12, no schema migration needed — JSONB is schema-less)** |
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
- Default embedding dimension: 1024 (Ollama bge-m3)
- All timestamps in UTC
- Use CASCADE delete for related records
- **Epic 6 (migration 0006):** Added `search_vector` (TSVECTOR with GIN index), denormalized metadata columns (`law_name`, `legal_status`, `approval_date`, `legal_type`), and a DB trigger `trg_chunk_search_vector` that auto-populates `search_vector` from `content` using `to_tsvector('simple', ...)` on INSERT/UPDATE.
- **Migration 0009 (RAG Retrieval Fix Sprint):** Normalizes Persian digits in existing `DocumentChunk.content` to English digits via `PersianNormalizer.normalize_for_fts()`. This ensures the `search_vector` built by the trigger contains English-digit tokens (e.g., `'195'` instead of `'۱۹۵'`), so FTS queries with English digits match correctly. After this migration, new chunks are also normalized at creation time in `chunk_document()`.
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

---

## Migrations

### Migration 0010 — Add pg_trgm Extension and Trigram Index
- **File:** `src/backend/documents/migrations/0010_add_pg_trgm.py`
- **Operations:**
  1. Installs the `pg_trgm` PostgreSQL extension via `TrigramExtension()`.
  2. Creates a GIN index on `document_chunks.content` using `gin_trgm_ops` operator class:
     ```sql
     CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm
     ON document_chunks USING gin (content gin_trgm_ops);
     ```
- **Purpose:** Enables trigram similarity search (`similarity()`, `show_trgm()`) for fuzzy matching of Persian legal text, catching OCR errors, spelling variations, and partial matches.
- **Dependencies:** Depends on migration `0009_normalize_chunk_digits`.
- **Applied:** Yes (via `docker-compose exec backend python manage.py migrate`).

### Migration 0012 — Add extracted_text, extraction_method, garbled_score
- **File:** `src/backend/documents/migrations/0012_add_extracted_text_and_extraction_metadata.py`
- **Changes:**
  - Added `extracted_text` (TextField, blank=True, default="") to `documents` table
  - Added `extraction_method` (CharField, max_length=20, null=True, blank=True) to `documents` table
  - Added `garbled_score` (FloatField, null=True, blank=True) to `documents` table
- **Purpose:** Stores the full extracted PDF text, the extraction method that succeeded (pymupdf/pdfplumber/tesseract), and the garbled detection ratio for the developer monitoring page at `/monitoring/:documentId`.
- **Dependencies:** Depends on migration `0011_normalize_presentation_forms`.
- **Applied:** Pending (run `docker-compose exec backend python manage.py migrate` to apply).

### Migration 0015 — Add hub_type to documents and document_chunks (Phase 2a — Global RAG)
- **File:** `src/backend/documents/migrations/0015_document_hub_type_documentchunk_hub_type_and_more.py`
- **Changes:**
  - Added `hub_type` column to `documents` table: `VARCHAR(50)`, nullable, indexed
  - Added `hub_type` column to `document_chunks` table: `VARCHAR(50)`, nullable, indexed (denormalized from parent document)
  - Choices: `'legislation'` (قوانین مصوب), `'judicial_precedent'` (رویه‌های قضایی), `'advisory_opinion'` (نظریات مشورتی)
  - Created `idx_chunks_hub_type` index on `document_chunks.hub_type`
  - **Purpose:** Enables per-hub filtering in Global RAG cross-document hybrid search without JOINs
  - **Note:** The GIN index `chunk_search_vector_gin` was NOT re-added (it already exists from migration 0014)
  - **Applied:** Yes (via `docker-compose exec backend python manage migrate documents 0015`)

### Migration 0016 — Add tables_data to documents (Phase 4 — Table Extraction)
- **File:** `src/backend/documents/migrations/0016_add_tables_data_field.py`
- **Changes:**
  - Added `tables_data` column to `documents` table: `JSONB`, default `[]`, blank
  - **Purpose:** Stores extracted table data (page, bbox, markdown, semantic_text) for PDF tables. Populated during `extract_text_from_pdf` when `TABLE_EXTRACTION_ENABLED=True`. Used by `chunk_document` to attach tables as metadata on chunks for dual-representation embedding.
  - **No GIN index:** `tables_data` is metadata-only and not queried directly; it is read during chunking and embedding.
  - **Applied:** Pending (run `docker-compose exec backend python manage.py migrate` to apply).

### Migration 0002 (conversations) — Add hub_metadata to messages (Phase 2a — Global RAG)
- **File:** `src/backend/conversations/migrations/0002_message_hub_metadata.py`
- **Changes:**
  - Added `hub_metadata` column to `messages` table: `JSONB`, nullable
  - **Purpose:** Stores Global RAG metadata including per-hub search results, sub-queries, and hub-level source counts for assistant messages generated with `mode='global_rag'`
  - **Applied:** Yes (via `docker-compose exec backend python manage migrate conversations 0002`)

### Migration 0011 — Normalize Arabic Presentation Forms in Chunk Content
- **File:** `src/backend/documents/migrations/0011_normalize_presentation_forms.py`
- **Operations:**
  1. Iterates over all existing `DocumentChunk` rows in batches of 500.
  2. Calls the updated `PersianNormalizer.normalize_for_fts()` on each chunk's `content`.
  3. Saves the normalized content, which triggers the `trg_chunk_search_vector` trigger to regenerate the `search_vector`.
- **Purpose:** Re-normalizes all existing chunk content with the updated `normalize_for_fts()` method, which now applies `unicodedata.normalize('NFKC', text)` as its first step. This converts Arabic Presentation Forms-B (U+FE70–U+FEFF) — positional glyph variants commonly produced by PDF extractors — to standard Unicode codepoints, fixing both Ctrl+F and FTS search failures for Persian text.
- **Dependencies:** Depends on migration `0010_add_pg_trgm`.
- **Applied:** Pending (run `docker-compose exec backend python manage.py migrate` to apply).

---

## Management Commands

### `import_chunked_data` — Import Pre-Chunked Legal Datasets (Phase 2a)

- **File:** [`src/backend/documents/management/commands/import_chunked_data.py`](src/backend/documents/management/commands/import_chunked_data.py)
- **Created:** 2026-05-12
- **Purpose:** Ingests pre-chunked JSON datasets (already split into chunks externally) into the 3 legal knowledge hubs (`legislation`, `judicial_precedent`, `advisory_opinion`). Designed for datasets that have been chunked by an external process (e.g., Persian legal NLP pipeline).
- **Test file:** [`src/backend/documents/tests/test_import_chunked_data.py`](src/backend/documents/tests/test_import_chunked_data.py) (19 tests)

#### Folder-to-Hub Mapping

| Folder Name (Persian) | Hub Type | Description |
|---|---|---|
| `هاب قوانین مصوب` | `legislation` | Approved legislation (قوانین مصوب) |
| `هاب رویه های قضایی` | `judicial_precedent` | Judicial precedents (رویه‌های قضایی) |
| `هاب نظریات مشورتی و رویه عملی` | `advisory_opinion` | Advisory opinions (نظریات مشورتی) |

#### Hub Type Normalization

The command normalizes hub type aliases via `HUB_TYPE_ALIASES`:
- `"precedent"` → `"judicial_precedent"`
- `"advisory"` → `"advisory_opinion"`
- `"legislation"` → `"legislation"`
- `"judicial_precedent"` → `"judicial_precedent"`
- `"advisory_opinion"` → `"advisory_opinion"`

#### Supported Data Formats

The command auto-detects 3 JSON formats:

**Format A (Legislation Object):**
```json
{
  "source_file": "قانون_مجازات_اسلامی",
  "chunks": [
    {
      "chunk_id": "madde_1",
      "text": "متن ماده ۱...",
      "metadata": {
        "chunk_index": 0,
        "page_start": 1,
        "page_end": 1,
        "law_name": "قانون مجازات اسلامی",
        "legal_type": "article",
        "legal_number": "1"
      }
    }
  ]
}
```
- Root is a JSON object with a `"chunks"` key (array of chunk objects)
- One document created per file; title from `source_file`

**Format B (Precedent Flat Array):**
```json
[
  {
    "chunk_id": "chunk_001",
    "text": "متن رأی...",
    "metadata": {
      "hub_type": "precedent",
      "full_title": "رأی وحدت رویه شماره ۷۴۲",
      "chunk_index": 0,
      "page_start": 1,
      "page_end": 1,
      "law_name": "رأی وحدت رویه شماره ۷۴۲"
    }
  }
]
```
- Root is a JSON array; hub_type detected from `metadata.hub_type` in first chunk
- Documents grouped by `full_title` in metadata

**Format C (Advisory Flat Array):**
```json
[
  {
    "chunk_id": "chunk_001",
    "text": "متن نظریه...",
    "metadata": {
      "parent_title": "نظریه شماره ۷/۹۸/۱۲۳۴",
      "chunk_index": 0,
      "page_start": 1,
      "page_end": 1,
      "law_name": "نظریه شماره ۷/۹۸/۱۲۳۴"
    }
  }
]
```
- Root is a JSON array; hub_type derived from parent folder name
- Documents grouped by `parent_title` in metadata

#### Idempotency

- Uses `metadata__chunk_id` lookup on `DocumentChunk` to skip already-imported chunks
- Safe to re-run; previously imported chunks are skipped

#### Transactional Integrity

- Each document group is processed within `transaction.atomic()`
- If any chunk in a document group fails, the entire document is rolled back

#### Embedding

- Uses `batch_generate_embeddings()` from [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py)
- Default batch size: 16 (configurable via `--embedding-batch-size`)
- Designed for bge-m3 (1024-dim) on 4GB VRAM

#### Usage

```bash
# Dry-run (validate without writing)
docker-compose exec backend python manage.py import_chunked_data \
  /data/chunked_datasets --dry-run

# Actual import
docker-compose exec backend python manage.py import_chunked_data \
  /data/chunked_datasets

# Custom embedding batch size
docker-compose exec backend python manage.py import_chunked_data \
  /data/chunked_datasets --embedding-batch-size 32

# Assign documents to a specific user
docker-compose exec backend python manage.py import_chunked_data \
  /data/chunked_datasets --user-id <user-uuid>
```

#### Data Injected (2026-05-12)

| Hub Type | Documents | Chunks | All Embedded |
|---|---|---|---|
| `legislation` | 2 | 4,612 | ✅ |
| `judicial_precedent` | 1,301 | 5,865 | ✅ |
| `advisory_opinion` | 1,769 | 8,450 | ✅ |
| **Total** | **3,072** | **18,927** | ✅ |

- 2 chunks skipped (empty `text` field)
- All 18,927 chunks embedded via `batch_generate_embeddings()` with batch size 16
- Superuser `admin@docuchat.local` used as default owner

### Reimport Command

A dedicated management command [`reimport_legislation_hub`](src/backend/documents/management/commands/reimport_legislation_hub.py) was created to:

1. **Purge** all existing legislation hub data (`hub_type='legislation'`)
2. **Re-import** from pre-chunked JSON files (Format B — flat array of chunks)
3. **Group** chunks by `metadata.source` (law name) — one Document per unique law
4. **Generate embeddings** via `batch_generate_embeddings()` with configurable batch size

**Key differences from `import_chunked_data`:**
- Groups by `metadata.source` instead of `full_title`/`parent_title`
- Only operates on `hub_type='legislation'`
- Always purges existing legislation data before import (idempotent)
- Preserves all original metadata fields (`chunk_id`, `madde_number`, `madde_suffix`, `madde_raw`, etc.)

**Usage:**
```bash
# Dry-run
docker-compose exec backend python manage.py reimport_legislation_hub \
    --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws --dry-run

# Actual import
docker-compose exec backend python manage.py reimport_legislation_hub \
    --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws
```

**Test coverage:** 20 tests covering purge isolation, import, embedding, dry-run, error handling, idempotency, metadata preservation, and user assignment.
