"""
File validation utilities for document uploads.

Provides functions to validate file types and sizes against
configurable settings, raising ``django.core.exceptions.ValidationError``
when constraints are violated.
"""

import os
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError


def validate_file_type(
    filename: str,
    allowed_types: Optional[list[str]] = None,
) -> None:
    """Validate that *filename* has an allowed file extension.

    Parameters
    ----------
    filename : str
        The name (or path) of the uploaded file.
    allowed_types : list[str] | None
        List of permitted extensions (e.g. ``['.pdf', '.docx']``).
        When ``None`` the value is read from ``settings.ALLOWED_EXTENSIONS``
        falling back to ``['.pdf', '.docx', '.txt']``.

    Raises
    ------
    ValidationError
        If the file extension is not in the allowed list.
    """
    if allowed_types is None:
        allowed_types = getattr(
            settings,
            "ALLOWED_EXTENSIONS",
            [".pdf", ".docx", ".txt"],
        )

    # Normalise: ensure every entry starts with a dot and is lower-case.
    allowed_types = [
        ext if ext.startswith(".") else f".{ext}" for ext in allowed_types
    ]
    allowed_types_lower = [ext.lower() for ext in allowed_types]

    _ext = os.path.splitext(filename)[1]
    if not _ext:
        raise ValidationError(
            f"File '{filename}' has no extension. "
            f"Allowed extensions: {', '.join(allowed_types)}."
        )

    if _ext.lower() not in allowed_types_lower:
        raise ValidationError(
            f"File type '{_ext}' is not allowed. "
            f"Allowed extensions: {', '.join(allowed_types)}."
        )


def validate_file_size(
    file,
    max_size_mb: Optional[float] = None,
) -> None:
    """Validate that *file* does not exceed the maximum allowed size.

    Parameters
    ----------
    file : django.core.files.UploadedFile | file-like
        The uploaded file object.  Must have a ``size`` attribute (in bytes).
    max_size_mb : float | None
        Maximum allowed size in megabytes.  When ``None`` the value is read
        from ``settings.MAX_UPLOAD_SIZE`` (in bytes), falling back to
        ``50`` MB.

    Raises
    ------
    ValidationError
        If the file size exceeds the limit.
    """
    if max_size_mb is None:
        max_size_bytes = getattr(settings, "MAX_UPLOAD_SIZE", 50 * 1024 * 1024)
    else:
        max_size_bytes = int(max_size_mb * 1024 * 1024)

    if file.size > max_size_bytes:
        max_size_mb_display = max_size_mb or (max_size_bytes / (1024 * 1024))
        raise ValidationError(
            f"File size ({file.size / (1024 * 1024):.2f} MB) exceeds the "
            f"maximum allowed size of {max_size_mb_display:.0f} MB."
        )
