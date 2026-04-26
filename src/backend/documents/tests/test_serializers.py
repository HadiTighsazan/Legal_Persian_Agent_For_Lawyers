"""
Tests for the documents app serializers.

Covers:
- :class:`~documents.serializers.DocumentUploadSerializer`
- :class:`~documents.serializers.DocumentResponseSerializer`
- :class:`~documents.serializers.ProcessingTaskSerializer`
- :class:`~documents.serializers.ProcessingStatusSerializer`
"""

from __future__ import annotations

import io
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone as tz_utils

from documents.serializers import (
    DocumentResponseSerializer,
    DocumentUploadSerializer,
    ProcessingStatusSerializer,
    ProcessingTaskSerializer,
)


# ---------------------------------------------------------------------------
# Tests — DocumentUploadSerializer
# ---------------------------------------------------------------------------


class DocumentUploadSerializerTests(TestCase):
    """Validate that the upload serializer correctly accepts/rejects input."""

    def test_valid_file_passes(self) -> None:
        """A ``SimpleUploadedFile`` should pass validation."""
        uploaded = SimpleUploadedFile("test.pdf", b"dummy content")
        serializer = DocumentUploadSerializer(data={"file": uploaded})
        self.assertTrue(serializer.is_valid())

    def test_missing_file_returns_error(self) -> None:
        """Omitting the ``file`` field should fail validation."""
        serializer = DocumentUploadSerializer(data={})
        self.assertFalse(serializer.is_valid())
        self.assertIn("file", serializer.errors)

    def test_none_file_returns_error(self) -> None:
        """Passing ``None`` for the file field should fail validation."""
        serializer = DocumentUploadSerializer(data={"file": None})
        self.assertFalse(serializer.is_valid())
        self.assertIn("file", serializer.errors)

    def test_help_text_is_set(self) -> None:
        """The ``file`` field should have a descriptive help_text."""
        field = DocumentUploadSerializer().fields["file"]
        self.assertIn("document file", field.help_text.lower())


# ---------------------------------------------------------------------------
# Tests — DocumentResponseSerializer
# ---------------------------------------------------------------------------


class DocumentResponseSerializerTests(TestCase):
    """Validate the document metadata response serializer."""

    def setUp(self) -> None:
        self.now = tz_utils.now()
        self.data = {
            "id": uuid.uuid4(),
            "title": "test.pdf",
            "original_filename": "my-doc.pdf",
            "file_size": 2048,
            "mime_type": "application/pdf",
            "file_path": "/storage/test.pdf",
            "storage_type": "local",
            "status": "uploaded",
            "created_at": self.now,
        }

    def test_valid_data_passes(self) -> None:
        """All required fields present should pass validation."""
        serializer = DocumentResponseSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_serializes_output(self) -> None:
        """The serializer should produce the expected output dict."""
        serializer = DocumentResponseSerializer(instance=self.data)
        output = serializer.data
        # DRF serializes UUIDs to strings
        self.assertEqual(output["id"], str(self.data["id"]))
        self.assertEqual(output["title"], "test.pdf")
        self.assertEqual(output["original_filename"], "my-doc.pdf")
        self.assertEqual(output["file_size"], 2048)
        self.assertEqual(output["mime_type"], "application/pdf")
        self.assertEqual(output["file_path"], "/storage/test.pdf")
        self.assertEqual(output["storage_type"], "local")
        self.assertEqual(output["status"], "uploaded")
        # DRF serializes datetimes as ISO strings
        self.assertIsInstance(output["created_at"], str)

    def test_missing_id_returns_error(self) -> None:
        """Omitting ``id`` should fail validation."""
        self.data.pop("id")
        serializer = DocumentResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("id", serializer.errors)

    def test_missing_title_returns_error(self) -> None:
        """Omitting ``title`` should fail validation."""
        self.data.pop("title")
        serializer = DocumentResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("title", serializer.errors)

    def test_missing_status_returns_error(self) -> None:
        """Omitting ``status`` should fail validation."""
        self.data.pop("status")
        serializer = DocumentResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("status", serializer.errors)

    def test_invalid_uuid_returns_error(self) -> None:
        """An invalid UUID string should fail validation."""
        self.data["id"] = "not-a-uuid"
        serializer = DocumentResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("id", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = DocumentResponseSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ProcessingTaskSerializer
# ---------------------------------------------------------------------------


class ProcessingTaskSerializerTests(TestCase):
    """Validate the per-task serializer used in the status response."""

    def setUp(self) -> None:
        self.data = {
            "task_type": "extract",
            "status": "running",
            "progress": 50,
            "error_message": None,
        }

    def test_valid_data_passes(self) -> None:
        """All required fields present should pass validation."""
        serializer = ProcessingTaskSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_serializes_output(self) -> None:
        """The serializer should produce the expected output dict."""
        serializer = ProcessingTaskSerializer(instance=self.data)
        output = serializer.data
        self.assertEqual(output["task_type"], "extract")
        self.assertEqual(output["status"], "running")
        self.assertEqual(output["progress"], 50)
        self.assertIsNone(output["error_message"])

    def test_error_message_can_be_string(self) -> None:
        """``error_message`` should accept a string value."""
        self.data["error_message"] = "Something went wrong"
        serializer = ProcessingTaskSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            serializer.validated_data["error_message"],
            "Something went wrong",
        )

    def test_missing_task_type_returns_error(self) -> None:
        """Omitting ``task_type`` should fail validation."""
        self.data.pop("task_type")
        serializer = ProcessingTaskSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("task_type", serializer.errors)

    def test_missing_status_returns_error(self) -> None:
        """Omitting ``status`` should fail validation."""
        self.data.pop("status")
        serializer = ProcessingTaskSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("status", serializer.errors)

    def test_missing_progress_returns_error(self) -> None:
        """Omitting ``progress`` should fail validation."""
        self.data.pop("progress")
        serializer = ProcessingTaskSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("progress", serializer.errors)

    def test_progress_must_be_integer(self) -> None:
        """``progress`` should reject non-integer values."""
        self.data["progress"] = "fifty"
        serializer = ProcessingTaskSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("progress", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = ProcessingTaskSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ProcessingStatusSerializer
# ---------------------------------------------------------------------------


class ProcessingStatusSerializerTests(TestCase):
    """Validate the top-level processing-status response serializer."""

    def setUp(self) -> None:
        self.data = {
            "document_id": uuid.uuid4(),
            "status": "completed",
            "progress": 100,
            "tasks": [
                {
                    "task_type": "extract",
                    "status": "completed",
                    "progress": 100,
                    "error_message": None,
                },
                {
                    "task_type": "chunk",
                    "status": "completed",
                    "progress": 100,
                    "error_message": None,
                },
            ],
        }

    def test_valid_data_passes(self) -> None:
        """All required fields present should pass validation."""
        serializer = ProcessingStatusSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_serializes_output(self) -> None:
        """The serializer should produce the expected output dict."""
        serializer = ProcessingStatusSerializer(instance=self.data)
        output = serializer.data
        # DRF serializes UUIDs to strings
        self.assertEqual(output["document_id"], str(self.data["document_id"]))
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["progress"], 100)
        self.assertEqual(len(output["tasks"]), 2)

    def test_missing_document_id_returns_error(self) -> None:
        """Omitting ``document_id`` should fail validation."""
        self.data.pop("document_id")
        serializer = ProcessingStatusSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("document_id", serializer.errors)

    def test_missing_status_returns_error(self) -> None:
        """Omitting ``status`` should fail validation."""
        self.data.pop("status")
        serializer = ProcessingStatusSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("status", serializer.errors)

    def test_missing_progress_returns_error(self) -> None:
        """Omitting ``progress`` should fail validation."""
        self.data.pop("progress")
        serializer = ProcessingStatusSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("progress", serializer.errors)

    def test_missing_tasks_returns_error(self) -> None:
        """Omitting ``tasks`` should fail validation."""
        self.data.pop("tasks")
        serializer = ProcessingStatusSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("tasks", serializer.errors)

    def test_empty_tasks_list_is_valid(self) -> None:
        """An empty ``tasks`` list should pass validation."""
        self.data["tasks"] = []
        serializer = ProcessingStatusSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_invalid_task_entry_fails(self) -> None:
        """A task entry missing required fields should fail validation."""
        self.data["tasks"] = [{"task_type": "extract"}]  # missing status/progress
        serializer = ProcessingStatusSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("tasks", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field should have a descriptive help_text."""
        serializer = ProcessingStatusSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )
