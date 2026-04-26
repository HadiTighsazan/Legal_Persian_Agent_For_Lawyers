"""
Tests for the document processing API views.

Covers:
- :class:`~documents.views.DocumentProcessView` (POST)
- :class:`~documents.views.DocumentProcessingStatusView` (GET)
- :class:`~documents.views.DocumentUploadView` (POST) — basic smoke test
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import ANY, MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import Document
from tasks.models import ProcessingTask
from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_header(user: User) -> dict[str, str]:
    """Return an Authorization header dict for the given user.

    Uses ``rest_framework_simplejwt`` to generate a valid access token.
    """
    from rest_framework_simplejwt.tokens import RefreshToken  # noqa: PLC0415

    refresh = RefreshToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}


def _create_document(
    user: User,
    processing_status: str = "pending",
    **kwargs,
) -> Document:
    """Create a Document with sensible defaults for testing."""
    return Document.objects.create(
        user=user,
        title=kwargs.get("title", "Test Document"),
        filename=kwargs.get("filename", "test.pdf"),
        original_filename=kwargs.get("original_filename", "test.pdf"),
        file_path=kwargs.get("file_path", "/tmp/test.pdf"),
        file_size=kwargs.get("file_size", 1000),
        mime_type=kwargs.get("mime_type", "application/pdf"),
        processing_status=processing_status,
    )


# ---------------------------------------------------------------------------
# Tests — DocumentProcessView (POST /documents/<uuid>/process/)
# ---------------------------------------------------------------------------


class DocumentProcessViewTests(TestCase):
    """Tests for the :class:`DocumentProcessView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="process-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.url = reverse(
            "documents:document-process",
            kwargs={"document_id": self.document.id},
        )

    # -- 404 Not Found -----------------------------------------------------

    def test_nonexistent_document_returns_404(self) -> None:
        """POST to a non-existent document ID should return 404."""
        url = reverse(
            "documents:document-process",
            kwargs={"document_id": uuid.uuid4()},
        )
        response = self.client.post(url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    # -- 403 Forbidden -----------------------------------------------------

    def test_other_users_document_returns_403(self) -> None:
        """POST to another user's document should return 403."""
        response = self.client.post(self.url, **_auth_header(self.other_user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    # -- 401 Unauthenticated -----------------------------------------------

    def test_unauthenticated_request_returns_401(self) -> None:
        """POST without auth should return 401."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- 202 Accepted (happy path) -----------------------------------------

    @patch("documents.views.process_document")
    def test_starts_processing_and_returns_202(self, mock_process: MagicMock) -> None:
        """Successful trigger should return 202 with task_id and status."""
        mock_process.return_value = "celery-task-id-123"

        response = self.client.post(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["task_id"], "celery-task-id-123")
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["document_id"], str(self.document.id))

        mock_process.assert_called_once_with(str(self.document.id))

    # -- 400 Bad Request (already processing) ------------------------------

    @patch("documents.views.process_document")
    def test_already_processing_returns_400(self, mock_process: MagicMock) -> None:
        """If process_document returns None, the view should return 400."""
        mock_process.return_value = None

        response = self.client.post(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "bad_request")
        self.assertIn("already being processed", response.data["message"])

        mock_process.assert_called_once_with(str(self.document.id))


# ---------------------------------------------------------------------------
# Tests — DocumentProcessingStatusView (GET /documents/<uuid>/processing-status/)
# ---------------------------------------------------------------------------


class DocumentProcessingStatusViewTests(TestCase):
    """Tests for the :class:`DocumentProcessingStatusView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="status-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-status@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.url = reverse(
            "documents:document-processing-status",
            kwargs={"document_id": self.document.id},
        )

    # -- 404 Not Found -----------------------------------------------------

    def test_nonexistent_document_returns_404(self) -> None:
        """GET for a non-existent document should return 404."""
        url = reverse(
            "documents:document-processing-status",
            kwargs={"document_id": uuid.uuid4()},
        )
        response = self.client.get(url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    # -- 403 Forbidden -----------------------------------------------------

    def test_other_users_document_returns_403(self) -> None:
        """GET for another user's document should return 403."""
        response = self.client.get(self.url, **_auth_header(self.other_user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    # -- 401 Unauthenticated -----------------------------------------------

    def test_unauthenticated_request_returns_401(self) -> None:
        """GET without auth should return 401."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- 200 OK — no tasks (pending) ---------------------------------------

    def test_no_tasks_returns_pending(self) -> None:
        """A document with no ProcessingTasks should show status='pending'."""
        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["document_id"], str(self.document.id))
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["progress"], 0)
        self.assertEqual(data["tasks"], [])

    # -- 200 OK — single completed task ------------------------------------

    def test_single_completed_task(self) -> None:
        """A document with one completed task should show status='completed'."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-001",
            status="completed",
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["progress"], 100)
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["task_type"], "extract")
        self.assertEqual(data["tasks"][0]["status"], "completed")
        self.assertEqual(data["tasks"][0]["progress"], 100)

    # -- 200 OK — running task ---------------------------------------------

    def test_running_task_shows_processing(self) -> None:
        """A document with a running task should show status='processing'."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-002",
            status="running",
            progress=45,
            started_at=timezone.now(),
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["progress"], 45)

    # -- 200 OK — mixed tasks (completed + running) ------------------------

    def test_mixed_tasks_shows_processing(self) -> None:
        """With one completed and one running task, status should be 'processing'."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-003",
            status="completed",
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )
        ProcessingTask.objects.create(
            document=self.document,
            task_type="chunk",
            celery_task_id="chunk-001",
            status="running",
            progress=30,
            started_at=timezone.now(),
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "processing")
        # Average of 100 (completed) and 30 (running)
        self.assertEqual(data["progress"], 65)
        self.assertEqual(len(data["tasks"]), 2)

    # -- 200 OK — failed task ----------------------------------------------

    def test_failed_task_shows_failed(self) -> None:
        """A document with a failed task should show status='failed'."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-004",
            status="failed",
            error_message="PDF is corrupted",
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["progress"], 0)
        self.assertEqual(data["tasks"][0]["error_message"], "PDF is corrupted")

    # -- 200 OK — cancelled task -------------------------------------------

    def test_cancelled_task_shows_cancelled(self) -> None:
        """A document with a cancelled task should show status='cancelled'."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-005",
            status="cancelled",
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "cancelled")

    # -- 200 OK — failed takes priority over running -----------------------

    def test_failed_takes_priority_over_running(self) -> None:
        """If one task failed and another is running, status should be 'failed'."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-006",
            status="failed",
            error_message="Extraction failed",
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )
        ProcessingTask.objects.create(
            document=self.document,
            task_type="chunk",
            celery_task_id="chunk-002",
            status="running",
            progress=50,
            started_at=timezone.now(),
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        # "failed" has higher priority than "running"
        self.assertEqual(data["status"], "failed")

    # -- 200 OK — pending task (queued) ------------------------------------

    def test_pending_task_shows_processing(self) -> None:
        """A document with a pending task (queued but not running) should show 'processing'."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-007",
            status="pending",
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["progress"], 0)

    # -- Response format matches serializer --------------------------------

    def test_response_format_matches_serializer(self) -> None:
        """The response should contain all expected fields."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            celery_task_id="extract-008",
            status="completed",
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )

        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("document_id", data)
        self.assertIn("status", data)
        self.assertIn("progress", data)
        self.assertIn("tasks", data)

        task = data["tasks"][0]
        self.assertIn("task_type", task)
        self.assertIn("status", task)
        self.assertIn("progress", task)
        self.assertIn("error_message", task)


# ---------------------------------------------------------------------------
# Tests — DocumentUploadView (POST /documents/upload/) — smoke test
# ---------------------------------------------------------------------------


class DocumentUploadViewSmokeTests(TestCase):
    """Smoke tests for the :class:`DocumentUploadView` endpoint.

    Full upload tests (with actual files) are in ``test_upload_integration.py``.
    """

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="upload-test@example.com",
            password="testpass123",
        )
        self.url = reverse("documents:document-upload")

    def test_unauthenticated_request_returns_401(self) -> None:
        """POST without auth should return 401."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_file_returns_400(self) -> None:
        """POST without a file should return 400."""
        response = self.client.post(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Tests — ProcessingService functions (unit-level)
# ---------------------------------------------------------------------------


class ProcessingServiceUnitTests(TestCase):
    """Unit tests for the processing service functions directly."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="service-test@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)

    # -- heal_task_from_celery --------------------------------------------

    @patch("documents.services.processing_service.celery_app")
    def test_heal_skips_completed_task(self, mock_celery: MagicMock) -> None:
        """heal_task_from_celery should skip tasks already in a terminal state."""
        task = ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            status="completed",
        )
        from documents.services.processing_service import heal_task_from_celery

        heal_task_from_celery(task)
        mock_celery.AsyncResult.assert_not_called()

    @patch("documents.services.processing_service.celery_app")
    def test_heal_skips_task_without_celery_id(self, mock_celery: MagicMock) -> None:
        """heal_task_from_celery should skip tasks without a celery_task_id."""
        task = ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            status="pending",
            celery_task_id=None,
        )
        from documents.services.processing_service import heal_task_from_celery

        heal_task_from_celery(task)
        mock_celery.AsyncResult.assert_not_called()

    # -- compute_display_status -------------------------------------------

    def test_display_status_empty_list_is_pending(self) -> None:
        """An empty task list should return 'pending'."""
        from documents.services.processing_service import compute_display_status

        self.assertEqual(compute_display_status([]), "pending")

    def test_display_status_all_completed(self) -> None:
        """All tasks completed should return 'completed'."""
        from documents.services.processing_service import compute_display_status

        task_data = [
            {"task_type": "extract", "status": "completed", "progress": 100, "error_message": None},
            {"task_type": "chunk", "status": "completed", "progress": 100, "error_message": None},
        ]
        self.assertEqual(compute_display_status(task_data), "completed")

    def test_display_status_failed_takes_priority(self) -> None:
        """Failed status should take priority over completed."""
        from documents.services.processing_service import compute_display_status

        task_data = [
            {"task_type": "extract", "status": "completed", "progress": 100, "error_message": None},
            {"task_type": "chunk", "status": "failed", "progress": 0, "error_message": "Error"},
        ]
        self.assertEqual(compute_display_status(task_data), "failed")

    def test_display_status_cancelled_takes_priority(self) -> None:
        """Cancelled status should take priority over completed."""
        from documents.services.processing_service import compute_display_status

        task_data = [
            {"task_type": "extract", "status": "completed", "progress": 100, "error_message": None},
            {"task_type": "chunk", "status": "cancelled", "progress": 0, "error_message": None},
        ]
        self.assertEqual(compute_display_status(task_data), "cancelled")

    # -- compute_overall_progress -----------------------------------------

    def test_overall_progress_average(self) -> None:
        """Overall progress should be the average of all task progress values."""
        from documents.services.processing_service import compute_overall_progress

        task_data = [
            {"task_type": "extract", "status": "completed", "progress": 100, "error_message": None},
            {"task_type": "chunk", "status": "running", "progress": 50, "error_message": None},
        ]
        self.assertEqual(compute_overall_progress(task_data), 75)

    def test_overall_progress_empty_list(self) -> None:
        """Empty task list should return 0."""
        from documents.services.processing_service import compute_overall_progress

        self.assertEqual(compute_overall_progress([]), 0)
