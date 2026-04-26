# Task 2: Implement Embedding Service — Complete Prompt for Code Mode

## Context

This is **Task 2 of Epic E-05** (Embedding & Vector Storage). Task 1 (pgvector migration) is already complete — the `embedding` column on `document_chunks` is `VECTOR(1536)` with an ivfflat index.

You are implementing the core embedding service that wraps OpenAI's `text-embedding-3-small` model. This service will be used by:
- A Celery task (`embed_document`) for background document embedding
- API views (`ChunkBatchEmbedView`, `ChunkReEmbedView`) for on-demand embedding

## Tech Stack

- **Django 4.2** + **Django REST Framework**
- **Celery 5.3** for async task processing
- **PostgreSQL** with **pgvector** extension
- **OpenAI Python SDK** (`openai>=1.0.0` — already in `requirements.txt`)
- **Testing:** `pytest` + `pytest-django` + `unittest.mock`

## Existing Code Patterns to Follow

### 1. Service Layer Pattern
Services live in [`src/backend/documents/services/`](src/backend/documents/services/). They are plain Python modules with standalone functions (not classes). See [`chunking_service.py`](src/backend/documents/services/chunking_service.py) and [`processing_service.py`](src/backend/documents/services/processing_service.py) for reference.

### 2. Logging Pattern
```python
import logging
logger = logging.getLogger(__name__)
logger.info("[%s] Milestone description — extra_key=extra_value", document_id)
```

### 3. Error Handling Pattern
See [`error_handler.py`](src/backend/documents/services/error_handler.py) for `fail_processing_task()` and `log_milestone()`.

### 4. OpenAI Configuration
- API key is in `settings.OPENAI_API_KEY` (loaded from `.env` via `django-environ`)
- Use `from django.conf import settings` to access it

### 5. Models Reference

**`DocumentChunk`** ([`src/backend/documents/models.py:80`](src/backend/documents/models.py:80)):
- `id` — UUIDField, primary key
- `document` — ForeignKey to Document
- `chunk_index` — IntegerField
- `content` — TextField (the chunk text)
- `embedding` — `VectorField(dimensions=1536, null=True, blank=True)`
- `token_count` — IntegerField, nullable
- `metadata` — JSONField

**`ProcessingTask`** ([`src/backend/tasks/models.py:12`](src/backend/tasks/models.py:12)):
- `id` — UUIDField, primary key
- `document` — ForeignKey to Document
- `task_type` — CharField with choices: `extract`, `chunk`, `embed`
- `status` — CharField: `pending`, `running`, `completed`, `failed`
- `progress` — IntegerField (0-100)
- `result` — JSONField, nullable
- `error_message` — TextField, nullable
- `celery_task_id` — CharField, nullable
- `started_at`, `completed_at`, `created_at` — DateTimeFields

### 6. Test Patterns
- Tests use `django.test.TestCase`
- Views tests use `APIClient` with JWT auth headers
- Task tests use `_mock_celery_request()` context manager (see [`test_tasks.py:96`](src/backend/documents/tests/test_tasks.py:96))
- OpenAI calls should be mocked with `unittest.mock.patch`

---

## Implementation Steps

### Step 1: Create [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py)

Implement the following 5 functions:

#### 1. `generate_embedding(text: str) -> list[float] | None`

```python
def generate_embedding(text: str) -> list[float] | None:
```

**Requirements:**
- If `text` is empty or `None` after stripping → return `None`
- Initialize `openai.OpenAI(api_key=settings.OPENAI_API_KEY)` inside the function (or at module level with lazy init)
- Call `client.embeddings.create(model="text-embedding-3-small", input=text)`
- Extract and return the embedding vector (1536 floats) from `response.data[0].embedding`
- Handle `openai.RateLimitError` with exponential backoff (manual retry loop: 3 retries, 2^retry seconds delay)
- Handle `openai.APIError`, `openai.APIConnectionError`, `openai.AuthenticationError` gracefully → log error, return `None`
- Log: `"generate_embedding: Generated embedding (dimensions=%d)" % len(embedding)`
- Log API errors with `logger.exception()` or `logger.error()`

**Signature & type hints:**
```python
from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
import openai

logger = logging.getLogger(__name__)


def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for a single text string.
    
    Args:
        text: The text to embed.
        
    Returns:
        A list of 1536 floats, or None if the text is empty or an error occurs.
    """
    if not text or not text.strip():
        return None
    
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            embedding = response.data[0].embedding
            logger.info(
                "generate_embedding: Generated embedding (dimensions=%d)",
                len(embedding),
            )
            return embedding
        except openai.RateLimitError:
            if attempt < max_retries - 1:
                sleep_time = 2 ** attempt
                logger.warning(
                    "generate_embedding: Rate limited, retrying in %ds (attempt %d/%d)",
                    sleep_time, attempt + 1, max_retries,
                )
                time.sleep(sleep_time)
            else:
                logger.error("generate_embedding: Rate limit exceeded after %d retries", max_retries)
                return None
        except (openai.APIError, openai.APIConnectionError, openai.AuthenticationError) as e:
            logger.error("generate_embedding: API error — %s", e)
            return None
    
    return None
```

#### 2. `batch_generate_embeddings(texts: list[str]) -> list[list[float] | None]`

```python
def batch_generate_embeddings(texts: list[str]) -> list[list[float] | None]:
```

**Requirements:**
- Split `texts` into sub-batches of 50 (the PRD performance target)
- For each sub-batch, call `client.embeddings.create(model="text-embedding-3-small", input=sub_batch)`
- Map results back to original order using the index within each sub-batch
- For items that fail (empty text, API error), insert `None` at the corresponding position
- Log which indices failed: `"batch_generate_embeddings: Item %d failed — empty text"`
- Apply the same retry logic as `generate_embedding` for each sub-batch
- Return a list of the same length as `texts`

**Important:** The OpenAI batch API returns results in the order they were sent, so you can safely map by index.

#### 3. `generate_embeddings_for_document(document_id: str) -> None`

```python
def generate_embeddings_for_document(document_id: str) -> None:
```

**Requirements:**
- Fetch the `Document` by `document_id` (handle `DoesNotExist` → log and return)
- Find or create a `ProcessingTask` with `task_type='embed'` for this document
- Set task status to `"running"` and `started_at` to now
- Query `DocumentChunk.objects.filter(document=document, embedding__isnull=True).order_by('chunk_index')`
- Process chunks in batches of 50:
  - Extract `content` from each chunk in the batch
  - Call `batch_generate_embeddings([chunk.content for chunk in batch])`
  - For each chunk that got a non-None embedding, update `chunk.embedding = embedding` and `chunk.save(update_fields=['embedding'])`
  - Update `ProcessingTask.progress = int(processed_count / total_count * 100)`
- After all batches, set task status to `"completed"`, `progress` to 100, `completed_at` to now
- If any error occurs, set task status to `"failed"` with `error_message`
- Log milestones: `"generate_embeddings_for_document: Starting embedding for document %s"`, `"Batch %d/%d complete"`, etc.

#### 4. `batch_embed_chunks(chunk_ids: list[str]) -> dict`

```python
def batch_embed_chunks(chunk_ids: list[str]) -> dict:
```

**Requirements:**
- Query `DocumentChunk.objects.filter(id__in=chunk_ids)` to validate existence
- Separate chunks into:
  - Those with `embedding IS NOT NULL` → skipped
  - Those with `embedding IS NULL` → needs processing
- For chunks needing processing, extract their `content`
- Call `batch_generate_embeddings([chunk.content for chunk in needs_embedding])`
- For each chunk that got a non-None embedding, save it
- Return `{"processed": N, "skipped": M, "failed": K}` where:
  - `processed` = chunks that got new embeddings
  - `skipped` = chunks that already had embeddings
  - `failed` = chunks where embedding generation returned `None`

#### 5. `reembed_chunk(chunk_id: str) -> dict`

```python
def reembed_chunk(chunk_id: str) -> dict:
```

**Requirements:**
- Fetch `DocumentChunk` by `chunk_id` (handle `DoesNotExist` → return `{"error": "not_found", "message": "Chunk not found"}`)
- Call `generate_embedding(chunk.content)`
- If embedding is not None: set `chunk.embedding = embedding`, `chunk.save(update_fields=['embedding'])`
- Return `{"chunk_id": str(chunk.id), "embedding_updated": True}` on success
- Return `{"chunk_id": str(chunk.id), "embedding_updated": False, "error": "..."}` on failure

### Step 2: Create Tests

Create a new test file: [`src/backend/documents/tests/test_embedding_service.py`](src/backend/documents/tests/test_embedding_service.py)

**Test cases to cover:**

1. **`test_generate_embedding_success`** — Mock `openai.OpenAI` to return a fake 1536-dim vector; verify the function returns it correctly.

2. **`test_generate_embedding_empty_text`** — Call with `""` and `"   "`; verify returns `None`.

3. **`test_generate_embedding_rate_limit_retry`** — Mock `RateLimitError` for first 2 calls, then success on 3rd; verify retry logic works.

4. **`test_generate_embedding_api_error`** — Mock `APIError`; verify returns `None` and logs error.

5. **`test_batch_generate_embeddings_success`** — Mock OpenAI to return embeddings for 3 texts; verify correct order and dimensions.

6. **`test_batch_generate_embeddings_mixed_failures`** — Include empty text in batch; verify `None` at correct positions.

7. **`test_batch_generate_embeddings_sub_batch_splitting`** — Send 120 texts (should split into 3 sub-batches of 50, 50, 20); verify all return correctly.

8. **`test_generate_embeddings_for_document_success`** — Create a document with 3 chunks (embedding=NULL); mock `batch_generate_embeddings`; verify chunks get embeddings and `ProcessingTask` is marked completed.

9. **`test_generate_embeddings_for_document_no_chunks`** — Document with 0 chunks; verify task completes immediately with progress=100.

10. **`test_generate_embeddings_for_document_all_already_embedded`** — All chunks already have embeddings; verify task completes with progress=100 and no API calls.

11. **`test_batch_embed_chunks_mixed_state`** — 5 chunks: 2 already embedded, 2 succeed, 1 fails; verify return dict `{"processed": 2, "skipped": 2, "failed": 1}`.

12. **`test_batch_embed_chunks_invalid_ids`** — Call with non-existent chunk IDs; verify `processed=0, skipped=0, failed=0`.

13. **`test_reembed_chunk_success`** — Create chunk with existing embedding; call `reembed_chunk`; verify embedding is replaced and returns `{"chunk_id": ..., "embedding_updated": True}`.

14. **`test_reembed_chunk_not_found`** — Call with non-existent chunk ID; verify returns error dict.

### Step 3: Update [`src/backend/documents/services/__init__.py`](src/backend/documents/services/__init__.py)

Ensure the new module is importable (the `__init__.py` is currently empty, so no changes needed unless you want to re-export).

---

## Key Design Decisions

1. **OpenAI client initialization**: Create a new `openai.OpenAI()` instance per function call (not a global singleton). This is simpler and avoids issues with settings not being loaded at import time in Django.

2. **Retry strategy**: Manual exponential backoff (not `tenacity`). The project doesn't have `tenacity` as a dependency, and the retry logic is simple enough to implement inline.

3. **Error handling**: All API errors are caught and logged. Functions return `None` or error dicts rather than raising exceptions, following the existing service pattern.

4. **Batch size**: 50 per sub-batch, as specified in the PRD performance target.

5. **VectorField assignment**: pgvector's `VectorField` accepts a Python list of floats directly. No special serialization needed.

---

## Files to Create/Modify

| Action | File |
|--------|------|
| **Create** | [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) |
| **Create** | [`src/backend/documents/tests/test_embedding_service.py`](src/backend/documents/tests/test_embedding_service.py) |

---

## Acceptance Criteria

- ✅ All 5 functions implemented with correct type hints and docstrings
- ✅ `generate_embedding()` returns 1536-dim vector for valid text, `None` for empty/null
- ✅ `generate_embedding()` retries on rate limits with exponential backoff
- ✅ `batch_generate_embeddings()` splits into sub-batches of 50
- ✅ `batch_generate_embeddings()` returns results in same order as input
- ✅ `generate_embeddings_for_document()` updates `ProcessingTask` progress correctly
- ✅ `batch_embed_chunks()` returns `{"processed": N, "skipped": M, "failed": K}`
- ✅ `reembed_chunk()` overwrites existing embedding
- ✅ All 14+ tests pass with mocked OpenAI calls
- ✅ Logging follows existing patterns (`logger.info`, `logger.error`, `logger.warning`)
- ✅ No new dependencies required
