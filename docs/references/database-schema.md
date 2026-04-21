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
| file_path | VARCHAR(1000) | NOT NULL | Storage path |
| file_size | BIGINT | NOT NULL | File size in bytes |
| mime_type | VARCHAR(100) | NOT NULL | File MIME type |
| total_pages | INTEGER | NULL | Total page count |
| status | VARCHAR(50) | DEFAULT 'uploaded' | processing status: uploaded, processing, completed, failed |
| error_message | TEXT | NULL | Error details if failed |
| created_at | TIMESTAMP | DEFAULT NOW() | Upload timestamp |
| updated_at | TIMESTAMP | DEFAULT NOW() | Last update timestamp |

**Indexes:**
- `idx_documents_user_id` on `user_id`
- `idx_documents_status` on `status`
- `idx_documents_created_at` on `created_at`

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
| token_hash | VARCHAR(255) | UNIQUE, NOT NULL | Hashed refresh token |
| expires_at | TIMESTAMP | NOT NULL | Expiration timestamp |
| created_at | TIMESTAMP | DEFAULT NOW() | Creation timestamp |

**Indexes:**
- `idx_refresh_tokens_user_id` on `user_id`
- `idx_refresh_tokens_token_hash` on `token_hash`
- `idx_refresh_tokens_expires_at` on `expires_at`

---

## PostgreSQL Extensions Required
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

---

## Migration Notes

- Use pgvector extension for similarity search on embeddings
- Default embedding dimension: 1536 (OpenAI text-embedding-3-small)
- All timestamps in UTC
- Use CASCADE delete for related records
- JSONB for flexible metadata storage


---