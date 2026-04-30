"""
Tests for the document processing Celery tasks.

Covers:
- :func:`~documents.tasks.document_processing.extract_text_from_pdf`
- :func:`~documents.tasks.document_processing.chunk_document`
- :func:`~documents.tasks.document_processing.process_document`
- :func:`~documents.tasks.embedding_tasks.embed_document`
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import MagicMock, PropertyMock, patch

import fitz
from celery.exceptions import SoftTimeLimitExceeded
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from documents.models import Document, DocumentChunk
from documents.services.chunking_service import ChunkingService
from documents.tasks import process_document  # re-exported from services module
from documents.tasks.document_processing import (
    _handle_chain_error,
    chunk_document,
    extract_text_from_pdf,
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
        """Document.extracted_text_length and total_pages should be updated."""
        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "pending")

        self._run_task()
        self.document.refresh_from_db()

        # Extraction no longer sets processing_status to "completed" —
        # that responsibility belongs to chunk_document. The status remains
        # "processing" (set by process_document before the chain starts).
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
        # Write a file that starts with %PDF magic bytes but is not a valid PDF
        # (so the magic bytes check passes, but fitz.open raises FileDataError).
        with open(bad_path, "wb") as f:
            f.write(b"%PDF-1.4\n%%... garbage after header that is not a valid PDF")

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

    # -- Password-protected PDF -------------------------------------------

    def test_password_protected_pdf_sets_failed_status(self) -> None:
        """A password-protected PDF should mark both ProcessingTask and Document as failed."""
        bad_path = os.path.join(self.tmpdir, "protected.pdf")
        # Write a valid PDF header so the magic bytes check passes.
        with open(bad_path, "wb") as f:
            f.write(b"%PDF-1.4\n%%...")

        self.document.file_path = bad_path
        self.document.save(update_fields=["file_path"])

        # Mock fitz.open to raise an exception with "password" in the message.
        with patch.object(fitz, "open", side_effect=Exception("requires a password")):
            result = self._run_task()

        self.assertEqual(result, "")

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("password-protected", self.document.processing_error.lower())

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="extract",
        )
        self.assertEqual(task.status, "failed")
        self.assertIn("password-protected", task.error_message.lower())

    # -- Non-PDF file -----------------------------------------------------

    def test_non_pdf_file_sets_failed_status(self) -> None:
        """A non-PDF file uploaded with .pdf extension should be detected and failed."""
        bad_path = os.path.join(self.tmpdir, "fake.pdf")
        # Write a file that does NOT start with %PDF magic bytes.
        with open(bad_path, "wb") as f:
            f.write(b"not a pdf")

        self.document.file_path = bad_path
        self.document.save(update_fields=["file_path"])

        result = self._run_task()
        self.assertEqual(result, "")

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("not a valid pdf", self.document.processing_error.lower())

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="extract",
        )
        self.assertEqual(task.status, "failed")
        self.assertIn("not a valid pdf", task.error_message.lower())

    # -- Celery task timeout ----------------------------------------------

    def test_celery_task_timeout_behavior(self) -> None:
        """A SoftTimeLimitExceeded during extraction should mark the task as failed."""
        bad_path = os.path.join(self.tmpdir, "timeout.pdf")
        # Write a valid PDF header so the magic bytes check passes.
        with open(bad_path, "wb") as f:
            f.write(b"%PDF-1.4\n%%...")

        self.document.file_path = bad_path
        self.document.save(update_fields=["file_path"])

        # Mock fitz.open to raise SoftTimeLimitExceeded.
        with patch.object(fitz, "open", side_effect=SoftTimeLimitExceeded()):
            result = self._run_task()

        self.assertEqual(result, "")

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("timed out", self.document.processing_error.lower())

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="extract",
        )
        self.assertEqual(task.status, "failed")
        self.assertIn("timed out", task.error_message.lower())


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

    # -- Bug #2 protection: chunk_document must not overwrite "failed" status --

    def test_does_not_overwrite_failed_status_on_empty_text(self) -> None:
        """If document is already 'failed', chunk_document must not overwrite to 'completed'."""
        # Simulate a document that was already marked as failed by extraction.
        self.document.processing_status = "failed"
        self.document.processing_error = "PDF file is corrupted or unreadable"
        self.document.save(update_fields=["processing_status", "processing_error"])

        # Run chunk_document with empty text (as would happen after a failed extract).
        self._run_task("")

        self.document.refresh_from_db()
        # processing_status must remain "failed", not be overwritten to "completed".
        self.assertEqual(self.document.processing_status, "failed")
        self.assertEqual(self.document.processing_error, "PDF file is corrupted or unreadable")

        # No chunk ProcessingTask should be created — we skip entirely when
        # the document is already in a failed state.
        chunk_task_exists = ProcessingTask.objects.filter(
            document=self.document,
            task_type="chunk",
        ).exists()
        self.assertFalse(chunk_task_exists)

    def test_does_not_overwrite_failed_status_on_successful_chunking(self) -> None:
        """If document is already 'failed', chunk_document must not overwrite even on success."""
        self.document.processing_status = "failed"
        self.document.processing_error = "Previous error"
        self.document.save(update_fields=["processing_status", "processing_error"])

        # Run chunk_document with valid text (would succeed normally).
        self._run_task("[PAGE 1]\nSome text here.")

        self.document.refresh_from_db()
        # Must remain "failed" — we skip entirely when the document is already failed.
        self.assertEqual(self.document.processing_status, "failed")
        self.assertEqual(self.document.processing_error, "Previous error")

        # No chunk ProcessingTask should be created.
        chunk_task_exists = ProcessingTask.objects.filter(
            document=self.document,
            task_type="chunk",
        ).exists()
        self.assertFalse(chunk_task_exists)

    # -- Test Gap #1: extract-success + chunk-failure scenario (Bug #1) --

    def test_extract_success_then_chunk_failure_sets_failed_status(self) -> None:
        """If extraction succeeds but chunking fails, document should be 'failed', not 'processing'."""
        # First, simulate a successful extraction by setting processing_status to "completed".
        self.document.processing_status = "completed"
        self.document.total_chunks = 0
        self.document.save(update_fields=["processing_status", "total_chunks"])

        # Now run chunk_document with a mocked ChunkingService that raises.
        with patch.object(
            ChunkingService, "chunk_text", side_effect=ValueError("Chunking failed")
        ):
            self._run_task("[PAGE 1]\nSome text to chunk.")

        self.document.refresh_from_db()
        # The document should be "failed", not stuck at "processing" or "completed".
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("Chunking failed", self.document.processing_error)

        # The chunk task should be marked as failed.
        chunk_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="chunk",
        )
        self.assertEqual(chunk_task.status, "failed")
        self.assertIn("Chunking failed", chunk_task.error_message)

    # -- Document not found -----------------------------------------------

    def test_nonexistent_document_does_not_raise(self) -> None:
        """If the document does not exist, the task should return gracefully."""
        # Should not raise.
        chunk_document("some text", "00000000-0000-0000-0000-000000000000")

    # -- Database error during chunk insert -------------------------------

    def test_database_error_during_chunk_insert(self) -> None:
        """An IntegrityError during bulk_create should mark the task as failed."""
        text = "[PAGE 1]\nSome text to chunk."

        with patch.object(
            DocumentChunk.objects, "bulk_create",
            side_effect=IntegrityError("duplicate key value violates unique constraint"),
        ):
            self._run_task(text)

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("Database error during chunking", self.document.processing_error)

        chunk_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="chunk",
        )
        self.assertEqual(chunk_task.status, "failed")
        self.assertIn("Database error during chunking", chunk_task.error_message)


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
        with patch("documents.services.processing_service.chain") as mock_chain:
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
        with patch("documents.services.processing_service.chain") as mock_chain:
            mock_result = MagicMock()
            mock_result.id = "chain-celery-id-002"
            mock_chain_obj = MagicMock()
            mock_chain_obj.apply_async.return_value = mock_result
            mock_chain.return_value = mock_chain_obj

            task_id = process_document(str(self.document.id))
            self.assertEqual(task_id, "chain-celery-id-002")

    def test_builds_celery_chain(self) -> None:
        """Verify that chain() is called with the correct tasks."""
        with patch("documents.services.processing_service.chain") as mock_chain:
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

    def test_passes_link_error_to_apply_async(self) -> None:
        """The chain should be submitted with a link_error callback."""
        with patch("documents.services.processing_service.chain") as mock_chain:
            mock_result = MagicMock()
            mock_result.id = "chain-celery-id-link-error"
            mock_chain_obj = MagicMock()
            mock_chain_obj.apply_async.return_value = mock_result
            mock_chain.return_value = mock_chain_obj

            process_document(str(self.document.id))

            # Verify apply_async was called with link_error.
            mock_chain_obj.apply_async.assert_called_once()
            _call_kwargs = mock_chain_obj.apply_async.call_args.kwargs
            self.assertIn("link_error", _call_kwargs)
            self.assertEqual(len(_call_kwargs["link_error"]), 1)


# ---------------------------------------------------------------------------
# Tests — _handle_chain_error (link_error callback)
# ---------------------------------------------------------------------------


class HandleChainErrorTests(TestCase):
    """Tests for the :func:`_handle_chain_error` error callback."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="chain-error@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Chain Error Test",
            filename="chain_error.pdf",
            original_filename="chain_error.pdf",
            file_path="/tmp/fake.pdf",
            file_size=500,
            mime_type="application/pdf",
            processing_status="processing",
        )

    def _run_callback(self, document_id: str | None = None, task_type: str = "extract") -> None:
        """Run _handle_chain_error synchronously with a mock Celery request."""
        with _mock_celery_request(_handle_chain_error):
            _handle_chain_error(document_id or str(self.document.id), task_type=task_type)

    def test_marks_pending_task_as_failed(self) -> None:
        """A pending ProcessingTask should be marked as failed."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            status="pending",
        )
        self._run_callback()

        task = ProcessingTask.objects.get(document=self.document, task_type="extract")
        self.assertEqual(task.status, "failed")
        self.assertIsNotNone(task.completed_at)
        self.assertIn("Chain-level failure", task.error_message)

    def test_marks_running_task_as_failed(self) -> None:
        """A running ProcessingTask should be marked as failed."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            status="running",
            started_at=timezone.now(),
        )
        self._run_callback()

        task = ProcessingTask.objects.get(document=self.document, task_type="extract")
        self.assertEqual(task.status, "failed")

    def test_marks_document_as_failed(self) -> None:
        """The document should be marked as failed if not already terminal."""
        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            status="pending",
        )
        self._run_callback()

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn("Chain-level failure", self.document.processing_error)

    def test_does_not_overwrite_terminal_document_status(self) -> None:
        """If document is already 'completed', _handle_chain_error should not change it."""
        self.document.processing_status = "completed"
        self.document.save(update_fields=["processing_status"])

        ProcessingTask.objects.create(
            document=self.document,
            task_type="extract",
            status="pending",
        )
        self._run_callback()

        self.document.refresh_from_db()
        self.assertEqual(self.document.processing_status, "completed")

    def test_nonexistent_document_does_not_raise(self) -> None:
        """If the document does not exist, the callback should return gracefully."""
        # Should not raise.
        self._run_callback(document_id="00000000-0000-0000-0000-000000000000")


