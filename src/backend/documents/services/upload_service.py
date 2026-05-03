"""
Upload service for document management.

Provides the ``upload_document`` orchestration function that ties together
file validation, storage, and repository layers into a single upload
workflow.
"""

import logging
import mimetypes
import uuid
from typing import Any, Optional

from django.core.exceptions import ValidationError

from documents.repositories.document_repository import create_document
from documents.storage import get_storage_backend
from documents.storage.base import StorageError
from documents.utils.file_validator import validate_file_size, validate_file_type

logger = logging.getLogger(__name__)


def _guess_mime_type(original_filename: str) -> str:
    """Guess the MIME type of a file based on its extension.

    Args:
        original_filename: The original name of the uploaded file.

    Returns:
        A MIME type string (e.g. ``"application/pdf"``). Falls back to
        ``"application/octet-stream"`` when the type cannot be determined.
    """
    mime_type, _ = mimetypes.guess_type(original_filename)
    return mime_type or "application/octet-stream"


def upload_document(
    user: Any,
    file: Any,
    title: str = "",
    allowed_extensions: Optional[list[str]] = None,
    max_size_mb: Optional[float] = None,
) -> dict:
    """Orchestrate the full document upload workflow.

    The function performs the following steps in order:

    1. Validate the file type (extension) using the Phase‑3 validator.
    2. Validate the file size using the Phase‑3 validator.
    3. Generate a unique internal filename (``{uuid}{ext}``).
    4. Save the file through the storage backend factory.
    5. Create a database record via the repository layer.
    6. Return a dictionary of document metadata.

    Args:
        user: The User instance that owns the document.
        file: The uploaded file object (must have ``.name`` and ``.size``
              attributes, and be readable as a binary stream).
        title: A descriptive title for the document (from the upload form).
        allowed_extensions: Optional list of permitted file extensions.
            Passed through to :func:`~documents.utils.file_validator.validate_file_type`.
        max_size_mb: Optional maximum file size in megabytes. Passed through
            to :func:`~documents.utils.file_validator.validate_file_size`.

    Returns:
        A dictionary containing the created document's metadata::

            {
                "id": "uuid-string",
                "title": "user-provided-title",
                "original_filename": "original-name.pdf",
                "file_size": 123456,
                "mime_type": "application/pdf",
                "file_path": "/storage/path/file.pdf",
                "storage_type": "local",
                "status": "uploaded",
                "created_at": "2026-01-01T00:00:00Z",
            }

    Raises:
        ValidationError: If file type or size validation fails.
        StorageError: If the storage backend fails to persist the file.
        RuntimeError: If the database record creation fails unexpectedly.
    """
    # ------------------------------------------------------------------
    # Step 1 – Validate file type
    # ------------------------------------------------------------------
    logger.info("Validating file type for '%s'", getattr(file, "name", "unknown"))
    validate_file_type(file.name, allowed_types=allowed_extensions)

    # ------------------------------------------------------------------
    # Step 2 – Validate file size
    # ------------------------------------------------------------------
    logger.info("Validating file size for '%s'", getattr(file, "name", "unknown"))
    validate_file_size(file, max_size_mb=max_size_mb)

    # ------------------------------------------------------------------
    # Step 3 – Generate a unique internal filename
    # ------------------------------------------------------------------
    original_filename: str = file.name
    _ext: str = ""
    if "." in original_filename:
        _ext = original_filename[original_filename.rindex(".") :]

    unique_filename: str = f"{uuid.uuid4()}{_ext}"
    logger.debug("Generated unique filename: %s", unique_filename)

    # ------------------------------------------------------------------
    # Step 4 – Save the file using the storage backend
    # ------------------------------------------------------------------
    storage = get_storage_backend()
    try:
        file_path: str = storage.save_file(file, unique_filename)
        logger.info("File saved to storage path: %s", file_path)
    except StorageError:
        logger.exception(
            "Storage backend failed to save file '%s'", unique_filename
        )
        raise

    # ------------------------------------------------------------------
    # Step 5 – Create the database record
    # ------------------------------------------------------------------
    mime_type: str = _guess_mime_type(original_filename)
    storage_type: str = getattr(storage, "storage_type", "local")

    try:
        document = create_document(
            user=user,
            title=title or unique_filename,
            filename=unique_filename,
            original_filename=original_filename,
            file_size=file.size,
            mime_type=mime_type,
            file_path=file_path,
            storage_type=storage_type,
        )
        logger.info("Document record created with id=%s", document.id)
    except Exception as exc:
        logger.exception(
            "Failed to create database record for '%s'", unique_filename
        )
        # Clean up the orphaned file from storage
        try:
            storage.delete_file(file_path)
            logger.info("Cleaned up orphaned file: %s", file_path)
        except Exception as cleanup_exc:
            logger.error(
                "Failed to clean up orphaned file '%s': %s",
                file_path, cleanup_exc,
            )
        raise RuntimeError(
            f"Document file was saved but the database record could not be "
            f"created: {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # Step 6 – Return document metadata
    # ------------------------------------------------------------------
    return {
        "id": str(document.id),
        "title": document.title,
        "original_filename": document.original_filename,
        "file_size": document.file_size,
        "mime_type": document.mime_type,
        "file_path": document.file_path,
        "storage_type": document.storage_type,
        "status": document.status,
        "created_at": document.created_at.isoformat(),
    }
