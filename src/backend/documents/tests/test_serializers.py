"""
Tests for the documents app serializers.

Covers:
- :class:`~documents.serializers.DocumentUploadSerializer`
- :class:`~documents.serializers.DocumentResponseSerializer`
- :class:`~documents.serializers.ProcessingTaskSerializer`
- :class:`~documents.serializers.ProcessingStatusSerializer`
- :class:`~documents.serializers.DocumentEmbedResponseSerializer`
- :class:`~documents.serializers.ChunkBatchEmbedRequestSerializer`
- :class:`~documents.serializers.ChunkBatchEmbedResponseSerializer`
- :class:`~documents.serializers.ChunkReEmbedResponseSerializer`
"""

from __future__ import annotations

import io
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone as tz_utils

from documents.serializers import (
    ChunkBatchEmbedRequestSerializer,
    ChunkBatchEmbedResponseSerializer,
    ChunkReEmbedResponseSerializer,
    DocumentEmbedResponseSerializer,
    DocumentResponseSerializer,
    DocumentUploadSerializer,
    ProcessingStatusSerializer,
    ProcessingTaskSerializer,
    SearchRequestSerializer,
    SearchResultSerializer,
    SearchResponseSerializer,
)


# ---------------------------------------------------------------------------
# Tests — DocumentUploadSerializer
# ---------------------------------------------------------------------------


class DocumentUploadSerializerTests(TestCase):
    """Validate that the upload serializer correctly accepts/rejects input."""

    def test_valid_file_and_title_passes(self) -> None:
        """A ``SimpleUploadedFile`` with a title should pass validation."""
        uploaded = SimpleUploadedFile("test.pdf", b"dummy content")
        serializer = DocumentUploadSerializer(
            data={"file": uploaded, "title": "My Document"},
        )
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["title"], "My Document")

    def test_missing_file_returns_error(self) -> None:
        """Omitting the ``file`` field should fail validation."""
        serializer = DocumentUploadSerializer(data={"title": "My Document"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("file", serializer.errors)

    def test_missing_title_defaults_to_empty(self) -> None:
        """Omitting the ``title`` field should default to empty string."""
        uploaded = SimpleUploadedFile("test.pdf", b"dummy content")
        serializer = DocumentUploadSerializer(data={"file": uploaded})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["title"], "")

    def test_none_file_returns_error(self) -> None:
        """Passing ``None`` for the file field should fail validation."""
        serializer = DocumentUploadSerializer(
            data={"file": None, "title": "My Document"},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("file", serializer.errors)

    def test_help_text_is_set(self) -> None:
        """The ``file`` and ``title`` fields should have descriptive help_text."""
        serializer = DocumentUploadSerializer()
        file_field = serializer.fields["file"]
        title_field = serializer.fields["title"]
        self.assertIn("document file", file_field.help_text.lower())
        self.assertIn("title", title_field.help_text.lower())


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


# ---------------------------------------------------------------------------
# Tests — DocumentEmbedResponseSerializer
# ---------------------------------------------------------------------------


class DocumentEmbedResponseSerializerTests(TestCase):
    """Validate the embed-response serializer for POST /documents/{id}/embed."""

    def setUp(self) -> None:
        self.data = {
            "task_id": uuid.uuid4(),
            "task_type": "embed",
            "status": "pending",
            "document_id": uuid.uuid4(),
            "total_chunks": 5,
        }

    def test_valid_data_passes(self) -> None:
        """All required fields present should pass validation."""
        serializer = DocumentEmbedResponseSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_serializes_output(self) -> None:
        """Output dict has correct types (UUID to str, etc.)."""
        serializer = DocumentEmbedResponseSerializer(instance=self.data)
        output = serializer.data
        self.assertEqual(output["task_id"], str(self.data["task_id"]))
        self.assertEqual(output["task_type"], "embed")
        self.assertEqual(output["status"], "pending")
        self.assertEqual(output["document_id"], str(self.data["document_id"]))
        self.assertEqual(output["total_chunks"], 5)

    def test_default_task_type(self) -> None:
        """``task_type`` defaults to ``\"embed\"``."""
        data = {
            "task_id": uuid.uuid4(),
            "document_id": uuid.uuid4(),
            "total_chunks": 3,
        }
        serializer = DocumentEmbedResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["task_type"], "embed")

    def test_default_status(self) -> None:
        """``status`` defaults to ``\"pending\"``."""
        data = {
            "task_id": uuid.uuid4(),
            "document_id": uuid.uuid4(),
            "total_chunks": 3,
        }
        serializer = DocumentEmbedResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["status"], "pending")

    def test_missing_task_id_returns_error(self) -> None:
        """Omitting ``task_id`` fails validation."""
        self.data.pop("task_id")
        serializer = DocumentEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("task_id", serializer.errors)

    def test_missing_document_id_returns_error(self) -> None:
        """Omitting ``document_id`` fails validation."""
        self.data.pop("document_id")
        serializer = DocumentEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("document_id", serializer.errors)

    def test_missing_total_chunks_returns_error(self) -> None:
        """Omitting ``total_chunks`` fails validation."""
        self.data.pop("total_chunks")
        serializer = DocumentEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("total_chunks", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field has descriptive help_text."""
        serializer = DocumentEmbedResponseSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ChunkBatchEmbedRequestSerializer
# ---------------------------------------------------------------------------


class ChunkBatchEmbedRequestSerializerTests(TestCase):
    """Validate the batch-embed request serializer for POST /chunks/batch-embed."""

    def setUp(self) -> None:
        self.data = {
            "chunk_ids": [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()],
        }

    def test_valid_chunk_ids_passes(self) -> None:
        """List of valid UUIDs passes."""
        serializer = ChunkBatchEmbedRequestSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_empty_list_passes(self) -> None:
        """Empty list is valid (view handles it)."""
        self.data["chunk_ids"] = []
        serializer = ChunkBatchEmbedRequestSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_invalid_uuid_fails(self) -> None:
        """Non-UUID string in list fails."""
        self.data["chunk_ids"] = ["not-a-uuid"]
        serializer = ChunkBatchEmbedRequestSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("chunk_ids", serializer.errors)

    def test_missing_chunk_ids_returns_error(self) -> None:
        """Omitting ``chunk_ids`` fails."""
        self.data.pop("chunk_ids")
        serializer = ChunkBatchEmbedRequestSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("chunk_ids", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field has descriptive help_text."""
        serializer = ChunkBatchEmbedRequestSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ChunkBatchEmbedResponseSerializer
# ---------------------------------------------------------------------------


class ChunkBatchEmbedResponseSerializerTests(TestCase):
    """Validate the batch-embed response serializer for POST /chunks/batch-embed."""

    def setUp(self) -> None:
        self.data = {
            "processed": 10,
            "skipped": 2,
            "failed": 1,
        }

    def test_valid_data_passes(self) -> None:
        """All fields present passes."""
        serializer = ChunkBatchEmbedResponseSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_serializes_output(self) -> None:
        """Output has correct integer values."""
        serializer = ChunkBatchEmbedResponseSerializer(instance=self.data)
        output = serializer.data
        self.assertEqual(output["processed"], 10)
        self.assertEqual(output["skipped"], 2)
        self.assertEqual(output["failed"], 1)

    def test_zero_counts_are_valid(self) -> None:
        """All zeros is valid."""
        data = {"processed": 0, "skipped": 0, "failed": 0}
        serializer = ChunkBatchEmbedResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_missing_processed_returns_error(self) -> None:
        """Omitting ``processed`` fails."""
        self.data.pop("processed")
        serializer = ChunkBatchEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("processed", serializer.errors)

    def test_missing_skipped_returns_error(self) -> None:
        """Omitting ``skipped`` fails."""
        self.data.pop("skipped")
        serializer = ChunkBatchEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("skipped", serializer.errors)

    def test_missing_failed_returns_error(self) -> None:
        """Omitting ``failed`` fails."""
        self.data.pop("failed")
        serializer = ChunkBatchEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("failed", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field has descriptive help_text."""
        serializer = ChunkBatchEmbedResponseSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — ChunkReEmbedResponseSerializer
# ---------------------------------------------------------------------------


class ChunkReEmbedResponseSerializerTests(TestCase):
    """Validate the re-embed response serializer for POST /chunks/{chunk_id}/re-embed."""

    def setUp(self) -> None:
        self.data = {
            "chunk_id": uuid.uuid4(),
            "embedding_updated": True,
        }

    def test_valid_data_passes(self) -> None:
        """All fields present passes."""
        serializer = ChunkReEmbedResponseSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_serializes_output(self) -> None:
        """Output has correct types."""
        serializer = ChunkReEmbedResponseSerializer(instance=self.data)
        output = serializer.data
        self.assertEqual(output["chunk_id"], str(self.data["chunk_id"]))
        self.assertTrue(output["embedding_updated"])

    def test_embedding_updated_true(self) -> None:
        """Boolean ``True`` is valid."""
        self.data["embedding_updated"] = True
        serializer = ChunkReEmbedResponseSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_embedding_updated_false(self) -> None:
        """Boolean ``False`` is valid."""
        self.data["embedding_updated"] = False
        serializer = ChunkReEmbedResponseSerializer(data=self.data)
        self.assertTrue(serializer.is_valid())

    def test_missing_chunk_id_returns_error(self) -> None:
        """Omitting ``chunk_id`` fails."""
        self.data.pop("chunk_id")
        serializer = ChunkReEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("chunk_id", serializer.errors)

    def test_missing_embedding_updated_returns_error(self) -> None:
        """Omitting ``embedding_updated`` fails."""
        self.data.pop("embedding_updated")
        serializer = ChunkReEmbedResponseSerializer(data=self.data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("embedding_updated", serializer.errors)

    def test_help_text_on_all_fields(self) -> None:
        """Every field has descriptive help_text."""
        serializer = ChunkReEmbedResponseSerializer()
        for field_name, field in serializer.fields.items():
            with self.subTest(field=field_name):
                self.assertTrue(
                    field.help_text,
                    f"Field '{field_name}' is missing help_text",
                )


# ---------------------------------------------------------------------------
# Tests — SearchRequestSerializer
# ---------------------------------------------------------------------------


class SearchRequestSerializerTests(TestCase):
    """Validate the search request serializer for POST /documents/{id}/search."""

    def test_search_request_defaults(self) -> None:
        """Omitting ``top_k`` and ``min_score`` gives defaults 10 and 0.0."""
        serializer = SearchRequestSerializer(data={"query": "test query"})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["top_k"], 10)
        self.assertEqual(serializer.validated_data["min_score"], 0.0)

    def test_search_request_top_k_max_validation(self) -> None:
        """``top_k=51`` fails validation (max is 50)."""
        serializer = SearchRequestSerializer(
            data={"query": "test", "top_k": 51}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("top_k", serializer.errors)

    def test_search_request_min_score_range(self) -> None:
        """``min_score`` values outside [0.0, 1.0] fail validation."""
        for score in (-0.1, 1.1):
            with self.subTest(score=score):
                serializer = SearchRequestSerializer(
                    data={"query": "test", "min_score": score}
                )
                self.assertFalse(serializer.is_valid())
                self.assertIn("min_score", serializer.errors)

    def test_search_request_empty_query(self) -> None:
        """Empty string fails validation (``required=True``, ``min_length`` implied)."""
        serializer = SearchRequestSerializer(data={"query": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("query", serializer.errors)

    def test_search_mode_defaults_to_hybrid(self) -> None:
        """Omitting ``search_mode`` defaults to ``"hybrid"``."""
        serializer = SearchRequestSerializer(data={"query": "test"})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["search_mode"], "hybrid")

    def test_search_mode_accepts_vector(self) -> None:
        """``search_mode="vector"`` is valid."""
        serializer = SearchRequestSerializer(
            data={"query": "test", "search_mode": "vector"}
        )
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["search_mode"], "vector")

    def test_search_mode_accepts_keyword(self) -> None:
        """``search_mode="keyword"`` is valid."""
        serializer = SearchRequestSerializer(
            data={"query": "test", "search_mode": "keyword"}
        )
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["search_mode"], "keyword")

    def test_search_mode_invalid_choice_fails(self) -> None:
        """``search_mode="invalid"`` fails validation."""
        serializer = SearchRequestSerializer(
            data={"query": "test", "search_mode": "invalid"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("search_mode", serializer.errors)

    def test_filters_accepts_valid_dict(self) -> None:
        """``filters={"legal_status": "valid"}`` is accepted."""
        serializer = SearchRequestSerializer(
            data={"query": "test", "filters": {"legal_status": "valid"}}
        )
        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            serializer.validated_data["filters"],
            {"legal_status": "valid"},
        )

    def test_filters_defaults_to_none(self) -> None:
        """Omitting ``filters`` defaults to ``None``."""
        serializer = SearchRequestSerializer(data={"query": "test"})
        self.assertTrue(serializer.is_valid())
        self.assertIsNone(serializer.validated_data.get("filters"))


class SearchResultSerializerTests(TestCase):
    """Validate the search result serializer for hybrid/keyword search responses."""

    def test_minimal_result_passes(self) -> None:
        """Only required fields should pass validation."""
        serializer = SearchResultSerializer(data={
            "chunk_id": str(uuid.uuid4()),
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 2,
            "content": "test content",
            "relevance_score": 0.9,
            "token_count": 10,
            "metadata": {},
        })
        self.assertTrue(serializer.is_valid())

    def test_hybrid_result_fields(self) -> None:
        """Hybrid search result with vector_score, keyword_score, rrf_score."""
        data = {
            "chunk_id": str(uuid.uuid4()),
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 2,
            "content": "test content",
            "relevance_score": 0.9,
            "token_count": 10,
            "metadata": {},
            "vector_score": 0.85,
            "keyword_score": 0.75,
            "rrf_score": 0.02,
        }
        serializer = SearchResultSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            serializer.validated_data["vector_score"], 0.85,
        )
        self.assertEqual(
            serializer.validated_data["keyword_score"], 0.75,
        )
        self.assertEqual(
            serializer.validated_data["rrf_score"], 0.02,
        )

    def test_hybrid_result_fields_optional(self) -> None:
        """vector_score, keyword_score, rrf_score are optional."""
        serializer = SearchResultSerializer(data={
            "chunk_id": str(uuid.uuid4()),
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 2,
            "content": "test content",
            "relevance_score": 0.9,
            "token_count": 10,
            "metadata": {},
        })
        self.assertTrue(serializer.is_valid())
        self.assertIsNone(
            serializer.validated_data.get("vector_score"),
        )
        self.assertIsNone(
            serializer.validated_data.get("keyword_score"),
        )
        self.assertIsNone(
            serializer.validated_data.get("rrf_score"),
        )


class SearchResponseSerializerTests(TestCase):
    """Validate the search response serializer includes search_mode and filters."""

    def test_response_contains_search_mode_and_filters(self) -> None:
        """search_mode and filters are included in the serialized output."""
        data = {
            "results": [],
            "query": "test",
            "top_k": 10,
            "min_score": 0.0,
            "total_results": 0,
            "search_mode": "hybrid",
            "filters": {"legal_status": "valid"},
        }
        serializer = SearchResponseSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["search_mode"], "hybrid")
        self.assertEqual(
            serializer.validated_data["filters"],
            {"legal_status": "valid"},
        )

    def test_response_search_mode_defaults_to_hybrid(self) -> None:
        """Omitting search_mode defaults to "hybrid"."""
        serializer = SearchResponseSerializer(data={
            "results": [],
            "query": "test",
            "top_k": 10,
            "min_score": 0.0,
            "total_results": 0,
        })
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["search_mode"], "hybrid")

    def test_response_filters_defaults_to_none(self) -> None:
        """Omitting filters defaults to None."""
        serializer = SearchResponseSerializer(data={
            "results": [],
            "query": "test",
            "top_k": 10,
            "min_score": 0.0,
            "total_results": 0,
        })
        self.assertTrue(serializer.is_valid())
        self.assertIsNone(serializer.validated_data.get("filters"))
