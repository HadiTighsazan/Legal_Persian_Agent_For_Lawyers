"""
Views for the documents app.

Provides ``DocumentUploadView`` — an API endpoint that accepts file uploads,
delegates processing to the upload service, and returns document metadata.
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from documents.serializers import (
    DocumentResponseSerializer,
    DocumentUploadSerializer,
)
from documents.services.upload_service import upload_document
from documents.storage.base import StorageError

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
