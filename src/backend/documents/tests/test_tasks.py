"""
Tests for the document processing Celery tasks.

Covers:
- :func:`~documents.tasks.document_processing.extract_text_from_pdf`
- :func:`~documents.tasks.document_processing.chunk_document`
- :func:`~documents.tasks.document_processing.process_document`
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import MagicMock, PropertyMock, patch

import fitz
from django.test import TestCase
from django.utils import timezone

from documents.models import Document, DocumentChunk
from documents.services.chunking_service import ChunkingService
from documents.tasks.document_processing import (
    chunk_document,
    extract_text_from_pdf,
    process_document,
)
from tasks.models import ProcessingTask
from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_sample_pdf(path: str, page_texts: list[str] | None = None) -> str:
    """Create a simple PDF at *path* with one page per string in *page_texts*.

    Returns the same *path* for convenience.
    """
    if page_texts is None:
        page_texts = ["Hello from page 1.", "This is page two content."]

    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((50, 100), text)
    doc.save(path)
    doc.close()
    return path


def _create_empty_pdf(path: str) -> str:
    """Create a valid PDF file with zero pages.

    PyMuPDF (``fitz``) refuses to save a document with 0 pages, so we
    write a minimal valid PDF 1.4 file manually.  The structure is:

    - Header
    - Catalog object (root)
    - Pages object with ``/Count 0`` and empty ``/Kids``
    - Cross-reference table
    - Trailer
    """
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n"
        b"<< /Type /Catalog /Pages 2 0 R >>\n"
        b"endobj\n"
        b"\n"
        b"2 0 obj\n"
        b"<< /Type /Pages /Kids [] /Count 0 >>\n"
        b"endobj\n"
        b"\n"
        b"xref\n"
        b"0 3\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"\n"
        b"trailer\n"
        b"<< /Size 3 /Root 1 0 R >>\n"
        b"startxref\n"
        b"109\n"
        b"%%EOF"
    )
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    return path


def _mock_celery_request(task_func, celery_task_id: str = "test-celery-id"):
    """Context manager that patches the Celery task ``request`` property.

    Celery's ``@shared_task(bind=True)`` wraps the function such that
    ``self.request`` is a read-only property on a ``PromiseProxy`` object,
    which cannot be patched directly with ``patch.object``.  Instead we
    patch ``celery.app.task.Task.request`` which is the underlying source
    of the property.
    """
    return patch(
        "celery.app.task.Task.request",
        new_callable=PropertyMock,
        return_value=MagicMock(id=celery_task_id),
    )


# ---------------------------------------------------------------------------
# Tests — extract_text_from_pdf
# ---------------------------------------------------------------------------


class ExtractTextFromPdfTests(TestCase):
    """Tests for the :func:`extract_text_from_pdf` task."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )

        # Create a temporary PDF file.
        self.tmpdir = tempfile.mkdtemp()
        self.pdf_path = os.path.join(self.tmpdir, "sample.pdf")
        _create_sample_pdf(self.pdf_path, ["Page one content.", "Page two content."])

        self.document = Document.objects.create(
            user=self.user,
            title="Test Document",
            filename="sample.pdf",
            original_filename="sample.pdf",
            file_path=self.pdf_path,
            file_size=os.path.getsize(self.pdf_path),
            mime_type="application/pdf",
            processing_status="pending",
        )

    def tearDown(self) -> None:
        # Clean up the entire temp directory tree.
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def _run_task(self) -> str:
        """Convenience: run the task synchronously with a mock Celery request."""
        with _mock_celery_request(extract_text_from_pdf):
            return extract_text_from_pdf(str(self.document.id))

    # -- Happy path -------------------------------------------------------

    def test_extracts_text_with_page_markers(self) -> None:
        """Verify that extracted text contains ``[PAGE N]`` markers."""
        result = self._run_task()

        self.assertIn("[PAGE 1]", result)
        self.assertIn("[PAGE 2]", result)
        self.assertIn("Page one content.", result)
        self.assertIn("Page two content.", result)

    def test_creates_processing_task(self) -> None:
        """A ProcessingTask with task_type='extract' should be created."""
        self._run_task()

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="extract",
        )
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.celery_task_id, "test-celery-id")
        self.assertIsNotNone(task.started_at)
        self.assertIsNotNone(task.completed_at)

    def test_updates_document_fields(self) -> None:
        """Document.processing_status, extracted_text_length should be updated."""
        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "pending")

        self._run_task()
        self.document.refresh_from_db()

        # The task sets processing_status='processing' at start.
        self.assertEqual(self.document.processing_status, "processing")
        self.assertGreater(self.document.extracted_text_length, 0)
        self.assertEqual(self.document.total_pages, 2)

    # -- Empty PDF --------------------------------------------------------

    def test_empty_pdf_returns_empty_string(self) -> None:
        """A PDF with 0 pages should return an empty string, not an error."""
        empty_pdf_path = os.path.join(self.tmpdir, "empty.pdf")
        _create_empty_pdf(empty_pdf_path)

        self.document.file_path = empty_pdf_path
        self.document.save(update_fields=["file_path"])

        result = self._run_task()
        self.assertEqual(result, "")

        self.document.refresh_from_db()
        self.assertEqual(self.document.extracted_text_length, 0)

    # -- Corrupted PDF ----------------------------------------------------

    def test_corrupted_pdf_sets_failed_status(self) -> None:
        """A corrupted PDF should mark both ProcessingTask and Document as failed."""
        bad_path = os.path.join(self.tmpdir, "corrupted.pdf")
        with open(bad_path, "wb") as f:
            f.write(b"not a real pdf content")

        self.document.file_path = bad_path
        self.document.save(update_fields=["file_path"])

        result = self._run_task()
        self.assertEqual(result, "")

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("corrupted", self.document.processing_error.lower())

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="extract",
        )
        self.assertEqual(task.status, "failed")
        self.assertIn("corrupted", task.error_message.lower())

    # -- Document not found -----------------------------------------------

    def test_nonexistent_document_returns_empty_string(self) -> None:
        """If the document does not exist, return empty string without error."""
        result = extract_text_from_pdf("00000000-0000-0000-0000-000000000000")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# Tests — chunk_document
# ---------------------------------------------------------------------------


class ChunkDocumentTests(TestCase):
    """Tests for the :func:`chunk_document` task."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="chunk@example.com",
            password="testpass123",
        )

        self.document = Document.objects.create(
            user=self.user,
            title="Chunk Test Doc",
            filename="chunk_test.pdf",
            original_filename="chunk_test.pdf",
            file_path="/tmp/fake.pdf",
            file_size=1000,
            mime_type="application/pdf",
            processing_status="processing",
        )

    def _run_task(self, extracted_text: str) -> None:
        """Run chunk_document synchronously with a mock Celery request.

        NOTE: The function signature is chunk_document(self, extracted_text, document_id).
        The Celery chain passes (extracted_text, document_id) — extracted_text comes
        from the return value of extract_text_from_pdf, and document_id is the
        immutable chain argument.
        """
        with _mock_celery_request(chunk_document):
            chunk_document(extracted_text, str(self.document.id))

    # -- Happy path -------------------------------------------------------

    def test_creates_chunks_from_text(self) -> None:
        """Verify that DocumentChunk records are created."""
        text = "[PAGE 1]\n" + "A" * 3000 + "\n[PAGE 2]\n" + "B" * 3000
        self._run_task(text)

        chunks = DocumentChunk.objects.filter(document=self.document).order_by("chunk_index")
        self.assertGreater(len(chunks), 0)

        # Verify chunk structure.
        for chunk in chunks:
            self.assertEqual(chunk.document_id, self.document.id)
            self.assertIsNotNone(chunk.content)
            self.assertIsInstance(chunk.token_count, int)

    def test_creates_chunk_processing_task(self) -> None:
        """A ProcessingTask with task_type='chunk' should be created."""
        text = "[PAGE 1]\nHello world.\n[PAGE 2]\nMore content here."
        self._run_task(text)

        # Verify a "chunk" ProcessingTask was created (not reusing "extract").
        chunk_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="chunk",
        )
        self.assertEqual(chunk_task.status, "completed")
        self.assertEqual(chunk_task.celery_task_id, "test-celery-id")
        self.assertIsNotNone(chunk_task.started_at)
        self.assertIsNotNone(chunk_task.completed_at)

    def test_updates_document_fields(self) -> None:
        """Document.total_chunks and processing_status should be updated."""
        text = "[PAGE 1]\nHello world.\n[PAGE 2]\nMore content here."
        self._run_task(text)

        self.document.refresh_from_db()
        self.assertGreater(self.document.total_chunks, 0)
        self.assertEqual(self.document.processing_status, "completed")

    # -- Empty text -------------------------------------------------------

    def test_empty_text_sets_zero_chunks(self) -> None:
        """Empty extracted text should result in 0 chunks and completed status."""
        self._run_task("")

        self.document.refresh_from_db()
        self.assertEqual(self.document.total_chunks, 0)
        self.assertEqual(self.document.processing_status, "completed")

        # Verify a chunk task was created and marked completed.
        chunk_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="chunk",
        )
        self.assertEqual(chunk_task.status, "completed")

    def test_whitespace_only_text_sets_zero_chunks(self) -> None:
        """Whitespace-only text should be treated as empty."""
        self._run_task("   \n   \t   ")

        self.document.refresh_from_db()
        self.assertEqual(self.document.total_chunks, 0)
        self.assertEqual(self.document.processing_status, "completed")

    # -- Error handling ---------------------------------------------------

    def test_exception_sets_failed_status(self) -> None:
        """If chunking raises, both Document and ProcessingTask should be failed."""
        with patch.object(
            ChunkingService, "chunk_text", side_effect=ValueError("Simulated failure")
        ):
            self._run_task("[PAGE 1]\nSome text.")

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("Simulated failure", self.document.processing_error)

        # Verify the chunk task was marked as failed.
        chunk_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="chunk",
        )
        self.assertEqual(chunk_task.status, "failed")
        self.assertIn("Simulated failure", chunk_task.error_message)

    # -- Document not found -----------------------------------------------

    def test_nonexistent_document_does_not_raise(self) -> None:
        """If the document does not exist, the task should return gracefully."""
        # Should not raise.
        chunk_document("some text", "00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# Tests — process_document (orchestration)
# ---------------------------------------------------------------------------
# NOTE: process_document is now a regular Python function (not a Celery task).
# It is called directly and returns the Celery chain's task ID.


class ProcessDocumentTests(TestCase):
    """Tests for the :func:`process_document` orchestration function."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="orchestrate@example.com",
            password="testpass123",
        )

        self.document = Document.objects.create(
            user=self.user,
            title="Orchestration Test",
            filename="orch_test.pdf",
            original_filename="orch_test.pdf",
            file_path="/tmp/fake.pdf",
            file_size=500,
            mime_type="application/pdf",
            processing_status="pending",
        )

    def test_creates_pending_processing_task(self) -> None:
        """A ProcessingTask with status='pending' should be created."""
        with patch("documents.tasks.document_processing.chain") as mock_chain:
            mock_result = MagicMock()
            mock_result.id = "chain-celery-id-001"
            mock_chain_obj = MagicMock()
            mock_chain_obj.apply_async.return_value = mock_result
            mock_chain.return_value = mock_chain_obj

            process_document(str(self.document.id))

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="extract",
        )
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.celery_task_id, "chain-celery-id-001")

    def test_returns_celery_task_id(self) -> None:
        """The function should return the Celery task ID."""
        with patch("documents.tasks.document_processing.chain") as mock_chain:
            mock_result = MagicMock()
            mock_result.id = "chain-celery-id-002"
            mock_chain_obj = MagicMock()
            mock_chain_obj.apply_async.return_value = mock_result
            mock_chain.return_value = mock_chain_obj

            task_id = process_document(str(self.document.id))
            self.assertEqual(task_id, "chain-celery-id-002")

    def test_builds_celery_chain(self) -> None:
        """Verify that chain() is called with the correct tasks."""
        with patch("documents.tasks.document_processing.chain") as mock_chain:
            mock_result = MagicMock()
            mock_result.id = "chain-celery-id-003"
            mock_chain_obj = MagicMock()
            mock_chain_obj.apply_async.return_value = mock_result
            mock_chain.return_value = mock_chain_obj

            process_document(str(self.document.id))

            # Verify chain was built with the two task signatures.
            mock_chain.assert_called_once()
            args, _ = mock_chain.call_args
            self.assertEqual(len(args), 2)

    def test_skips_if_already_processing(self) -> None:
        """If processing_status is 'processing', the task should return None."""
        self.document.processing_status = "processing"
        self.document.save(update_fields=["processing_status"])

        result = process_document(str(self.document.id))
        self.assertIsNone(result)

    def test_skips_if_already_completed(self) -> None:
        """If processing_status is 'completed', the task should return None."""
        self.document.processing_status = "completed"
        self.document.save(update_fields=["processing_status"])

        result = process_document(str(self.document.id))
        self.assertIsNone(result)

    def test_nonexistent_document_returns_none(self) -> None:
        """If the document does not exist, return None."""
        result = process_document("00000000-0000-0000-0000-000000000000")
        self.assertIsNone(result)
