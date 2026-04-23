# Database Schema

## Core Tables

### 1. users
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PRIMARY KEY | User unique identifier |
| email | VARCHAR(255) | UNIQUE, NOT NULL | User email |
| password | VARCHAR(255) | NOT NULL | Hashed password (Django AbstractBaseUser field) |
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
| status | VARCHAR(50) | DEFAULT 'uploaded' | processing status: uploaded, processing, completed, failed |
| error_message | TEXT | NULL | Error details if failed |
| **storage_type** | **VARCHAR(20)** | **DEFAULT 'local', INDEXED** | **Storage backend: local / s3 (added in E03-P1)** |
| created_at | TIMESTAMP | DEFAULT NOW() | Upload timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

**Indexes:**
- `idx_documents_user_id` on `user_id`
- `idx_documents_status` on `status`
- `idx_documents_created_at` on `created_at`
- `idx_documents_storage_type` on `storage_type`

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
| embedding | VECTOR(1536) | NULL | OpenAI embedding vector |
| metadata | JSONB | DEFAULT '{}' | Additional metadata |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |

**Indexes:**
- `idx_chunks_document_id` on `document_id`
- `idx_chunks_embedding` on `embedding` USING ivfflat (for pgvector similarity search)
- `idx_chunks_document_chunk` on `(document_id, chunk_index)`

**Constraints:**
- UNIQUE(`document_id`, `chunk_index`)

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
| celery_task_id | VARCHAR(255) | UNIQUE, NULL | Celery task ID |
| status | VARCHAR(50) | DEFAULT 'pending' | Task status: pending, running, completed, failed |
| progress | INTEGER | DEFAULT 0 | Progress percentage (0-100) |
| result | JSONB | NULL | Task result data |
| error_message | TEXT | NULL | Error details if failed |
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

---

## Migration Notes

- Use pgvector extension for similarity search on embeddings
- Default embedding dimension: 1536 (OpenAI text-embedding-3-small)
- All timestamps in UTC
- Use CASCADE delete for related records
- JSONB for flexible metadata storage
- `refresh_tokens` table created in Epic E02 (Authentication & User Management)
- `filename` and `storage_type` columns added to `documents` table in Epic E03 Phase 1 (migration `0002_add_storage_fields.py`)
