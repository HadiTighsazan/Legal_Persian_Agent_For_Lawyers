"""
Serializers for the documents app.

Provides ``DocumentUploadSerializer`` for validating incoming file uploads,
``DocumentResponseSerializer`` for formatting document metadata into
a consistent JSON response, and processing-status serializers for
:class:`~documents.views.DocumentProcessingStatusView`.
"""

from rest_framework import serializers


class DocumentUploadSerializer(serializers.Serializer):
    """Validate the incoming file field from a multipart/form-data request.

    The serializer only performs basic DRF-level validation (ensuring a file
    is present).  Deeper type/size validation is delegated to the
    :mod:`documents.utils.file_validator` module called by the upload service.
    """

    file = serializers.FileField(
        help_text="The document file to upload (PDF, DOCX, or TXT).",
    )


class DocumentResponseSerializer(serializers.Serializer):
    """Format the document metadata dictionary into a consistent response.

    This serializer mirrors the dictionary returned by
    :func:`documents.services.upload_service.upload_document`.
    """

    id = serializers.UUIDField(
        help_text="Unique identifier of the document.",
    )
    title = serializers.CharField(
        help_text="Internal storage filename of the document.",
    )
    original_filename = serializers.CharField(
        help_text="Original name of the uploaded file.",
    )
    file_size = serializers.IntegerField(
        help_text="Size of the file in bytes.",
    )
    mime_type = serializers.CharField(
        help_text="MIME type of the file (e.g. application/pdf).",
    )
    file_path = serializers.CharField(
        help_text="Storage path where the file is persisted.",
    )
    storage_type = serializers.CharField(
        help_text="Storage backend used (e.g. local or s3).",
    )
    status = serializers.CharField(
        help_text="Current processing status of the document.",
    )
    created_at = serializers.DateTimeField(
        help_text="Timestamp when the document record was created.",
    )


class ProcessingTaskSerializer(serializers.Serializer):
    """Serialize a single :class:`~tasks.models.ProcessingTask` for the
    processing-status response."""

    task_type = serializers.CharField(
        help_text="Type of processing task (extract, chunk, embed).",
    )
    status = serializers.CharField(
        help_text="Current status of the task (pending, running, completed, failed).",
    )
    progress = serializers.IntegerField(
        help_text="Progress percentage (0–100).",
    )
    error_message = serializers.CharField(
        allow_null=True,
        help_text="Error message if the task failed, or null.",
    )


class ProcessingStatusSerializer(serializers.Serializer):
    """Serialize the full processing status response for a document."""

    document_id = serializers.UUIDField(
        help_text="Unique identifier of the document.",
    )
    status = serializers.CharField(
        help_text="Overall processing status of the document.",
    )
    progress = serializers.IntegerField(
        help_text="Aggregated progress percentage (average of all task progress values).",
    )
    tasks = ProcessingTaskSerializer(
        many=True,
        help_text="List of processing tasks for this document.",
    )
