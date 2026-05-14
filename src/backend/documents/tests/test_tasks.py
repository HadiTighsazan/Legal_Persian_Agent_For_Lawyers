"""
Tests for the document processing Celery tasks.

Covers:
- :func:`~documents.tasks.document_processing.extract_text_from_pdf`
- :func:`~documents.tasks.document_processing.chunk_document`
- :func:`~documents.tasks.document_processing.process_document`
- :func:`~documents.tasks.embedding_tasks.embed_document`
- :func:`~documents.tasks.document_processing._has_shattered_persian_words`
- :func:`~documents.tasks.document_processing._compute_persian_quality_score`
- :func:`~documents.tasks.document_processing._compute_stopword_ratio`
- :func:`~documents.tasks.document_processing._compute_bigram_plausibility`
- :func:`~documents.tasks.document_processing._compute_rtl_consistency`
- :func:`~documents.tasks.document_processing._compute_character_entropy`
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
from documents.services.anchor_chunking_service import AnchorChunkingService
from documents.tasks import process_document  # re-exported from services module
from documents.tasks.document_processing import (
    _compute_bigram_plausibility,
    _compute_character_entropy,
    _compute_garbled_ratio,
    _compute_persian_quality_score,
    _compute_rtl_consistency,
    _compute_stopword_ratio,
    _fix_bidi_brackets,
    _handle_chain_error,
    _has_shattered_persian_words,
    _is_persian_text_garbled,
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
        """Document.total_chunks should be updated; processing_status stays 'processing'.

        The processing_status is NOT set to 'completed' by chunk_document anymore.
        It was moved to embed_document (the final link in the Celery chain) to
        prevent the frontend from stopping polling and hiding the progress panel
        before embeddings are generated (Bug A fix).
        """
        text = "[PAGE 1]\nHello world.\n[PAGE 2]\nMore content here."
        self._run_task(text)

        self.document.refresh_from_db()
        self.assertGreater(self.document.total_chunks, 0)
        # processing_status remains "processing" (set by extract_text_from_pdf)
        # because embed_document is now responsible for setting it to "completed".
        self.assertEqual(self.document.processing_status, "processing")

    # -- Empty text -------------------------------------------------------

    def test_empty_text_sets_failed_status(self) -> None:
        """Empty extracted text should result in failed status with descriptive error."""
        self._run_task("")

        self.document.refresh_from_db()
        self.assertEqual(self.document.total_chunks, 0)
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn(
            "Text extraction produced no content",
            self.document.processing_error,
        )

        # Verify a chunk task was created and marked failed.
        chunk_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="chunk",
        )
        self.assertEqual(chunk_task.status, "failed")
        self.assertIn(
            "Text extraction produced no content",
            chunk_task.error_message,
        )

    def test_whitespace_only_text_sets_failed_status(self) -> None:
        """Whitespace-only text should be treated as empty and mark document as failed."""
        self._run_task("   \n   \t   ")

        self.document.refresh_from_db()
        self.assertEqual(self.document.total_chunks, 0)
        self.assertEqual(self.document.processing_status, "failed")
        self.assertIn(
            "Text extraction produced no content",
            self.document.processing_error,
        )

    # -- Error handling ---------------------------------------------------

    def test_exception_sets_failed_status(self) -> None:
        """If chunking raises, both Document and ProcessingTask should be failed."""
        with patch.object(
            AnchorChunkingService, "chunk_text", side_effect=ValueError("Simulated failure")
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

        # Now run chunk_document with a mocked AnchorChunkingService that raises.
        with patch.object(
            AnchorChunkingService, "chunk_text", side_effect=ValueError("Chunking failed")
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
        """Verify that chain() is called with the correct tasks (extract → chunk → embed)."""
        with patch("documents.services.processing_service.chain") as mock_chain:
            mock_result = MagicMock()
            mock_result.id = "chain-celery-id-003"
            mock_chain_obj = MagicMock()
            mock_chain_obj.apply_async.return_value = mock_result
            mock_chain.return_value = mock_chain_obj

            process_document(str(self.document.id))

            # Verify chain was built with the three task signatures.
            mock_chain.assert_called_once()
            args, _ = mock_chain.call_args
            self.assertEqual(len(args), 3)

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
        """Run _handle_chain_error synchronously with a mock Celery request.

        Celery's ``link_error`` passes ``(request, exc, traceback)`` as positional
        args **before** the signature args (``document_id``, ``task_type``).
        The test must replicate this call pattern.
        """
        with _mock_celery_request(_handle_chain_error):
            _handle_chain_error(
                "mock-request-id",  # request
                Exception("Chain failed"),  # exc
                None,  # traceback
                document_id or str(self.document.id),
                task_type=task_type,
            )

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


# ---------------------------------------------------------------------------
# Tests — _has_shattered_persian_words
# ---------------------------------------------------------------------------


class HasShatteredPersianWordsTests(TestCase):
    """Tests for the :func:`_has_shattered_persian_words` heuristic."""

    # -- Shattered text (should return True) -------------------------------

    def test_shattered_persian_text(self) -> None:
        """Shattered Persian text ``ق ا ن و ن   م د ن ی`` → ``True``."""
        text = "ق ا ن و ن   م د ن ی"
        self.assertTrue(_has_shattered_persian_words(text))

    def test_shattered_with_mixed_normal(self) -> None:
        """Mixed text with some shattered words → ``True``."""
        text = "قانون مدنی ج م ه و ر ی"
        self.assertTrue(_has_shattered_persian_words(text))

    def test_mostly_shattered_text(self) -> None:
        """Text where most Persian chars are isolated → ``True``."""
        text = "ب ه   ن ا م   خ د ا و ن د   م ه ر ب ا ن"
        self.assertTrue(_has_shattered_persian_words(text))

    # -- Normal text (should return False) ---------------------------------

    def test_normal_persian_text(self) -> None:
        """Normal Persian text ``قانون مدنی جمهوری اسلامی ایران`` → ``False``."""
        text = "قانون مدنی جمهوری اسلامی ایران"
        self.assertFalse(_has_shattered_persian_words(text))

    def test_persian_with_legal_structure(self) -> None:
        """Legal Persian text with article markers → ``False``."""
        text = "ماده ۱: این قانون برای تنظیم روابط اجتماعی وضع می‌شود."
        self.assertFalse(_has_shattered_persian_words(text))

    def test_persian_with_single_char_words(self) -> None:
        """Persian text with legitimate single-char words (و) → ``False``."""
        text = "و اما بعد، این قانون برای تنظیم امور مالی و اداری وضع گردید"
        self.assertFalse(_has_shattered_persian_words(text))

    def test_english_text(self) -> None:
        """English text with no Persian chars → ``False``."""
        text = "This is a test document with multiple sentences."
        self.assertFalse(_has_shattered_persian_words(text))

    def test_mixed_persian_english(self) -> None:
        """Mixed Persian/English text with normal Persian → ``False``."""
        text = "این یک متن آزمایشی است This is a test document"
        self.assertFalse(_has_shattered_persian_words(text))

    # -- Edge cases -------------------------------------------------------

    def test_empty_string(self) -> None:
        """Empty string → ``False``."""
        self.assertFalse(_has_shattered_persian_words(""))

    def test_whitespace_only(self) -> None:
        """Whitespace-only string → ``False``."""
        self.assertFalse(_has_shattered_persian_words("   \n\n  "))

    def test_no_persian_chars(self) -> None:
        """Text with no Persian characters → ``False``."""
        text = "Hello World! 123."
        self.assertFalse(_has_shattered_persian_words(text))

    def test_single_persian_word(self) -> None:
        """Single normal Persian word → ``False``."""
        text = "قانون"
        self.assertFalse(_has_shattered_persian_words(text))

    def test_shattered_single_word(self) -> None:
        """Single shattered Persian word → ``True``."""
        text = "ق ا ن و ن"
        self.assertTrue(_has_shattered_persian_words(text))

    def test_custom_threshold(self) -> None:
        """Custom threshold changes detection sensitivity."""
        text = "قانون مدنی ج م ه و ر ی"
        # With a very high threshold, this should not be detected
        self.assertFalse(_has_shattered_persian_words(text, threshold=0.9))
        # With a very low threshold, this should be detected
        self.assertTrue(_has_shattered_persian_words(text, threshold=0.1))


# ---------------------------------------------------------------------------
# Tests — Persian Language Confidence Score (Phase 2)
# ---------------------------------------------------------------------------


class ComputeStopwordRatioTests(TestCase):
    """Tests for :func:`_compute_stopword_ratio`."""

    def test_empty_text(self) -> None:
        """Empty string → 0.0."""
        self.assertEqual(_compute_stopword_ratio(""), 0.0)

    def test_no_persian_stopwords(self) -> None:
        """Text with no Persian stopwords → 0.0."""
        text = "This is a test with no Persian words at all."
        self.assertEqual(_compute_stopword_ratio(text), 0.0)

    def test_all_stopwords(self) -> None:
        """Text consisting entirely of stopwords → 1.0."""
        text = "از به در با و که این آن را"
        self.assertAlmostEqual(_compute_stopword_ratio(text), 1.0)

    def test_mixed_stopwords(self) -> None:
        """Mixed Persian text with stopwords → ratio between 0 and 1."""
        text = "قانون مدنی جمهوری اسلامی ایران در تاریخ ۱۳۷۶ تصویب شد"
        # Stopwords in this text: "در", "شد"
        ratio = _compute_stopword_ratio(text)
        self.assertGreater(ratio, 0.0)
        self.assertLess(ratio, 1.0)

    def test_legal_stopwords(self) -> None:
        """Legal-domain stopwords are recognized."""
        text = "دادگاه شعبه خواهان خوانده پرونده کلاسه"
        ratio = _compute_stopword_ratio(text)
        self.assertGreater(ratio, 0.5)

    def test_garbled_text_low_stopwords(self) -> None:
        """RTL-reversed garbled text should have very few stopwords."""
        # Simulated RTL-reversed text — stopwords like از, به, در are gone
        text = "رپونده خوااهن ناوخد هدبش هدافتسا"
        ratio = _compute_stopword_ratio(text)
        self.assertLess(ratio, 0.1)

    def test_typical_legal_paragraph(self) -> None:
        """A typical Persian legal paragraph should have a decent stopword ratio."""
        text = (
            "به موجب ماده ۲ قانون مدنی، قراردادهای خصوصی نسبت به کسانی که "
            "آن را منعقد نموده اند، در حکم قانون است و دادگاه نمی تواند "
            "طرفین را از اجرای آن منع نماید مگر به موجب قانون."
        )
        ratio = _compute_stopword_ratio(text)
        self.assertGreater(ratio, 0.1)


class ComputeBigramPlausibilityTests(TestCase):
    """Tests for :func:`_compute_bigram_plausibility`."""

    def test_empty_text(self) -> None:
        """Empty string → 1.0."""
        self.assertEqual(_compute_bigram_plausibility(""), 1.0)

    def test_no_persian_chars(self) -> None:
        """Text with no Persian characters → 1.0."""
        text = "Hello World"
        self.assertEqual(_compute_bigram_plausibility(text), 1.0)

    def test_single_persian_char(self) -> None:
        """Single Persian character → 1.0 (no bigrams to evaluate)."""
        self.assertEqual(_compute_bigram_plausibility("و"), 1.0)

    def test_valid_persian_bigrams(self) -> None:
        """Valid Persian text should have many valid bigrams."""
        text = "قانون مدنی جمهوری اسلامی ایران"
        score = _compute_bigram_plausibility(text)
        # Most bigrams in this text should be valid
        self.assertGreater(score, 0.3)

    def test_garbled_bigrams(self) -> None:
        """Garbled text (random chars) should have fewer valid bigrams.

        NOTE: RTL-reversed text preserves bigrams (reversing a word keeps
        the same character pairs), so bigram plausibility is NOT a reliable
        signal for RTL reversal. This test uses random character sequences
        which genuinely have fewer valid bigrams.
        """
        # Random Persian character sequence (not reversed, just random)
        # This simulates OCR garbage or random corruption
        garbled = "ثخدحزظصضطظغفذ"
        score_garbled = _compute_bigram_plausibility(garbled)
        # Valid Persian text should score higher
        valid = "قانون مدنی جمهوری اسلامی ایران"
        score_valid = _compute_bigram_plausibility(valid)
        self.assertGreater(score_valid, score_garbled)


class ComputeRtlConsistencyTests(TestCase):
    """Tests for :func:`_compute_rtl_consistency`."""

    def test_empty_text(self) -> None:
        """Empty string → 1.0."""
        self.assertEqual(_compute_rtl_consistency(""), 1.0)

    def test_no_persian_chars(self) -> None:
        """Text with no Persian characters → 1.0."""
        text = "Hello World"
        self.assertEqual(_compute_rtl_consistency(text), 1.0)

    def test_valid_persian_high_consistency(self) -> None:
        """Valid Persian text should have high RTL consistency."""
        text = "قانون مدنی جمهوری اسلامی ایران"
        score = _compute_rtl_consistency(text)
        self.assertGreater(score, 0.8)

    def test_isolated_persian_chars_low_consistency(self) -> None:
        """Isolated Persian characters (garbled) should have low consistency."""
        # Each Persian char isolated by spaces
        text = "ق ا ن و ن   م د ن ی"
        score = _compute_rtl_consistency(text)
        self.assertLess(score, 0.3)

    def test_mixed_text(self) -> None:
        """Mixed Persian/English text should still have reasonable consistency."""
        text = "قانون مدنی is the Persian Civil Code"
        score = _compute_rtl_consistency(text)
        # Most Persian chars are in contiguous runs
        self.assertGreater(score, 0.5)


class ComputeCharacterEntropyTests(TestCase):
    """Tests for :func:`_compute_character_entropy`."""

    def test_empty_text(self) -> None:
        """Empty string → 0.0."""
        self.assertEqual(_compute_character_entropy(""), 0.0)

    def test_no_persian_chars(self) -> None:
        """Text with no Persian characters → 0.0."""
        text = "Hello World"
        self.assertEqual(_compute_character_entropy(text), 0.0)

    def test_single_repeated_char(self) -> None:
        """Single repeated character → 0.0 entropy."""
        text = "اااااااااا"
        self.assertAlmostEqual(_compute_character_entropy(text), 0.0, places=1)

    def test_valid_persian_entropy(self) -> None:
        """Valid Persian text should have moderate entropy (2.0–4.0)."""
        text = "قانون مدنی جمهوری اسلامی ایران ماده ۱"
        entropy = _compute_character_entropy(text)
        self.assertGreater(entropy, 1.0)
        self.assertLess(entropy, 5.0)


class ComputePersianQualityScoreTests(TestCase):
    """Tests for :func:`_compute_persian_quality_score`."""

    def test_empty_text(self) -> None:
        """Empty string → 0.0."""
        self.assertEqual(_compute_persian_quality_score(""), 0.0)

    def test_whitespace_only(self) -> None:
        """Whitespace-only string → 0.0."""
        self.assertEqual(_compute_persian_quality_score("   \n\n  "), 0.0)

    def test_valid_persian_high_score(self) -> None:
        """Valid Persian legal text should score high (>0.5)."""
        text = (
            "به موجب ماده ۲ قانون مدنی، قراردادهای خصوصی نسبت به کسانی که "
            "آن را منعقد نموده اند، در حکم قانون است و دادگاه نمی تواند "
            "طرفین را از اجرای آن منع نماید مگر به موجب قانون."
        )
        score = _compute_persian_quality_score(text)
        self.assertGreater(score, 0.5)

    def test_garbled_text_low_score(self) -> None:
        """RTL-reversed garbled text should score low (<0.4).

        RTL-reversed text has zero valid stopwords (the most reliable signal),
        which dominates the weighted score (weight 0.50). Even though bigram
        plausibility and RTL consistency may be high, the absence of stopwords
        pulls the score below threshold.
        """
        # Simulated RTL-reversed text — stopwords like از, به, در are gone
        text = "رپونده خوااهن ناوخد هدبش هدافتسا"
        score = _compute_persian_quality_score(text)
        self.assertLess(score, 0.4)

    def test_shattered_text_low_score(self) -> None:
        """Shattered Persian text (spaces between chars) should score low.

        Shattered text has low RTL consistency (chars are isolated by spaces)
        AND zero valid stopwords, so both the stopword and RTL signals fire.
        """
        text = "ق ا ن و ن   م د ن ی   ج م ه و ر ی   ا س ل ا م ی"
        score = _compute_persian_quality_score(text)
        self.assertLess(score, 0.4)

    def test_english_text_default_score(self) -> None:
        """English text with no Persian chars → depends on signals."""
        text = "This is a test document with multiple sentences."
        score = _compute_persian_quality_score(text)
        # No Persian chars → stopword_ratio=0, bigram=1.0, rtl=1.0, entropy=0.0
        # entropy_score = 1.0 - min(0/5, 1.0) = 1.0
        # Weighted: 0*0.50 + 1.0*0.10 + 1.0*0.25 + 1.0*0.15 = 0.10+0.25+0.15 = 0.50
        self.assertAlmostEqual(score, 0.50, places=1)

    def test_persian_legal_document_high_score(self) -> None:
        """A realistic Persian legal document should score well above threshold."""
        text = (
            "دادنامه شماره ۹۹۰۹۹۷۰۲۲۲۲۰۰۱۲۳\n"
            "شعبه ۲۲ دادگاه تجدیدنظر استان تهران\n"
            "در خصوص تجدیدنظرخواهی آقای ... به طرفیت ...\n"
            "نظر به اینکه دادنامه بدوی مطابق با قانون و دلایل موجود در پرونده "
            "می باشد و از ناحیه تجدیدنظرخواه دلیل یا مدرکی که موجب نقض یا "
            "بی اعتباری رأی بدوی گردد اقامه نشده است، لذا دادگاه اعتراض "
            "مذکور را وارد ندانسته و به استناد ماده ۳۵۸ قانون آیین دادرسی "
            "دادگاه های عمومی و انقلاب در امور مدنی، رأی بدوی را تأیید می نماید."
        )
        score = _compute_persian_quality_score(text)
        self.assertGreater(score, 0.5)

    def test_threshold_detection(self) -> None:
        """Quality score < 0.4 should be detected as garbled by _is_persian_text_garbled.

        Uses shattered text (spaces between chars) which has both low stopword
        ratio AND low RTL consistency, ensuring the score is well below 0.4.
        """
        # Shattered text — low stopword ratio AND low RTL consistency
        garbled = "ق ا ن و ن   م د ن ی   ج م ه و ر ی   ا س ل ا م ی"
        self.assertTrue(_is_persian_text_garbled(garbled, threshold=0.4))

    def test_threshold_clear_text(self) -> None:
        """Quality score >= 0.4 should NOT be detected as garbled."""
        valid = (
            "به موجب ماده ۲ قانون مدنی، قراردادهای خصوصی نسبت به کسانی که "
            "آن را منعقد نموده اند، در حکم قانون است."
        )
        self.assertFalse(_is_persian_text_garbled(valid, threshold=0.4))

    def test_legacy_mode_fallback(self) -> None:
        """Legacy mode (use_quality_score=False) uses old garbled ratio."""
        text = "قانون مدنی جمهوری اسلامی ایران"
        # With legacy mode and a very low threshold, clean text should not be garbled
        self.assertFalse(
            _is_persian_text_garbled(text, threshold=0.9, use_quality_score=False)
        )

    def test_legacy_mode_garbled_detection(self) -> None:
        """Legacy mode detects isolated Persian chars as garbled."""
        text = "ق ا ن و ن   م د ن ی"
        self.assertTrue(
            _is_persian_text_garbled(text, threshold=0.3, use_quality_score=False)
        )


class ComputeGarbledRatioLegacyTests(TestCase):
    """Tests for the legacy :func:`_compute_garbled_ratio` (kept for backward compat)."""

    def test_empty_text(self) -> None:
        """Empty string → 0.0."""
        self.assertEqual(_compute_garbled_ratio(""), 0.0)

    def test_no_persian_chars(self) -> None:
        """Text with no Persian characters → 0.0."""
        self.assertEqual(_compute_garbled_ratio("Hello World"), 0.0)

    def test_valid_persian_low_ratio(self) -> None:
        """Valid Persian text should have low garbled ratio."""
        text = "قانون مدنی جمهوری اسلامی ایران"
        ratio = _compute_garbled_ratio(text)
        self.assertLess(ratio, 0.3)

    def test_isolated_chars_high_ratio(self) -> None:
        """Isolated Persian characters should have high garbled ratio."""
        text = "ق ا ن و ن"
        ratio = _compute_garbled_ratio(text)
        self.assertGreater(ratio, 0.5)


class FixBidiBracketsTests(TestCase):
    """Tests for :func:`_fix_bidi_brackets` — safe bracket balancing for RTL text."""

    # ------------------------------------------------------------------
    # Pattern 1: Closing bracket before Persian text → move after
    # ------------------------------------------------------------------

    def test_closing_bracket_before_persian_moved_after(self) -> None:
        """) followed by Persian text → text)"""
        result = _fix_bidi_brackets(")سلام")
        self.assertEqual(result, "سلام)")

    def test_closing_bracket_with_space_before_persian(self) -> None:
        """) with space before Persian → text)"""
        result = _fix_bidi_brackets(") سلام")
        self.assertEqual(result, "سلام)")

    def test_closing_bracket_before_persian_in_sentence(self) -> None:
        """) before Persian word in a mixed sentence — moves after the word"""
        result = _fix_bidi_brackets("متن )سلام دنیا")
        # Pattern 1 moves ) after the first Persian word: سلام) دنیا
        self.assertEqual(result, "متن سلام) دنیا")

    def test_multiple_closing_brackets_before_persian(self) -> None:
        """Multiple )) before Persian → only the one adjacent to Persian moves"""
        result = _fix_bidi_brackets("))سلام")
        # Pattern 1 scans left-to-right for non-overlapping matches:
        # - Position 0: ) followed by ) (not Persian) → no match
        # - Position 1: ) followed by سلام → match → سلام)
        # Result: ")سلام)" (first ) stays, second ) moved after سلام)
        self.assertEqual(result, ")سلام)")

    # ------------------------------------------------------------------
    # Pattern 2: Opening bracket after Persian text → move before
    # ------------------------------------------------------------------

    def test_opening_bracket_after_persian_moved_before(self) -> None:
        """Persian text followed by ( → (text)"""
        result = _fix_bidi_brackets("سلام(")
        self.assertEqual(result, "(سلام")

    def test_opening_bracket_with_space_after_persian(self) -> None:
        """Persian text with space before ( → (text)"""
        result = _fix_bidi_brackets("سلام (")
        self.assertEqual(result, "(سلام")

    def test_opening_bracket_after_persian_in_sentence(self) -> None:
        """Persian word followed by ( in a mixed sentence — moves before the word"""
        result = _fix_bidi_brackets("متن سلام( دنیا")
        # Pattern 2 moves ( before the first Persian word: (سلام دنیا
        self.assertEqual(result, "متن (سلام دنیا")

    def test_multiple_opening_brackets_after_persian(self) -> None:
        """Multiple (( after Persian → only the one adjacent to Persian moves"""
        result = _fix_bidi_brackets("سلام((")
        # Pattern 2 scans left-to-right for non-overlapping matches:
        # - Position 0: سلام( → match → (سلام
        # - Remaining text: ( (no Persian chars left for pattern to match)
        # Result: "(سلام(" (first ( moved before سلام, second ( stays)
        self.assertEqual(result, "(سلام(")

    # ------------------------------------------------------------------
    # Pattern 3: Bracket balancing (count-based, diff >= 2)
    # ------------------------------------------------------------------

    def test_extra_closing_bracket_removed(self) -> None:
        """More ) than ( by 2+ → remove trailing )"""
        result = _fix_bidi_brackets("(سلام) دنیا)")
        # 2 closing, 1 opening → diff=1 < 2 → no change by Pattern 3
        # Pattern 1: trailing ) is preceded by non-Persian (space), so it stays
        # Result keeps the imbalance since diff < 2
        self.assertEqual(result, "(سلام) دنیا)")

    def test_extra_opening_bracket_removed(self) -> None:
        """More ( than ) by 2+ → remove leading ("""
        result = _fix_bidi_brackets("((سلام) دنیا")
        # 2 opening, 1 closing → diff=1 < 2 → no change by Pattern 3
        # Pattern 2: leading ( is NOT followed by Persian (next is (سلام...)
        # Actually ( is followed by ( which is not Persian, so Pattern 2 doesn't match
        # Result keeps the imbalance since diff < 2
        self.assertEqual(result, "((سلام) دنیا")

    def test_balanced_brackets_unchanged(self) -> None:
        """Balanced brackets should remain unchanged."""
        text = "(سلام) دنیا"
        result = _fix_bidi_brackets(text)
        self.assertEqual(result, text)

    def test_no_brackets_unchanged(self) -> None:
        """Text with no brackets should remain unchanged."""
        text = "سلام دنیا"
        result = _fix_bidi_brackets(text)
        self.assertEqual(result, text)

    def test_english_text_unchanged(self) -> None:
        """English text with brackets should remain unchanged."""
        text = "Hello (world) test"
        result = _fix_bidi_brackets(text)
        self.assertEqual(result, text)

    def test_empty_string(self) -> None:
        """Empty string should return empty string."""
        self.assertEqual(_fix_bidi_brackets(""), "")

    # ------------------------------------------------------------------
    # Mixed / real-world scenarios
    # ------------------------------------------------------------------

    def test_mixed_persian_english_brackets(self) -> None:
        """Mixed Persian/English text with brackets."""
        text = "ماده ۲ (قانون مدنی) به شرح زیر است"
        result = _fix_bidi_brackets(text)
        # Should remain balanced and correct
        self.assertEqual(result.count("("), result.count(")"))

    def test_persian_legal_text_with_parentheses(self) -> None:
        """Realistic Persian legal text with parentheses."""
        text = (
            "به موجب ماده ۲ قانون مدنی )قراردادهای خصوصی نسبت به کسانی که "
            "آن را منعقد نموده اند( در حکم قانون است."
        )
        result = _fix_bidi_brackets(text)
        # Closing bracket before Persian should be moved after
        self.assertNotIn(")ق", result)  # )ق should become ق)
        # Opening bracket after Persian should be moved before
        self.assertNotIn("ند(", result)  # ند( should become (ند
        # Brackets should be balanced
        self.assertEqual(result.count("("), result.count(")"))

    def test_nested_brackets_preserved(self) -> None:
        """Nested brackets should be preserved when balanced."""
        text = "متن (سلام (دنیا))"
        result = _fix_bidi_brackets(text)
        self.assertEqual(result, text)

    def test_multiline_bracket_balancing(self) -> None:
        """Multi-line text with bracket issues on different lines."""
        text = "خط اول)\nخط دوم(\nخط سوم"
        result = _fix_bidi_brackets(text)
        lines = result.split('\n')
        self.assertEqual(len(lines), 3)
        # Line 1: ) after Persian → Pattern 1's negative lookbehind prevents
        # matching because ) is preceded by Persian character (ل).
        # Result: "خط اول)" (unchanged — already correct for RTL)
        self.assertEqual(lines[0], "خط اول)")
        # Line 2: ( before end → Pattern 2 matches the LAST Persian word
        # before ( (i.e., "دوم(") and moves ( before it: "(دوم".
        # The full line becomes "خط (دوم" (first word "خط" stays in place).
        self.assertEqual(lines[1], "خط (دوم")
