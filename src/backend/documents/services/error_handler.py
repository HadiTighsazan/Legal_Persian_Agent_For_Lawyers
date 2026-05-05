"""
Centralized error-handling utilities for the document processing pipeline.

Provides reusable functions for:
- Classifying PDF-related errors (password-protected, corrupted, empty, non-PDF)
- Updating ``ProcessingTask`` and ``Document`` statuses to ``"failed"``
- Logging processing milestones with consistent formatting
"""

from __future__ import annotations

import logging
from typing import Any

import fitz
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone

from documents.models import Document
from tasks.models import ProcessingTask


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_pdf_magic_bytes(file_path: str) -> bool:
    """Check whether *file_path* starts with the PDF magic bytes (``%PDF``).

    Args:
        file_path: Absolute or relative path to the file to check.

    Returns:
        ``True`` if the first 4 bytes are ``b"%PDF"``, ``False`` otherwise.
        Returns ``False`` if the file does not exist or cannot be read.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(4)
        return header == b"%PDF"
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logger.warning(
            "_has_pdf_magic_bytes: Cannot read file '%s' — %s",
            file_path,
            exc,
        )
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_pdf_error(exception: Exception, pdf_path: str) -> str:
    """Return a user-friendly error string based on *exception* and *pdf_path*.

    Classification order:

    1. If the file does **not** start with ``%PDF`` magic bytes →
       ``"File is not a valid PDF"``.
    2. If *exception* is :class:`fitz.FileDataError` or :class:`fitz.EmptyFileError` →
       ``"PDF file is corrupted or unreadable"``.
    3. If the exception message contains ``"password"`` (case-insensitive) →
       ``"PDF is password-protected"``.
    4. Otherwise → ``str(exception)`` (fallback).

    Args:
        exception: The exception raised during PDF processing.
        pdf_path: The path to the PDF file (used for magic-bytes check).

    Returns:
        A human-readable error string.
    """
    # 1. Non-PDF magic bytes check.
    if not _has_pdf_magic_bytes(pdf_path):
        return "File is not a valid PDF"

    # 2. Corrupted / unreadable PDF.
    if isinstance(exception, (fitz.FileDataError, fitz.EmptyFileError)):
        return "PDF file is corrupted or unreadable"

    # 3. Celery task timeout.
    if isinstance(exception, SoftTimeLimitExceeded):
        return "Task timed out"

    # 4. Password-protected PDF.
    error_msg = str(exception)
    if "password" in error_msg.lower():
        return "PDF is password-protected"

    # 5. Fallback.
    return error_msg


def fail_processing_task(
    processing_task: ProcessingTask,
    document: Document,
    error_message: str,
    logger: logging.Logger,
) -> None:
    """Set both *processing_task* and *document* to ``"failed"`` status.

    The *processing_task* gets ``status="failed"``, ``error_message`` set, and
    ``completed_at`` set to the current time.  The *document* gets
    ``processing_status="failed"`` and ``processing_error`` set.

    The error is logged via ``logger.exception()`` with contextual info.

    Args:
        processing_task: The :class:`ProcessingTask` to mark as failed.
        document: The :class:`Document` to mark as failed.
        error_message: The error message to store on both records.
        logger: A :class:`logging.Logger` instance to use for logging.
    """
    processing_task.status = "failed"
    processing_task.error_message = error_message
    processing_task.completed_at = timezone.now()
    processing_task.save(update_fields=["status", "error_message", "completed_at"])

    document.processing_status = "failed"
    document.status = "failed"
    document.processing_error = error_message
    document.save(update_fields=["processing_status", "status", "processing_error"])

    logger.exception(
        "fail_processing_task: Document %s failed — %s",
        document.id,
        error_message,
    )


def log_milestone(
    logger: logging.Logger,
    document_id: str,
    milestone: str,
    **extra: Any,
) -> None:
    """Log a processing milestone at ``INFO`` level with consistent formatting.

    Format::

        [document_id] milestone — extra_key=extra_value ...

    Args:
        logger: A :class:`logging.Logger` instance.
        document_id: The UUID (as a string) of the :class:`Document`.
        milestone: A short description of the milestone
            (e.g. ``"Starting extraction"``, ``"Pipeline complete"``).
        **extra: Additional key-value pairs to append to the log message.
    """
    extra_str = " ".join(f"{k}={v}" for k, v in extra.items())
    if extra_str:
        logger.info("[%s] %s — %s", document_id, milestone, extra_str)
    else:
        logger.info("[%s] %s", document_id, milestone)
