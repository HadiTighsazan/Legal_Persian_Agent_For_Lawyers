"""
Service layer for the document processing pipeline.

Provides reusable functions that encapsulate business logic extracted from
views and tasks, including:

- :func:`process_document` — Orchestrate the full document processing pipeline
  as a Celery chain (previously in ``tasks/document_processing.py``).
- :func:`heal_task_from_celery` — Check a ``ProcessingTask`` against Celery's
  ``AsyncResult`` and update stale DB state.
- :func:`build_task_data` — Build the list of task dicts for the status
  response, applying ``AsyncResult`` healing.
- :func:`compute_display_status` — Derive the top-level processing status
  from individual task states.
- :func:`compute_overall_progress` — Average progress across all tasks.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import chain, current_app as celery_app
from django.utils import timezone

from documents.models import Document
from tasks.models import ProcessingTask

logger = logging.getLogger(__name__)


def heal_task_from_celery(task: ProcessingTask) -> None:
    """Check a single ``ProcessingTask`` against Celery's ``AsyncResult``.

    If the task's DB status is ``"running"`` or ``"pending"`` but Celery
    reports ``FAILURE`` or ``REVOKED``, the DB record is updated (healed)
    to reflect the real state.

    This is a **read** operation that performs a write only when healing
    is necessary. It is safe to call on every status-check GET request.

    Args:
        task: The ``ProcessingTask`` instance to check (modified in-place
            and saved if healing occurs).
    """
    if not task.celery_task_id or task.status not in ("running", "pending"):
        return

    try:
        async_result = celery_app.AsyncResult(task.celery_task_id)
        celery_state = async_result.state

        if celery_state == "FAILURE" and task.status != "failed":
            task.status = "failed"
            task.error_message = (
                task.error_message
                or "Task failed (detected via Celery AsyncResult)"
            )
            task.completed_at = timezone.now()
            task.save(update_fields=["status", "error_message", "completed_at"])

        elif celery_state == "REVOKED" and task.status != "cancelled":
            task.status = "cancelled"
            task.completed_at = timezone.now()
            task.save(update_fields=["status", "completed_at"])

    except Exception:
        logger.warning(
            "Failed to check AsyncResult for task %s",
            task.celery_task_id,
            exc_info=True,
        )


def _task_progress(task: ProcessingTask) -> int:
    """Return the progress percentage for a single task."""
    if task.status == "completed":
        return 100
    elif task.status == "failed":
        return 0
    elif task.status == "running":
        return task.progress
    else:  # pending or cancelled
        return 0


def build_task_data(tasks: list[ProcessingTask]) -> list[dict[str, Any]]:
    """Build the list of task dicts for the processing-status response.

    Each dict contains ``task_type``, ``status``, ``progress``, and
    ``error_message``.  ``AsyncResult`` healing is applied to each task
    before building the dict.

    Args:
        tasks: The list of ``ProcessingTask`` instances (typically ordered
            by ``created_at``).

    Returns:
        A list of serializable dicts.
    """
    task_data: list[dict[str, Any]] = []
    for task in tasks:
        heal_task_from_celery(task)

        task_data.append(
            {
                "task_type": task.task_type,
                "status": task.status,
                "progress": _task_progress(task),
                "error_message": task.error_message,
            }
        )
    return task_data


def compute_display_status(task_data: list[dict[str, Any]]) -> str:
    """Derive the top-level processing status from individual task states.

    Rules (in priority order):
        1. No tasks → ``"pending"``.
        2. Any task ``"failed"`` → ``"failed"``.
        3. Any task ``"cancelled"`` → ``"cancelled"``.
        4. Any task ``"running"`` → ``"processing"``.
        5. Any task ``"pending"`` (none running) → ``"processing"``.
        6. All tasks ``"completed"`` → ``"completed"``.
        7. Fallback → ``"processing"``.

    Args:
        task_data: The list of task dicts from :func:`build_task_data`.

    Returns:
        One of ``"pending"``, ``"processing"``, ``"completed"``,
        ``"failed"``, or ``"cancelled"``.
    """
    if not task_data:
        return "pending"

    statuses = {t["status"] for t in task_data}

    if "failed" in statuses:
        return "failed"
    if "cancelled" in statuses:
        return "cancelled"
    if "running" in statuses:
        return "processing"
    if "pending" in statuses:
        return "processing"
    if statuses == {"completed"}:
        return "completed"

    # Fallback (e.g. mixed completed/pending — shouldn't happen).
    return "processing"


def compute_overall_progress(task_data: list[dict[str, Any]]) -> int:
    """Calculate the overall progress as the average of all task progress values.

    Args:
        task_data: The list of task dicts from :func:`build_task_data`.

    Returns:
        An integer 0–100 representing the average progress.
    """
    if not task_data:
        return 0
    return sum(t["progress"] for t in task_data) // len(task_data)


# ---------------------------------------------------------------------------
# Orchestration — Celery chain
# ---------------------------------------------------------------------------


def process_document(document_id: str) -> str | None:
    """Orchestrate the full document processing pipeline via a Celery chain.

    Creates ``ProcessingTask`` records for each step, then builds and executes
    the chain::

        extract_text_from_pdf → chunk_document → embed_document

    A ``link_error`` callback is attached to the chain so that chain-level
    failures (e.g. worker crash) are caught and the ``ProcessingTask`` status
    is updated to ``"failed"`` rather than remaining stuck at ``"pending"``.

    This is a **regular Python function** (not a Celery task). It is called
    directly from the API view.

    Args:
        document_id: The UUID (as a string) of the :class:`Document` to process.

    Returns:
        The Celery task ID of the chain, or ``None`` if the document is already
        being processed or does not exist.
    """
    # Import Celery tasks here to avoid circular imports:
    # processing_service → tasks.document_processing → processing_service
    from documents.tasks.document_processing import (  # noqa: PLC0415
        _handle_chain_error,
        chunk_document,
        extract_text_from_pdf,
    )
    from documents.tasks.embedding_tasks import embed_document  # noqa: PLC0415

    logger.info("process_document: Starting orchestration for document %s", document_id)

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error("process_document: Document %s not found", document_id)
        return None

    # Prevent duplicate processing.
    if document.processing_status in ("processing", "completed"):
        logger.warning(
            "process_document: Document %s is already being processed or completed — skipping",
            document_id,
        )
        return None

    # Create ProcessingTask records for each pipeline step.
    extract_task = ProcessingTask.objects.create(
        document=document,
        task_type="extract",
        status="pending",
    )
    embed_task = ProcessingTask.objects.create(
        document=document,
        task_type="embed",
        status="pending",
    )

    # Build the Celery chain with a link_error callback.
    # The chain passes the return value of extract_text_from_pdf (extracted text)
    # as the first positional argument to chunk_document.
    # After chunking completes, embed_document generates embeddings for all
    # un-embedded chunks.
    #
    # NOTE: embed_document uses .si() (immutable signature) to prevent Celery
    # from passing the return value of chunk_document (None) as the first
    # positional argument. Without .si(), embed_document would receive
    # (None, document_id, task_id) = 3 positional args, causing:
    #   TypeError: embed_document() takes 3 positional arguments but 4 were given
    chain_obj = chain(
        extract_text_from_pdf.s(document_id),
        chunk_document.s(document_id),
        embed_document.si(document_id, str(embed_task.id)),
    )

    # Attach a link_error callback so chain-level failures are caught.
    # NOTE: Celery's link_error passes (request, exc, traceback) as positional
    # args before the .s() args. The _handle_chain_error task must accept
    # these in its signature.
    error_callback = _handle_chain_error.s(document_id, task_type="extract")

    # Execute the chain with the error callback.
    result = chain_obj.apply_async(link_error=[error_callback])

    # Update the ProcessingTask with the Celery task ID.
    extract_task.celery_task_id = result.id
    extract_task.save(update_fields=["celery_task_id"])

    logger.info(
        "process_document: Chain submitted for document %s (celery_task_id=%s)",
        document_id,
        result.id,
    )

    return result.id
