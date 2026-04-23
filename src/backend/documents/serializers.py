"""
Serializers for the documents app.

Provides ``DocumentUploadSerializer`` for validating incoming file uploads
and ``DocumentResponseSerializer`` for formatting document metadata into
a consistent JSON response.
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
