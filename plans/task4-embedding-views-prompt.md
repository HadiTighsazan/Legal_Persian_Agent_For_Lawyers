# Task 4: Embedding Views — Implementation Prompt

## Overview

Implement 4 new API views for the embedding pipeline in [`src/backend/documents/views.py`](src/backend/documents/views.py), register their URLs in [`src/backend/documents/urls.py`](src/backend/documents/urls.py), and write comprehensive tests in [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py).

The serializers already exist in [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) (completed in Task 3). The embedding service functions already exist in [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py).

---

## Files to Modify

| File | Action |
|------|--------|
| [`src/backend/documents/views.py`](src/backend/documents/views.py) | Add 4 new view classes |
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | Register 4 new URL routes |
| [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) | Add test classes for all 4 views |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | Document the new endpoints |

---

## View 1: `DocumentEmbedView` — `POST /documents/{document_id}/embed/`

### Behavior

1. **Auth:** `IsAuthenticated` (same as all existing views)
2. **Lookup:** Fetch `Document` by `document_id` (UUID from URL kwarg)
3. **Ownership check:** If `document.user != request.user` → `403 Forbidden` (`{"error": "permission_denied", "message": "..."}`)
4. **Not found:** If document doesn't exist → `404 Not Found` (`{"error": "not_found", "message": "Document not found"}`)
5. **Count un-embedded chunks:** `DocumentChunk.objects.filter(document=document, embedding__isnull=True).count()`
6. **Create ProcessingTask:** `ProcessingTask.objects.create(document=document, task_type='embed', status='pending')`
7. **Dispatch Celery task:** Call `embed_document.delay(str(document.id), str(task.id))`
   - **Note:** The `embed_document` Celery task does NOT exist yet. You must create it in [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py) and export it from [`src/backend/documents/tasks/__init__.py`](src/backend/documents/tasks/__init__.py).
   - The task should call `embedding_service.generate_embeddings_for_document(document_id)`.
   - See the "New Celery Task" section below for details.
8. **Response:** `202 Accepted` with `DocumentEmbedResponseSerializer` data:
   ```json
   {
     "task_id": "<processing_task.uuid>",
     "task_type": "embed",
     "status": "pending",
     "document_id": "<document.uuid>",
     "total_chunks": <count_of_unembedded_chunks>
   }
   ```

### Error Responses

- `401 Unauthorized` — No auth token (handled by DRF)
- `403 Forbidden` — `{"error": "permission_denied", "message": "You do not have permission to embed this document."}`
- `404 Not Found` — `{"error": "not_found", "message": "Document not found"}`

### Code Pattern (follow existing `DocumentProcessView`)

```python
class DocumentEmbedView(APIView):
    """Trigger embedding for all un-embedded chunks of a document.

    **Endpoint:** ``POST /documents/<uuid:document_id>/embed/``

    **Authentication:** Required.

    **Responses:**
        - ``202 Accepted`` — Embedding task created successfully.
        - ``403 Forbidden`` — Document belongs to another user.
        - ``404 Not Found`` — Document does not exist.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, document_id: str) -> Response:
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if document.user != request.user:
            return Response(
                {"error": "permission_denied", "message": "You do not have permission to embed this document."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Count un-embedded chunks.
        total_chunks = DocumentChunk.objects.filter(
            document=document,
            embedding__isnull=True,
        ).count()

        # Create a ProcessingTask record.
        processing_task = ProcessingTask.objects.create(
            document=document,
            task_type="embed",
            status="pending",
        )

        # Dispatch the Celery task.
        embed_document.delay(str(document.id), str(processing_task.id))

        logger.info(
            "Embedding triggered for document %s (task_id=%s, chunks=%d)",
            document.id,
            processing_task.id,
            total_chunks,
        )

        # Build response using the existing serializer.
        serializer = DocumentEmbedResponseSerializer(data={
            "task_id": processing_task.id,
            "task_type": "embed",
            "status": "pending",
            "document_id": document.id,
            "total_chunks": total_chunks,
        })
        serializer.is_valid(raise_exception=True)

        return Response(serializer.validated_data, status=status.HTTP_202_ACCEPTED)
```

---

## View 2: `ChunkBatchEmbedView` — `POST /chunks/batch-embed/`

### Behavior

1. **Auth:** `IsAuthenticated`
2. **Validate request body** with `ChunkBatchEmbedRequestSerializer` (validates `chunk_ids: list[UUID]`)
3. **Call service:** `embedding_service.batch_embed_chunks(chunk_ids)` — returns `{"processed": N, "skipped": N, "failed": N}`
4. **Response:** `200 OK` with `ChunkBatchEmbedResponseSerializer` data

### Error Responses

- `400 Bad Request` — Invalid `chunk_ids` (DRF serializer validation errors)
- `401 Unauthorized` — No auth token

### Code Pattern

```python
class ChunkBatchEmbedView(APIView):
    """Embed a batch of chunks by their IDs.

    **Endpoint:** ``POST /chunks/batch-embed/``

    **Authentication:** Required.

    **Request body:**
        ``{"chunk_ids": ["<uuid>", "<uuid>", ...]}``

    **Responses:**
        - ``200 OK`` — Batch embedding completed.
        - ``400 Bad Request`` — Invalid chunk_ids.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ChunkBatchEmbedRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        chunk_ids = [str(cid) for cid in serializer.validated_data["chunk_ids"]]
        result = batch_embed_chunks(chunk_ids)

        response_serializer = ChunkBatchEmbedResponseSerializer(data=result)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
```

---

## View 3: `ChunkReEmbedView` — `POST /chunks/{chunk_id}/re-embed/`

### Behavior

1. **Auth:** `IsAuthenticated`
2. **Lookup:** Fetch `DocumentChunk` by `chunk_id` (UUID from URL kwarg)
3. **Ownership check:** If `chunk.document.user != request.user` → `403 Forbidden`
4. **Not found:** If chunk doesn't exist → `404 Not Found`
5. **Call service:** `embedding_service.reembed_chunk(str(chunk.id))` — returns `{"chunk_id": "...", "embedding_updated": True/False}`
6. **Response:** `200 OK` with `ChunkReEmbedResponseSerializer` data

### Error Responses

- `401 Unauthorized` — No auth token
- `403 Forbidden` — `{"error": "permission_denied", "message": "You do not have permission to re-embed this chunk."}`
- `404 Not Found` — `{"error": "not_found", "message": "Chunk not found"}`

### Code Pattern

```python
class ChunkReEmbedView(APIView):
    """Re-embed a single chunk by regenerating its embedding.

    **Endpoint:** ``POST /chunks/<uuid:chunk_id>/re-embed/``

    **Authentication:** Required.

    **Responses:**
        - ``200 OK`` — Re-embedding completed.
        - ``403 Forbidden`` — Chunk belongs to another user's document.
        - ``404 Not Found`` — Chunk does not exist.
    """

    permission_classes = [IsAuthenticated]

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
                {"error": "permission_denied", "message": "You do not have permission to re-embed this chunk."},
                status=status.HTTP_403_FORBIDDEN,
            )

        result = reembed_chunk(str(chunk.id))

        response_serializer = ChunkReEmbedResponseSerializer(data=result)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
```

---

## View 4: `TaskStatusView` — `GET /tasks/{task_id}/`

### Behavior

1. **Auth:** `IsAuthenticated`
2. **Lookup:** Fetch `ProcessingTask` by `task_id` (UUID from URL kwarg)
3. **Ownership check:** If `task.document.user != request.user` → `403 Forbidden`
4. **Not found:** If task doesn't exist → `404 Not Found`
5. **Response:** `200 OK` with task details:
   ```json
   {
     "id": "<task.uuid>",
     "document_id": "<document.uuid>",
     "task_type": "embed",
     "status": "running",
     "progress": 75,
     "result": null,
     "error_message": null,
     "started_at": "2026-04-18T10:00:00Z",
     "completed_at": null
   }
   ```

### Error Responses

- `401 Unauthorized` — No auth token
- `403 Forbidden` — `{"error": "permission_denied", "message": "You do not have permission to view this task."}`
- `404 Not Found` — `{"error": "not_found", "message": "Task not found"}`

### Code Pattern

```python
class TaskStatusView(APIView):
    """Retrieve the status of a processing task.

    **Endpoint:** ``GET /tasks/<uuid:task_id>/``

    **Authentication:** Required.

    **Responses:**
        - ``200 OK`` — Task status returned successfully.
        - ``403 Forbidden`` — Task belongs to another user.
        - ``404 Not Found`` — Task does not exist.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, task_id: str) -> Response:
        try:
            task = ProcessingTask.objects.get(id=task_id)
        except ProcessingTask.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Task not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if task.document.user != request.user:
            return Response(
                {"error": "permission_denied", "message": "You do not have permission to view this task."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {
                "id": str(task.id),
                "document_id": str(task.document.id),
                "task_type": task.task_type,
                "status": task.status,
                "progress": task.progress,
                "result": task.result,
                "error_message": task.error_message,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            },
            status=status.HTTP_200_OK,
        )
```

---

## New Celery Task: `embed_document`

Create a new Celery task in [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py):

```python
@shared_task(
    bind=True,
    autoretry_for=(IntegrityError, OperationalError, ConnectionError, TimeoutError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def embed_document(self, document_id: str, processing_task_id: str) -> None:
    """Generate embeddings for all un-embedded chunks of a document.

    This task is dispatched by :class:`~documents.views.DocumentEmbedView`
    and delegates to :func:`~documents.services.embedding_service.generate_embeddings_for_document`.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to process.
        processing_task_id: The UUID (as a string) of the :class:`~tasks.models.ProcessingTask`
            tracking this embed operation.
    """
    log_milestone(logger, document_id, "Starting embedding")

    try:
        processing_task = ProcessingTask.objects.get(id=processing_task_id)
    except ProcessingTask.DoesNotExist:
        logger.error(
            "embed_document: ProcessingTask %s not found for document %s",
            processing_task_id,
            document_id,
        )
        return

    # Update the ProcessingTask with the Celery task ID and mark as running.
    processing_task.celery_task_id = self.request.id
    processing_task.status = "running"
    processing_task.started_at = timezone.now()
    processing_task.save(update_fields=["celery_task_id", "status", "started_at"])

    # Delegate to the embedding service.
    # generate_embeddings_for_document handles its own ProcessingTask management
    # internally (it creates/finds a ProcessingTask with task_type='embed').
    # To avoid conflicts, we pass the existing processing_task_id context.
    # The service function will use get_or_create which will find our existing task.
    generate_embeddings_for_document(document_id)
```

**Important:** The existing [`generate_embeddings_for_document`](src/backend/documents/services/embedding_service.py:218) function already creates/finds a `ProcessingTask` with `task_type='embed'` via `get_or_create`. Since we're creating the `ProcessingTask` in the view first, the service function will find it. However, there's a potential conflict: the service function's `get_or_create` will find the task we already created, but it will also try to set `status='pending'` as a default. Since we already set `status='pending'` in the view, this should be fine — `get_or_create` only uses defaults when creating a new record.

**Alternative approach (simpler):** Instead of creating the `ProcessingTask` in the view and passing it to the task, we could have the view just dispatch the Celery task, and let `generate_embeddings_for_document` handle the `ProcessingTask` creation entirely. This is simpler and avoids the dual-creation concern. **Recommend this approach:**

```python
# In DocumentEmbedView.post():
embed_document.delay(str(document.id))

# In the Celery task:
@shared_task(...)
def embed_document(self, document_id: str) -> None:
    """Generate embeddings for all un-embedded chunks of a document."""
    generate_embeddings_for_document(document_id)
```

But then the view can't return the `ProcessingTask` ID in the response. Let's check what the task spec says...

**Decision:** Use the two-argument approach (pass `processing_task_id`) since the view needs to return the task ID in the response. The `generate_embeddings_for_document` function's `get_or_create` will find the existing task and work correctly.

---

## URL Registration

Add to [`src/backend/documents/urls.py`](src/backend/documents/urls.py):

```python
from documents.views import (
    DocumentChunksListView,
    DocumentEmbedView,
    DocumentProcessView,
    DocumentProcessingStatusView,
    DocumentUploadView,
    ProcessingTaskRetryView,
    ChunkBatchEmbedView,
    ChunkReEmbedView,
    TaskStatusView,
)

urlpatterns = [
    # ... existing paths ...
    path(
        "<uuid:document_id>/embed/",
        DocumentEmbedView.as_view(),
        name="document-embed",
    ),
    path(
        "chunks/batch-embed/",
        ChunkBatchEmbedView.as_view(),
        name="chunk-batch-embed",
    ),
    path(
        "chunks/<uuid:chunk_id>/re-embed/",
        ChunkReEmbedView.as_view(),
        name="chunk-re-embed",
    ),
    path(
        "tasks/<uuid:task_id>/",
        TaskStatusView.as_view(),
        name="task-status",
    ),
]
```

**IMPORTANT URL ORDER:** The `chunks/batch-embed/` path must be registered **before** any `chunks/<uuid:...>/` pattern to avoid Django matching `batch-embed` as a UUID. Since there's no existing `chunks/<uuid:...>/` pattern, this is fine as-is.

---

## Imports to Add in views.py

```python
from documents.serializers import (
    ChunkBatchEmbedRequestSerializer,
    ChunkBatchEmbedResponseSerializer,
    ChunkReEmbedResponseSerializer,
    DocumentChunkSerializer,
    DocumentEmbedResponseSerializer,
    DocumentResponseSerializer,
    DocumentUploadSerializer,
    ProcessingStatusSerializer,
)
from documents.services.embedding_service import (
    batch_embed_chunks,
    reembed_chunk,
)
from documents.tasks import embed_document  # New import
```

---

## New Celery Task Export

Add to [`src/backend/documents/tasks/__init__.py`](src/backend/documents/tasks/__init__.py):

```python
from .document_processing import chunk_document, embed_document, extract_text_from_pdf

from documents.services.processing_service import process_document

__all__ = ["extract_text_from_pdf", "chunk_document", "embed_document", "process_document"]
```

---

## Tests

Add the following test classes to [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py). Follow the existing patterns from `DocumentProcessViewTests` and `ProcessingTaskRetryViewTests`.

### Test Class 1: `DocumentEmbedViewTests`

| Test Method | Description |
|-------------|-------------|
| `test_nonexistent_document_returns_404` | POST to non-existent document ID → 404 |
| `test_other_users_document_returns_403` | POST to another user's document → 403 |
| `test_unauthenticated_request_returns_401` | POST without auth → 401 |
| `test_successful_embed_returns_202` | Happy path → 202 with task info |
| `test_embed_creates_processing_task` | Verify ProcessingTask is created with task_type='embed' |
| `test_embed_counts_unembedded_chunks` | Verify total_chunks in response matches un-embedded chunks count |
| `test_embed_skips_already_embedded_chunks` | Chunks with existing embeddings are not counted |

### Test Class 2: `ChunkBatchEmbedViewTests`

| Test Method | Description |
|-------------|-------------|
| `test_unauthenticated_request_returns_401` | POST without auth → 401 |
| `test_invalid_chunk_ids_returns_400` | POST with invalid chunk_ids → 400 |
| `test_successful_batch_embed_returns_200` | Happy path → 200 with processed/skipped/failed counts |

### Test Class 3: `ChunkReEmbedViewTests`

| Test Method | Description |
|-------------|-------------|
| `test_nonexistent_chunk_returns_404` | POST to non-existent chunk ID → 404 |
| `test_other_users_chunk_returns_403` | POST to another user's chunk → 403 |
| `test_unauthenticated_request_returns_401` | POST without auth → 401 |
| `test_successful_reembed_returns_200` | Happy path → 200 with chunk_id and embedding_updated |

### Test Class 4: `TaskStatusViewTests`

| Test Method | Description |
|-------------|-------------|
| `test_nonexistent_task_returns_404` | GET for non-existent task ID → 404 |
| `test_other_users_task_returns_403` | GET for another user's task → 403 |
| `test_unauthenticated_request_returns_401` | GET without auth → 401 |
| `test_returns_task_status` | Happy path → 200 with task details |
| `test_returns_all_expected_fields` | Verify response contains id, document_id, task_type, status, progress, result, error_message, started_at, completed_at |

### Mocking Strategy

- Use `@patch("documents.views.embed_document")` for `DocumentEmbedViewTests` (mock the Celery task)
- Use `@patch("documents.views.batch_embed_chunks")` for `ChunkBatchEmbedViewTests` (mock the service function)
- Use `@patch("documents.views.reembed_chunk")` for `ChunkReEmbedViewTests` (mock the service function)
- No mocking needed for `TaskStatusViewTests` (pure DB read)

---

## Implementation Order

1. **Add `embed_document` Celery task** to [`src/backend/documents/tasks/document_processing.py`](src/backend/documents/tasks/document_processing.py)
2. **Export `embed_document`** from [`src/backend/documents/tasks/__init__.py`](src/backend/documents/tasks/__init__.py)
3. **Add 4 new views** to [`src/backend/documents/views.py`](src/backend/documents/views.py)
4. **Register 4 new URL routes** in [`src/backend/documents/urls.py`](src/backend/documents/urls.py)
5. **Add tests** to [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py)
6. **Update** [`docs/references/api-registry.md`](docs/references/api-registry.md) with the new endpoints
7. **Run tests** to verify everything passes

---

## Mermaid Diagram: Request Flow

```mermaid
flowchart LR
    Client[Client] -->|POST /documents/{id}/embed| EmbedView[DocumentEmbedView]
    EmbedView -->|1. Fetch Document| DB[(Database)]
    EmbedView -->|2. Check ownership| Auth{IsAuthenticated}
    EmbedView -->|3. Count un-embedded chunks| DB
    EmbedView -->|4. Create ProcessingTask| DB
    EmbedView -->|5. Dispatch Celery task| Celery[Celery Worker]
    Celery -->|embed_document| Service[generate_embeddings_for_document]
    Service -->|Batch embed chunks| OpenAI[OpenAI API]
    EmbedView -->|6. Return 202| Client

    Client2[Client] -->|POST /chunks/batch-embed| BatchView[ChunkBatchEmbedView]
    BatchView -->|Validate chunk_ids| Serializer[ChunkBatchEmbedRequestSerializer]
    BatchView -->|Call service| BatchService[batch_embed_chunks]
    BatchService -->|Generate embeddings| OpenAI
    BatchView -->|Return 200 with counts| Client2

    Client3[Client] -->|POST /chunks/{id}/re-embed| ReEmbedView[ChunkReEmbedView]
    ReEmbedView -->|Check chunk ownership| DB
    ReEmbedView -->|Call service| ReEmbedService[reembed_chunk]
    ReEmbedService -->|Generate single embedding| OpenAI
    ReEmbedView -->|Return 200| Client3

    Client4[Client] -->|GET /tasks/{id}| TaskView[TaskStatusView]
    TaskView -->|Fetch ProcessingTask| DB
    TaskView -->|Check task ownership| DB
    TaskView -->|Return 200 with task details| Client4
```

---

## API Registry Update

Add these entries to [`docs/references/api-registry.md`](docs/references/api-registry.md) under a new section "### ✅ Implemented Endpoints — Embedding Views (Epic E-05, Task 4)":

1. **POST /documents/{document_id}/embed/** — `DocumentEmbedView`
2. **POST /chunks/batch-embed/** — `ChunkBatchEmbedView`
3. **POST /chunks/{chunk_id}/re-embed/** — `ChunkReEmbedView`
4. **GET /tasks/{task_id}/** — `TaskStatusView`
