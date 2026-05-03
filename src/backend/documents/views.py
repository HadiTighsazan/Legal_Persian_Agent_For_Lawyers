"""
Views for the documents app.

Provides ``DocumentUploadView`` — an API endpoint that accepts file uploads,
delegates processing to the upload service, and returns document metadata.
Also provides ``DocumentProcessView`` and ``DocumentProcessingStatusView``
for the document processing pipeline (Epic E-04, Task 5), and
``DocumentChunksListView`` for retrieving paginated document chunks
(Epic E-04, Task 6).

Epic E-05 (Task 4) adds four new embedding views:
- ``DocumentEmbedView`` — trigger embedding for a document
- ``ChunkBatchEmbedView`` — batch-embed chunks by ID
- ``ChunkReEmbedView`` — re-embed a single chunk
- ``TaskStatusView`` — retrieve processing task status
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import EmptyPage, Paginator
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from documents.models import Document, DocumentChunk
from documents.serializers import (
    ChunkBatchEmbedRequestSerializer,
    ChunkBatchEmbedResponseSerializer,
    ChunkReEmbedResponseSerializer,
    DocumentChunkSerializer,
    DocumentEmbedResponseSerializer,
    DocumentResponseSerializer,
    DocumentUploadSerializer,
    ProcessingStatusSerializer,
    SearchRequestSerializer,
    SearchResponseSerializer,
)
from documents.services.embedding_service import (
    EmbeddingError,
    batch_embed_chunks,
    embed_query,
    reembed_chunk,
)
from documents.services.search_service import (
    search_chunks,
)
from documents.services.processing_service import (
    build_task_data,
    compute_display_status,
    compute_overall_progress,
)
from documents.services.upload_service import upload_document
from documents.storage.base import StorageError
from documents.tasks import embed_document, process_document
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)


class DocumentListView(APIView):
    """List the authenticated user's documents with pagination, search, and status filtering.

    **Endpoint:** ``GET /documents/``

    **Authentication:** Required.

    **Query Parameters:**
        - ``page`` (int, default=1)
        - ``page_size`` (int, default=20, max=100)
        - ``search`` (str, optional) — filter by title (case-insensitive contains)
        - ``status`` (str, optional) — filter by document status

    **Responses:**
        - ``200 OK`` — Paginated document list returned successfully.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        search = request.query_params.get("search", "")
        status_filter = request.query_params.get("status", "")

        # Clamp values
        page = max(1, page)
        page_size = max(1, min(100, page_size))

        # Build queryset
        queryset = Document.objects.filter(user=request.user)

        if search:
            queryset = queryset.filter(title__icontains=search)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        queryset = queryset.order_by("-created_at")

        # Paginate
        paginator = Paginator(queryset, page_size)
        try:
            page_obj = paginator.page(page)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages) if paginator.num_pages > 0 else []
            page = paginator.num_pages if paginator.num_pages > 0 else 1

        # Serialize
        results = []
        for doc in page_obj.object_list:
            results.append({
                "id": str(doc.id),
                "title": doc.title,
                "original_filename": doc.original_filename,
                "file_size": doc.file_size,
                "total_pages": doc.total_pages,
                "status": doc.status,
                "created_at": doc.created_at.isoformat(),
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            })

        # Build next/previous URLs
        base_url = request.build_absolute_uri(request.path)
        next_url = f"{base_url}?page={page + 1}&page_size={page_size}" if page_obj.has_next() else None
        prev_url = f"{base_url}?page={page - 1}&page_size={page_size}" if page_obj.has_previous() else None

        return Response({
            "count": paginator.count,
            "next": next_url,
            "previous": prev_url,
            "results": results,
        })


class DocumentUploadView(APIView):
    """Accept a file upload and return the created document's metadata.

    **Endpoint:** ``POST /documents/upload/``

    **Request:** ``multipart/form-data`` with a ``file`` field.

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    **Responses:**
        - ``201 Created`` — Document uploaded successfully.
        - ``400 Bad Request`` — Validation error (invalid file type/size).
        - ``500 Internal Server Error`` — Storage or runtime failure.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """Handle the file upload POST request."""
        # ------------------------------------------------------------------
        # Step 1 — Validate the incoming request data
        # ------------------------------------------------------------------
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        logger.info(
            "Upload request received for file '%s' (size=%s) by user=%s",
            uploaded_file.name,
            uploaded_file.size,
            request.user,
        )

        # ------------------------------------------------------------------
        # Step 2 — Delegate to the upload service
        # ------------------------------------------------------------------
        try:
            metadata = upload_document(user=request.user, file=uploaded_file)
        except DjangoValidationError as exc:
            logger.warning(
                "Validation failed for file '%s': %s",
                uploaded_file.name,
                exc,
            )
            return Response(
                {"detail": exc.message if hasattr(exc, "message") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except StorageError as exc:
            logger.exception(
                "Storage error while saving file '%s'", uploaded_file.name
            )
            return Response(
                {"detail": f"Storage error: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except RuntimeError as exc:
            logger.exception(
                "Runtime error during upload of '%s'", uploaded_file.name
            )
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ------------------------------------------------------------------
        # Step 3 — Serialize and return the response
        # ------------------------------------------------------------------
        response_serializer = DocumentResponseSerializer(data=metadata)
        response_serializer.is_valid(raise_exception=True)

        return Response(
            response_serializer.validated_data,
            status=status.HTTP_201_CREATED,
        )


class DocumentProcessView(APIView):
    """Trigger document processing for a given document.

    **Endpoint:** ``POST /documents/<uuid:document_id>/process/``

    **Authentication:** Required.

    **Responses:**
        - ``202 Accepted`` — Processing started successfully.
        - ``400 Bad Request`` — Document is already being processed or completed.
        - ``403 Forbidden`` — Document belongs to another user.
        - ``404 Not Found`` — Document does not exist.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, document_id: str) -> Response:
        """Handle the process trigger POST request."""
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verify ownership.
        if document.user != request.user:
            return Response(
                {"error": "permission_denied", "message": "You do not have permission to process this document."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Trigger the Celery chain via the process_document helper.
        # process_document is a regular Python function (not a Celery task),
        # so we call it directly. It returns the Celery chain's task ID,
        # or None if the document is already being processed or completed.
        task_id = process_document(str(document.id))

        if task_id is None:
            # process_document returned None — the document is already being
            # processed or has already been completed. This check is delegated
            # to process_document() to avoid a race window between the view's
            # check and the actual task creation.
            return Response(
                {"error": "bad_request", "message": "Document is already being processed or has been processed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(
            "Processing triggered for document %s (celery_task_id=%s)",
            document.id,
            task_id,
        )

        return Response(
            {
                "task_id": task_id,
                "status": "pending",
                "document_id": str(document.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class DocumentProcessingStatusView(APIView):
    """Retrieve the processing status for a given document.

    **Endpoint:** ``GET /documents/<uuid:document_id>/processing-status/``

    **Authentication:** Required.

    **Responses:**
        - ``200 OK`` — Processing status returned successfully.
        - ``403 Forbidden`` — Document belongs to another user.
        - ``404 Not Found`` — Document does not exist.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, document_id: str) -> Response:
        """Handle the processing status GET request."""
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verify ownership.
        if document.user != request.user:
            return Response(
                {"error": "permission_denied", "message": "You do not have permission to view this document."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Fetch related ProcessingTasks ordered by creation time.
        tasks = ProcessingTask.objects.filter(
            document=document,
        ).order_by("created_at")

        # Build task data with AsyncResult healing applied.
        task_data = build_task_data(list(tasks))

        # Compute derived values from task states.
        display_status = compute_display_status(task_data)
        overall_progress = compute_overall_progress(task_data)

        # Build and validate the response via serializer.
        response_data = {
            "document_id": str(document.id),
            "status": display_status,
            "progress": overall_progress,
            "tasks": task_data,
        }

        serializer = ProcessingStatusSerializer(data=response_data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class ProcessingTaskRetryView(APIView):
    """Retry a failed processing task.

    **Endpoint:** ``POST /documents/processing-tasks/<uuid:task_id>/retry/``

    **Authentication:** Required.

    **Responses:**
        - ``200 OK`` — Task retry initiated successfully.
        - ``400 Bad Request`` — Task is not in a failed state, or max retries exceeded.
        - ``403 Forbidden`` — Task belongs to another user.
        - ``404 Not Found`` — Processing task does not exist.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, task_id: str) -> Response:
        """Handle the retry POST request."""
        try:
            task = ProcessingTask.objects.get(id=task_id)
        except ProcessingTask.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Processing task not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verify ownership via the task's document.
        if task.document.user != request.user:
            return Response(
                {"error": "permission_denied", "message": "You do not have permission to retry this task."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check task is in a failed state.
        if task.status != "failed":
            return Response(
                {"error": "bad_request", "message": "Task is not in a failed state"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check retry limit.
        if task.retry_count >= 3:
            return Response(
                {"error": "max_retries_exceeded", "message": "Maximum retry limit (3) exceeded"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Increment retry count.
        task.retry_count += 1

        # Reset task state.
        task.status = "pending"
        task.error_message = None
        task.completed_at = None

        # Re-trigger the Celery processing pipeline.
        new_task_id = process_document(str(task.document.id))

        if new_task_id is None:
            # process_document returned None — document is already processing/completed.
            return Response(
                {"error": "bad_request", "message": "Document is already being processed or has been processed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update the celery_task_id with the new task ID.
        task.celery_task_id = new_task_id
        task.save()

        logger.info(
            "Task %s retried (retry_count=%d, new_celery_task_id=%s)",
            task.id,
            task.retry_count,
            new_task_id,
        )

        return Response(
            {
                "task_id": new_task_id,
                "status": "pending",
                "retry_count": task.retry_count,
                "document_id": str(task.document.id),
            },
            status=status.HTTP_200_OK,
        )


class DocumentChunksListView(APIView):
    """Retrieve paginated chunks for a given document.

    **Endpoint:** ``GET /documents/<uuid:document_id>/chunks/``

    **Authentication:** Required.

    **Query Parameters:**
        - ``page`` (int, default=1)
        - ``page_size`` (int, default=20)

    **Responses:**
        - ``200 OK`` — Chunks returned successfully (may be empty list).
        - ``403 Forbidden`` — Document belongs to another user.
        - ``404 Not Found`` — Document does not exist.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, document_id: str) -> Response:
        """Handle the chunks list GET request."""
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verify ownership.
        if document.user != request.user:
            return Response(
                {"error": "permission_denied", "message": "You do not have permission to view this document."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Parse pagination params.
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (ValueError, TypeError):
            page, page_size = 1, 20

        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20

        # Query chunks ordered by chunk_index.
        chunks = DocumentChunk.objects.filter(
            document=document,
        ).order_by("chunk_index")

        # Apply pagination.
        total = chunks.count()
        start = (page - 1) * page_size
        end = start + page_size
        page_chunks = chunks[start:end]

        # Serialize.
        serializer = DocumentChunkSerializer(page_chunks, many=True)

        # Build paginated response.
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        return Response(
            {
                "count": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "next": page + 1 if page < total_pages else None,
                "previous": page - 1 if page > 1 else None,
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Embedding Views (Epic E-05, Task 4)
# ---------------------------------------------------------------------------


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


class DocumentSearchView(APIView):
    """Semantic search within a document's chunks.

    **Endpoint:** ``POST /documents/<uuid:document_id>/search/``

    **Authentication:** Required.

    **Request body:**
        ``{"query": "...", "top_k": 10, "min_score": 0.0}``

    **Responses:**
        - ``200 OK`` — Search results returned successfully.
        - ``400 Bad Request`` — Invalid request body (DRF validation).
        - ``403 Forbidden`` — Document belongs to another user.
        - ``404 Not Found`` — Document does not exist.
        - ``422 Unprocessable Entity`` — Document processing is not complete.
        - ``500 Internal Server Error`` — Embedding generation failed.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, document_id: str) -> Response:
        """Handle the search POST request."""
        # 1. Fetch document (404 if not found)
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Ownership check (403 if mismatch)
        if document.user != request.user:
            return Response(
                {
                    "error": "permission_denied",
                    "message": "You do not have permission to search this document.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 3. Processing status check (422 if not 'completed')
        if document.processing_status != "completed":
            return Response(
                {
                    "error": "document_not_ready",
                    "message": "Document processing is not complete yet.",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # 4. Validate request body with SearchRequestSerializer (400 on failure)
        serializer = SearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query: str = serializer.validated_data["query"]
        top_k: int = serializer.validated_data["top_k"]
        min_score: float = serializer.validated_data["min_score"]

        # 5. Call embed_query() to get query vector
        try:
            query_vector = embed_query(query)
        except EmbeddingError:
            logger.exception("Embedding failed for query on document %s", document_id)
            return Response(
                {"error": "embedding_failed", "message": "Failed to generate query embedding."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 6. Call search_chunks() to get results
        results = search_chunks(
            document_id=str(document.id),
            query_vector=query_vector,
            top_k=top_k,
            min_score=min_score,
        )

        # 7. Serialize response with SearchResponseSerializer
        response_data = {
            "results": results,
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "total_results": len(results),
        }
        response_serializer = SearchResponseSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        # 8. Return 200 OK
        return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
