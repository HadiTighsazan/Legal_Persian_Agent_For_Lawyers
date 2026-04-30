# Epic E05 — Embedding & Vector Storage Refactoring Prompt

## Objective

Refactor the Epic E05 codebase to fix 7 identified issues (2 high, 3 medium, 2 low severity). All existing tests must continue to pass after each change.

## Files to Modify

| # | File | Changes |
|---|------|---------|
| 1 | `src/backend/documents/services/embedding_service.py` | Remove dead code, fix progress calc, fix `reembed_chunk` error shapes |
| 2 | `src/backend/documents/tasks/embedding_tasks.py` | Remove duplicate logic, fix `autoretry_for` dead code |
| 3 | `src/backend/providers/openai_embedding.py` | Fix silent API failure in `embed_batch()` |
| 4 | `src/backend/providers/gemini_embedding.py` | Fix silent API failure in `embed_batch()`, deduplicate `SUB_BATCH_SIZE` |
| 5 | `src/backend/providers/ollama_embedding.py` | Fix silent API failure in `embed_batch()` |
| 6 | `src/backend/providers/base.py` | Add `SUB_BATCH_SIZE` constant or shared location |
| 7 | `src/backend/documents/views.py` | Add ownership check to `ChunkBatchEmbedView` |
| 8 | `src/backend/documents/tests/test_embedding.py` | Update tests for refactored code |

## Step-by-Step Instructions

### Step 1: Fix Silent API Failures in `embed_batch()` Across All Providers

**Problem:** When the API call in `embed_batch()` fails entirely (e.g., network error, auth failure), the exception is caught and logged, but the method returns a list of all `None` values. The caller cannot distinguish "all texts were empty" from "the API call failed entirely."

**Solution:** Add a custom exception `EmbeddingBatchError` to `providers/base.py` that wraps partial results. When the API call fails entirely, raise this exception with the partial results (all `None` values). The caller can catch it and decide how to handle.

**Changes:**

#### `src/backend/providers/base.py`
Add a new exception class:
```python
class EmbeddingBatchError(ProviderError):
    """Raised when a batch embedding API call fails entirely.
    
    The ``partial_results`` attribute contains the results that were
    successfully computed before the failure (typically all ``None``).
    """
    def __init__(
        self,
        message: str,
        partial_results: list[list[float] | None] | None = None,
    ) -> None:
        self.partial_results = partial_results
        super().__init__(message)
```

#### `src/backend/providers/openai_embedding.py`
In `embed_batch()`, change the `except` block (lines 97-101) to raise `EmbeddingBatchError` instead of silently returning:
```python
except Exception as e:
    logger.error("OpenAIEmbeddingProvider.embed_batch: Failed — %s", e)
    raise EmbeddingBatchError(
        f"OpenAI batch embedding failed: {e}",
        partial_results=results,
    ) from e
```

#### `src/backend/providers/ollama_embedding.py`
Same change in `embed_batch()` (lines 114-118):
```python
except Exception as e:
    logger.error("OllamaEmbeddingProvider.embed_batch: Failed — %s", e)
    raise EmbeddingBatchError(
        f"Ollama batch embedding failed: {e}",
        partial_results=results,
    ) from e
```

#### `src/backend/providers/gemini_embedding.py`
In `embed_batch()`, after the retry loop exhausts all attempts (when both Timeout and RequestException retries fail), raise `EmbeddingBatchError` instead of silently continuing. The key locations are:
- After the Timeout retry loop (around line 210): raise `EmbeddingBatchError`
- After the RequestException retry loop (around line 232): raise `EmbeddingBatchError`

```python
# After timeout retries exhausted:
raise EmbeddingBatchError(
    f"Gemini batch embedding timed out after {_MAX_RETRIES} retries for sub-batch {batch_start}–{batch_end}",
    partial_results=results,
)

# After RequestException retries exhausted:
raise EmbeddingBatchError(
    f"Gemini batch embedding failed after {_MAX_RETRIES} retries for sub-batch {batch_start}–{batch_end}: {e}",
    partial_results=results,
) from e
```

**Important:** The `embed_batch()` method should still return `list[list[float] | None]` on success. The exception is only raised when ALL retry attempts fail.

### Step 2: Eliminate Dead Code — Remove `generate_embeddings_for_document()`

**Problem:** [`generate_embeddings_for_document()`](src/backend/documents/services/embedding_service.py:115) has nearly identical logic to the Celery task [`embed_document()`](src/backend/documents/tasks/embedding_tasks.py:38), but is never called by it. The docstring of `embed_document` explicitly says it "manages the ProcessingTask lifecycle directly (no delegation to generate_embeddings_for_document)."

**Solution:** Remove `generate_embeddings_for_document()` from `embedding_service.py` and update the Celery task to use a shared helper function for the core batch-processing logic.

**Changes:**

#### `src/backend/documents/services/embedding_service.py`
1. Remove the `generate_embeddings_for_document()` function entirely (lines 115-228).
2. Remove the import of `ProcessingTask` and `timezone` since they're no longer needed.
3. Remove the import of `Document` since it's no longer needed (only `DocumentChunk` remains).
4. Export a new shared helper function that both the service layer and Celery task can use:

```python
def _process_chunk_batch(
    chunks: list[DocumentChunk],
    progress_callback: Callable[[int], None] | None = None,
) -> int:
    """Shared helper: generate embeddings for a list of chunks and save them.
    
    Args:
        chunks: List of DocumentChunk instances (must have content).
        progress_callback: Optional callback receiving processed_count after each batch.
        
    Returns:
        Number of chunks successfully embedded.
    """
    total = len(chunks)
    processed = 0
    
    for batch_start in range(0, total, SUB_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + SUB_BATCH_SIZE]
        texts = [chunk.content for chunk in batch]
        embeddings = batch_generate_embeddings(texts)
        
        for chunk, embedding in zip(batch, embeddings):
            if embedding is not None:
                chunk.embedding = embedding
                chunk.save(update_fields=["embedding"])
                processed += 1
        
        if progress_callback:
            progress_callback(processed)
    
    return processed
```

5. Update the module docstring to remove references to `generate_embeddings_for_document`.

#### `src/backend/documents/tasks/embedding_tasks.py`
1. Import `_process_chunk_batch` from `embedding_service`.
2. Replace the inline batch-processing loop (lines 108-145) with a call to `_process_chunk_batch()`.
3. Keep the `ProcessingTask` lifecycle management (status updates, error handling) in the task — only delegate the actual embedding loop.

The refactored task body (after Step 2 chunk fetch) would look like:
```python
    try:
        processed_count = _process_chunk_batch(
            chunks,
            progress_callback=lambda p: _update_progress(processing_task, p, total_count),
        )
        
        # Mark as completed
        processing_task.status = "completed"
        processing_task.progress = 100
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "progress", "completed_at"])
        
        log_milestone(...)
        
    except EmbeddingBatchError as e:
        # Partial failure — mark as failed but log partial results
        error_message = f"Embedding failed after partial progress: {e}"
        logger.exception(...)
        processing_task.status = "failed"
        processing_task.error_message = error_message
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "error_message", "completed_at"])
    
    except Exception as e:
        error_message = f"Embedding failed: {e}"
        logger.exception(...)
        processing_task.status = "failed"
        processing_task.error_message = error_message
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "error_message", "completed_at"])
```

Add a helper for progress:
```python
def _update_progress(task: ProcessingTask, processed: int, total: int) -> None:
    """Update the ProcessingTask progress based on processed count."""
    progress = int(processed / total * 100) if total > 0 else 100
    task.progress = progress
    task.save(update_fields=["progress"])
```

### Step 3: Fix `autoretry_for` Dead Code in `embed_document` Task

**Problem:** The `@shared_task` decorator has `autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError)`, but the entire processing loop is wrapped in `try/except Exception` which catches everything before Celery can retry.

**Solution:** Either:
- (A) Remove `autoretry_for` parameters since they're never used, OR
- (B) Restructure so transient DB errors propagate to Celery's retry mechanism.

**Recommendation:** Choose option (A) — remove `autoretry_for`, `max_retries`, `retry_backoff`, `retry_backoff_max`, and `retry_jitter` from the decorator. The task already handles failures gracefully by marking the `ProcessingTask` as "failed". If we want retries, they should be implemented explicitly within the task body (like the Gemini provider does).

### Step 4: Deduplicate `SUB_BATCH_SIZE`

**Problem:** `SUB_BATCH_SIZE = 100` is defined in both [`embedding_service.py:35`](src/backend/documents/services/embedding_service.py:35) and [`gemini_embedding.py:20`](src/backend/providers/gemini_embedding.py:20). The Gemini provider does its own internal sub-batching, which could cause double-batching if the caller also batches.

**Solution:** Move `SUB_BATCH_SIZE` to a single shared location.

**Changes:**

#### `src/backend/providers/base.py`
Add a module-level constant:
```python
EMBEDDING_SUB_BATCH_SIZE: int = 100
"""Maximum number of texts to send in a single provider API call."""
```

#### `src/backend/documents/services/embedding_service.py`
Change the import to use the shared constant:
```python
from providers.base import EMBEDDING_SUB_BATCH_SIZE as SUB_BATCH_SIZE
```
Remove the local definition of `SUB_BATCH_SIZE`.

#### `src/backend/providers/gemini_embedding.py`
Change to use the shared constant:
```python
from providers.base import EMBEDDING_SUB_BATCH_SIZE as SUB_BATCH_SIZE
```
Remove the local definition of `SUB_BATCH_SIZE` (line 20).

### Step 5: Fix `reembed_chunk()` Error Response Consistency

**Problem:** [`reembed_chunk()`](src/backend/documents/services/embedding_service.py:273) returns different error shapes:
- Missing chunk: `{"error": "not_found", "message": "Chunk not found"}`
- API failure: `{"chunk_id": ..., "embedding_updated": False, "error": "Failed to generate embedding"}`

The view [`ChunkReEmbedView`](src/backend/documents/views.py:529) doesn't check for the error case.

**Solution:** Make `reembed_chunk()` raise exceptions for error cases, and let the view handle them consistently.

**Changes:**

#### `src/backend/documents/services/embedding_service.py`
Refactor `reembed_chunk()` to raise exceptions:
```python
def reembed_chunk(chunk_id: str) -> dict[str, Any]:
    try:
        chunk = DocumentChunk.objects.get(id=chunk_id)
    except DocumentChunk.DoesNotExist:
        raise EmbeddingError(f"Chunk {chunk_id} not found")

    embedding = generate_embedding(chunk.content)
    if embedding is None:
        raise EmbeddingError(f"Failed to generate embedding for chunk {chunk_id}")

    chunk.embedding = embedding
    chunk.save(update_fields=["embedding"])
    return {"chunk_id": str(chunk.id), "embedding_updated": True}
```

#### `src/backend/documents/views.py`
Update `ChunkReEmbedView.post()` to catch `EmbeddingError`:
```python
def post(self, request: Request, chunk_id: str) -> Response:
    try:
        chunk = DocumentChunk.objects.get(id=chunk_id)
    except DocumentChunk.DoesNotExist:
        return Response(
            {"error": "not_found", "message": "Chunk not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    if chunk.document.user != request.user:
        return Response(
            {"error": "permission_denied", "message": "..."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        result = reembed_chunk(str(chunk.id))
    except EmbeddingError as e:
        return Response(
            {"error": "embedding_failed", "message": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    response_serializer = ChunkReEmbedResponseSerializer(data=result)
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
```

### Step 6: Add Ownership Check to `ChunkBatchEmbedView`

**Problem:** [`ChunkBatchEmbedView`](src/backend/documents/views.py:499) doesn't verify that the requested chunk IDs belong to the authenticated user.

**Solution:** Filter chunks by user before processing.

**Changes:**

#### `src/backend/documents/views.py`
In `ChunkBatchEmbedView.post()`, add ownership filtering:
```python
def post(self, request: Request) -> Response:
    serializer = ChunkBatchEmbedRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    chunk_ids = [str(cid) for cid in serializer.validated_data["chunk_ids"]]
    
    # Filter chunks belonging to the authenticated user
    user_chunks = DocumentChunk.objects.filter(
        id__in=chunk_ids,
        document__user=request.user,
    ).values_list("id", flat=True)
    
    user_chunk_ids = [str(cid) for cid in user_chunks]
    
    if not user_chunk_ids:
        return Response(
            {"processed": 0, "skipped": 0, "failed": 0},
            status=status.HTTP_200_OK,
        )
    
    result = batch_embed_chunks(user_chunk_ids)
    
    response_serializer = ChunkBatchEmbedResponseSerializer(data=result)
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
```

### Step 7: Update Tests

**Changes to `src/backend/documents/tests/test_embedding.py`:**

1. **Remove tests for `generate_embeddings_for_document`** (the `GenerateEmbeddingsForDocumentTests` class, lines 255-413) since the function is being removed.

2. **Update `ReembedChunkTests`** to expect exceptions instead of error dicts:
   - `test_reembed_chunk_not_found` should expect `EmbeddingError` instead of checking `result["error"]`
   - `test_reembed_chunk_failure` should expect `EmbeddingError` instead of checking `result["embedding_updated"]`

3. **Update `ChunkBatchEmbedViewTests`** to test ownership filtering:
   - Add a test that chunks from another user's document are silently skipped
   - Update `test_successful_batch_embed_returns_200` to create chunks owned by the user

4. **Update `EmbeddingCeleryTaskTests`** to work with the refactored task that uses `_process_chunk_batch`:
   - The mock target may change from `documents.tasks.embedding_tasks.batch_generate_embeddings` to `documents.services.embedding_service.batch_generate_embeddings` depending on import structure
   - Verify the task still correctly handles `EmbeddingBatchError`

## Testing Checklist

After all changes, run:
```bash
docker-compose exec backend pytest src/backend/documents/tests/test_embedding.py -v
docker-compose exec backend pytest src/backend/documents/tests/test_tasks.py -v
docker-compose exec backend pytest src/backend/ -v
```

All tests must pass. No existing test should be removed without replacement.

## Key Principles

1. **TDD Flow**: RED → GREEN → REFACTOR for each step
2. **Don't break existing tests**: If a test needs to change, understand why first
3. **One change at a time**: Commit/verify after each step
4. **Update `docs/active-task/wip-context.md`** after completing each step
5. **Update `docs/references/api-registry.md`** if any API endpoint behavior changes
