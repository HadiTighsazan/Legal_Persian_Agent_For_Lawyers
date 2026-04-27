Here is the complete **Implementation Plan for Epic E-05 — Embedding & Vector Storage**.

---

## Implementation Plan: E-05 — Embedding & Vector Storage

### Architecture Overview

```mermaid
flowchart TD
    A[Client] -->|POST /documents/{id}/embed| B[DocumentEmbedView]
    A -->|POST /chunks/batch-embed| C[ChunkBatchEmbedView]
    A -->|POST /chunks/{id}/re-embed| D[ChunkReEmbedView]
    A -->|GET /tasks/{id}| E[TaskStatusView]
    
    B --> F[EmbeddingService.generate_embeddings_for_document]
    F --> G[Create ProcessingTask embed/pending]
    G --> H[embed_document Celery Task]
    
    C --> I[EmbeddingService.batch_embed_chunks]
    D --> J[EmbeddingService.reembed_chunk]
    
    H --> K[EmbeddingService.batch_generate_embeddings]
    K --> L[OpenAI API text-embedding-3-small]
    L --> M[Update chunks.embedding]
    M --> N[Update ProcessingTask progress/status]
    
    subgraph "New Files"
        S1[src/backend/documents/services/embedding_service.py]
        S2[src/backend/documents/tasks/embedding_tasks.py]
        S3[src/backend/documents/serializers.py - add embed serializers]
        S4[src/backend/documents/views.py - add embed views]
        S5[src/backend/documents/urls.py - add embed routes]
        S6[src/backend/scripts/reembed_all.py]
    end
```

### Key Observations from Codebase Analysis

1. **Tech Stack**: Django 4.2 + DRF + Celery + PostgreSQL. The project uses `APIView` classes (not ViewSets), manual pagination, and Celery chains for async processing.
2. **Existing Patterns**: Views use `IsAuthenticated`, ownership checks (`document.user != request.user`), and consistent error format `{"error": "...", "message": "..."}`.
3. **`DocumentChunk.embedding`** is currently stored as `TextField(null=True, blank=True)` with a comment "Temporary until pgvector is set up". The PRD says schema is ready with `VECTOR(1536)`, but the actual model still uses `TextField`. **A migration will be needed** to change this to pgvector's `VectorField`.
4. **OpenAI is not in requirements.txt** — `openai` package must be added.
5. **`ProcessingTask` model** already supports `task_type='embed'` in its choices.
6. **`settings.py`** already has `OPENAI_API_KEY` env var configured.

---

### Task Breakdown

#### Task 1: Add `openai` dependency & pgvector migration

**Files to modify:**
- [`src/backend/requirements.txt`](src/backend/requirements.txt) — add `openai>=1.0.0`
- [`src/backend/documents/models.py`](src/backend/documents/models.py:92) — change `embedding` from `TextField` to pgvector's `VectorField(dimensions=1536, null=True, blank=True)`
- Create migration: `src/backend/documents/migrations/0004_add_pgvector_embedding.py`

**Details:**
- Add `django-pgvector` to requirements or use raw SQL via `RunSQL` migration (since the project doesn't currently use `django-pgvector`).
- The migration must: (1) ensure `CREATE EXTENSION IF NOT EXISTS vector`, (2) alter `embedding` column type to `VECTOR(1536)`, (3) create `idx_chunks_embedding` ivfflat index.
- Update [`docs/references/database-schema.md`](docs/references/database-schema.md) to reflect the change from `TextField` to `VECTOR(1536)`.

**Acceptance:** Migration runs without error; `embedding` column is `VECTOR(1536)`; ivfflat index exists.

---

#### Task 2: Implement Embedding Service

**New file:** [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py)

**Functions to implement:**

1. **`generate_embedding(text: str) -> list[float] | None`**
   - Calls OpenAI `text-embedding-3-small` via `openai.Embedding.create()`
   - Returns 1536-dimension vector
   - Handles rate limits with exponential backoff (use `tenacity` or manual retry)
   - Handles empty/null text → returns `None`
   - Logs `document_id`, `chunk_id`, generation time, API errors

2. **`batch_generate_embeddings(texts: list[str]) -> list[list[float] | None]`**
   - Uses OpenAI batch embedding API
   - Splits into sub-batches of 50 (per PRD performance target)
   - Returns results in same order as input
   - Logs which items failed

3. **`generate_embeddings_for_document(document_id: str) -> None`**
   - Fetches all chunks for document where `embedding IS NULL`
   - Processes in batches of 50
   - Updates `chunks.embedding` for each chunk
   - Updates `ProcessingTask` progress

4. **`batch_embed_chunks(chunk_ids: list[str]) -> dict`**
   - Validates chunk IDs exist
   - Fetches chunk text for each ID
   - Skips chunks that already have embeddings
   - Calls `batch_generate_embeddings()`
   - Stores embeddings
   - Returns `{"processed": N, "skipped": M, "failed": K}`

5. **`reembed_chunk(chunk_id: str) -> dict`**
   - Fetches chunk by ID
   - Calls `generate_embedding()`
   - Replaces existing embedding
   - Returns `{"chunk_id": "...", "embedding_updated": true}`

**Acceptance:** All functions work correctly with mocked OpenAI calls in tests.

---

#### Task 3: Add Embedding Serializers

**File to modify:** [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py)

**New serializers:**

1. **`DocumentEmbedResponseSerializer`** — for `POST /documents/{id}/embed` response
   ```python
   class DocumentEmbedResponseSerializer(serializers.Serializer):
       task_id = serializers.UUIDField()
       task_type = serializers.CharField(default="embed")
       status = serializers.CharField(default="pending")
       document_id = serializers.UUIDField()
       total_chunks = serializers.IntegerField()
   ```

2. **`ChunkBatchEmbedRequestSerializer`** — for `POST /chunks/batch-embed` request
   ```python
   class ChunkBatchEmbedRequestSerializer(serializers.Serializer):
       chunk_ids = serializers.ListField(child=serializers.UUIDField())
   ```

3. **`ChunkBatchEmbedResponseSerializer`** — for batch-embed response
   ```python
   class ChunkBatchEmbedResponseSerializer(serializers.Serializer):
       processed = serializers.IntegerField()
       skipped = serializers.IntegerField()
       failed = serializers.IntegerField()
   ```

4. **`ChunkReEmbedResponseSerializer`** — for re-embed response
   ```python
   class ChunkReEmbedResponseSerializer(serializers.Serializer):
       chunk_id = serializers.UUIDField()
       embedding_updated = serializers.BooleanField()
   ```

---

#### Task 4: Implement Embedding Views

**File to modify:** [`src/backend/documents/views.py`](src/backend/documents/views.py)

**New views:**

1. **`DocumentEmbedView`** — `POST /documents/{document_id}/embed`
   - Auth: `IsAuthenticated`
   - Ownership check (404/403 pattern same as existing views)
   - Fetches document, counts chunks where `embedding IS NULL`
   - Creates `ProcessingTask(task_type='embed', status='pending')`
   - Calls Celery task `embed_document.delay(document_id, task_id)`
   - Returns `202 Accepted` with task info

2. **`ChunkBatchEmbedView`** — `POST /chunks/batch-embed`
   - Auth: `IsAuthenticated`
   - Validates request body with `ChunkBatchEmbedRequestSerializer`
   - Calls `embedding_service.batch_embed_chunks()`
   - Returns `200 OK` with processed/skipped/failed counts

3. **`ChunkReEmbedView`** — `POST /chunks/{chunk_id}/re-embed`
   - Auth: `IsAuthenticated`
   - Verifies chunk exists and belongs to user's document
   - Calls `embedding_service.reembed_chunk()`
   - Returns `200 OK` with chunk_id and embedding_updated

4. **`TaskStatusView`** — `GET /tasks/{task_id}`
   - Auth: `IsAuthenticated`
   - Fetches `ProcessingTask` by ID
   - Verifies ownership via task's document
   - Returns task status, progress, error_message, etc.

---

#### Task 5: Register Embedding Routes

**File to modify:** [`src/backend/documents/urls.py`](src/backend/documents/urls.py)

**New URL patterns:**
```python
path("<uuid:document_id>/embed/", DocumentEmbedView.as_view(), name="document-embed"),
```

**File to create:** [`src/backend/tasks/urls.py`](src/backend/tasks/urls.py) (new)

```python
urlpatterns = [
    path("<uuid:task_id>/", TaskStatusView.as_view(), name="task-status"),
]
```

**File to modify:** [`src/backend/config/urls.py`](src/backend/config/urls.py)

Uncomment/add:
```python
path('tasks/', include('tasks.urls')),
```

Also register the batch-embed and re-embed routes. Since these operate on chunks (not documents), they could go in a new `chunks/` URL namespace or stay under `documents/`. Per the PRD, the endpoints are:
- `POST /api/chunks/batch-embed` → add to `documents/urls.py` or create `chunks/urls.py`
- `POST /api/chunks/{chunk_id}/re-embed` → same

**Recommendation:** Add these to `documents/urls.py` since chunks are document children:
```python
path("chunks/batch-embed/", ChunkBatchEmbedView.as_view(), name="chunk-batch-embed"),
path("chunks/<uuid:chunk_id>/re-embed/", ChunkReEmbedView.as_view(), name="chunk-re-embed"),
```

---

#### Task 6: Implement Embedding Celery Task

**New file:** [`src/backend/documents/tasks/embedding_tasks.py`](src/backend/documents/tasks/embedding_tasks.py)

**Celery task:**

```python
@shared_task(bind=True, autoretry_for=(...,), max_retries=3, retry_backoff=True)
def embed_document(self, document_id: str, task_id: str) -> None:
```

**Logic:**
1. Fetch `ProcessingTask` by `task_id`, set status to `running`
2. Fetch all chunks for document where `embedding IS NULL`
3. Process in batches of 50:
   - Call `batch_generate_embeddings()`
   - Update each chunk's `embedding` field
   - Update task `progress` (e.g., `int(batch_index / total_batches * 100)`)
4. On success: set task status to `completed`, update `completed_at`
5. On failure: set task status to `failed`, log error message
6. Log `document_id`, `task_id`, batch size, generation time per batch

---

#### Task 7: pgvector Index Verification

**File to create:** [`src/backend/documents/migrations/0005_verify_pgvector_index.py`](src/backend/documents/migrations/0005_verify_pgvector_index.py)

Or add as part of Task 1's migration. The SQL to run:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
ON document_chunks
USING ivfflat (embedding vector_cosine_ops);
```

**Verification:** Run a Django `check` or a test that executes `SELECT * FROM pg_indexes WHERE indexname = 'idx_chunks_embedding'` and asserts the index exists with type `ivfflat`.

---

#### Task 8: Re-embed Script

**New file:** [`src/backend/scripts/reembed_all.py`](src/backend/scripts/reembed_all.py)

**Logic:**
1. Query all chunks
2. Set `embedding = NULL` for all chunks
3. Iterate in batches of 500 chunks:
   - For each batch, trigger `embed_document` Celery tasks per document
   - Log progress (e.g., "Processed 500/50000 chunks")
4. Handle large datasets safely with memory-efficient batching

**Usage:** `docker-compose exec backend python scripts/reembed_all.py`

---

#### Task 9: Write Tests

**New test file:** [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py)

**Test categories (TDD: RED → GREEN → REFACTOR):**

1. **EmbeddingService unit tests:**
   - `test_generate_embedding_returns_1536_floats` — mock OpenAI
   - `test_generate_embedding_empty_text_returns_none`
   - `test_generate_embedding_handles_rate_limit` — retry on 429
   - `test_batch_generate_embeddings_returns_in_order`
   - `test_batch_generate_embeddings_handles_partial_failure`
   - `test_batch_embed_chunks_skips_existing_embeddings`
   - `test_reembed_chunk_overwrites_existing_embedding`

2. **View tests (following existing patterns in [`test_views.py`](src/backend/documents/tests/test_views.py)):**
   - `test_document_embed_returns_202_with_task_id`
   - `test_document_embed_nonexistent_document_returns_404`
   - `test_document_embed_other_users_document_returns_403`
   - `test_document_embed_unauthenticated_returns_401`
   - `test_batch_embed_validates_chunk_ids`
   - `test_batch_embed_handles_up_to_100_chunks`
   - `test_reembed_nonexistent_chunk_returns_404`
   - `test_reembed_other_users_chunk_returns_403`
   - `test_task_status_returns_correct_state`
   - `test_task_status_nonexistent_task_returns_404`

3. **Celery task tests (following patterns in [`test_tasks.py`](src/backend/documents/tests/test_tasks.py)):**
   - `test_embed_document_creates_embeddings_for_all_chunks`
   - `test_embed_document_updates_task_progress`
   - `test_embed_document_marks_task_completed`
   - `test_embed_document_handles_openai_failure`

---

#### Task 10: Update Reference Documentation

**Files to update:**
- [`docs/references/database-schema.md`](docs/references/database-schema.md) — confirm `embedding` column type is `VECTOR(1536)` (not `TextField`)
- [`docs/references/api-registry.md`](docs/references/api-registry.md) — add the 4 new endpoints with request/response schemas
- [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) — update after each step

---

### Execution Order Summary

| # | Task | Files | Type |
|---|------|-------|------|
| 1 | Add `openai` dependency & pgvector migration | `requirements.txt`, `models.py`, new migration | Modify |
| 2 | Implement Embedding Service | `documents/services/embedding_service.py` | **Create** |
| 3 | Add Embedding Serializers | `documents/serializers.py` | Modify |
| 4 | Implement Embedding Views | `documents/views.py` | Modify |
| 5 | Register Embedding Routes | `documents/urls.py`, `tasks/urls.py`, `config/urls.py` | Modify/Create |
| 6 | Implement Embedding Celery Task | `documents/tasks/embedding_tasks.py` | **Create** |
| 7 | pgvector Index Verification | Migration or test | Verify |
| 8 | Re-embed Script | `scripts/reembed_all.py` | **Create** |
| 9 | Write Tests | `documents/tests/test_embedding.py` | **Create** |
| 10 | Update Reference Docs | `database-schema.md`, `api-registry.md`, `wip-context.md` | Modify |

---

### Edge Cases & Error Handling (from PRD)

| Edge Case | Handling Strategy |
|-----------|------------------|
| Empty chunk text | Return `None` embedding, skip in batch |
| OpenAI API failure | Retry with exponential backoff (3 attempts) |
| Rate limits (429) | Exponential backoff with jitter |
| Partial batch failure | Log per-chunk failures, continue batch |
| Chunk deleted during processing | Catch `DocumentChunk.DoesNotExist`, log warning |
| Task restart after crash | Celery `acks_late=True` re-queues on worker crash |

---

