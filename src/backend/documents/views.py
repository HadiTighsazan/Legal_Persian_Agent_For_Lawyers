"""
Views for the documents app.

Provides ``DocumentUploadView`` — an API endpoint that accepts file uploads,
delegates processing to the upload service, and returns document metadata.
Also provides ``DocumentProcessView`` and ``DocumentProcessingStatusView``
for the document processing pipeline (Epic E-04, Task 5).
"""

import logging
from django.utils import timezone

from celery import current_app as celery_app
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from documents.models import Document
from documents.serializers import (
    DocumentResponseSerializer,
    DocumentUploadSerializer,
    ProcessingStatusSerializer,
)
from documents.services.upload_service import upload_document
from documents.storage.base import StorageError
from documents.tasks import process_document
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)


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

        # Prevent duplicate processing (both in-progress and already-completed).
        if document.processing_status in ("processing", "completed"):
            return Response(
                {"error": "bad_request", "message": "Document is already being processed or has been processed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Trigger the Celery chain via the process_document helper.
        # process_document is a regular Python function (not a Celery task),
        # so we call it directly. It returns the Celery chain's task ID.
        task_id = process_document(str(document.id))

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

        # Build task list with progress rules and Celery AsyncResult healing.
        task_data = []
        for task in tasks:
            # Check Celery AsyncResult for real-time state if we have a task ID.
            if task.celery_task_id and task.status in ("running", "pending"):
                try:
                    async_result = celery_app.AsyncResult(task.celery_task_id)
                    celery_state = async_result.state
                    # Heal stale DB state based on Celery's actual state.
                    if celery_state == "FAILURE" and task.status != "failed":
                        task.status = "failed"
                        task.error_message = task.error_message or "Task failed (detected via Celery AsyncResult)"
                        task.completed_at = timezone.now()
                        task.save(update_fields=["status", "error_message", "completed_at"])
                    elif celery_state == "REVOKED" and task.status != "cancelled":
                        task.status = "cancelled"
                        task.completed_at = timezone.now()
                        task.save(update_fields=["status", "completed_at"])
                except Exception:
                    logger.warning(
                        "Failed to check AsyncResult for task %s", task.celery_task_id,
                        exc_info=True,
                    )

            if task.status == "completed":
                progress = 100
            elif task.status == "failed":
                progress = 0
            elif task.status == "running":
                progress = task.progress
            else:  # pending or cancelled
                progress = 0

            task_data.append(
                {
                    "task_type": task.task_type,
                    "status": task.status,
                    "progress": progress,
                    "error_message": task.error_message,
                }
            )

        # Calculate overall progress (average of all task progress values).
        if task_data:
            overall_progress = sum(t["progress"] for t in task_data) // len(task_data)
        else:
            overall_progress = 0

        # Determine the top-level status.
        # If no tasks exist, the document hasn't been processed yet.
        if not task_data:
            display_status = "pending"
        else:
            display_status = document.processing_status

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
