"""
Tests for the document processing pipeline.

Covers:
- :class:`~documents.services.anchor_chunking_service.AnchorChunkingService` unit tests (no DB)
- Full pipeline integration test (DB + mocked Celery)
- Authentication requirement for all processing endpoints
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import MagicMock, PropertyMock, patch

import fitz
import tiktoken
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import Document, DocumentChunk
from documents.services.anchor_chunking_service import AnchorChunkingService
from documents.tasks.document_processing import (
    _handle_chain_error,
    chunk_document,
    extract_text_from_pdf,
)
from tasks.models import ProcessingTask
from users.models import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENCODING = tiktoken.get_encoding("cl100k_base")


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


def _auth_header(user: User) -> dict[str, str]:
    """Return an Authorization header dict for the given user."""
    from rest_framework_simplejwt.tokens import RefreshToken  # noqa: PLC0415

    refresh = RefreshToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}


# ===================================================================
# Category 1: AnchorChunkingService Unit Tests (No DB Needed)
# ===================================================================


class AnchorChunkingServiceTests(TestCase):
    """Pure unit tests for :class:`AnchorChunkingService.chunk_text`.

    These tests instantiate ``AnchorChunkingService`` directly and call
    ``chunk_text()`` with various inputs.  No database or Celery needed.
    """

    def setUp(self) -> None:
        self.service = AnchorChunkingService()

    # -- Test 1: Short text returns one chunk ---------------------------

    def test_chunk_text_short_text_returns_one_chunk(self) -> None:
        """Short text should produce at least 1 chunk."""
        text = "Hello world. This is a short document."
        chunks = self.service.chunk_text(text, chunk_tokens=400, overlap_tokens=50)

        self.assertGreaterEqual(len(chunks), 1)
        self.assertIn("Hello world", chunks[0].content)

    # -- Test 2: Long text returns multiple chunks ----------------------

    def test_chunk_text_long_text_returns_multiple_chunks(self) -> None:
        """Long text should produce multiple chunks."""
        # 3000 characters with chunk_tokens=400 should produce multiple chunks.
        text = "Hello world. " + "A" * 2980
        chunks = self.service.chunk_text(text, chunk_tokens=400, overlap_tokens=50)

        self.assertGreaterEqual(len(chunks), 2)

    # -- Test 3: Overlap between consecutive chunks ---------------------

    def test_chunk_text_overlap_is_correct(self) -> None:
        """Consecutive chunks should share overlapping content."""
        # Create text long enough to require splitting.
        # Use 5000+ chars to guarantee multiple chunks with chunk_tokens=400.
        text = ("A" * 800 + " ") * 7  # ~5600 chars
        chunks = self.service.chunk_text(text, chunk_tokens=400, overlap_tokens=50)

        self.assertGreaterEqual(len(chunks), 2)

        chunk1 = chunks[0].content
        chunk2 = chunks[1].content

        # With overlap_tokens=50, chunk 2 should start before chunk 1's end,
        # so chunk 1 should contain chunk 2's content as a suffix.
        overlap_chars = 0
        for i in range(min(len(chunk1), len(chunk2)), 0, -1):
            if chunk1[-i:] == chunk2[:i]:
                overlap_chars = i
                break

        self.assertGreater(
            overlap_chars,
            0,
            "Chunks should share at least some overlapping content",
        )

    # -- Test 4: Token count calculation ---------------------------------

    def test_chunk_text_token_count_calculation(self) -> None:
        """``token_count`` should match ``len(tiktoken.encode(content))``."""
        text = "The quick brown fox jumps over the lazy dog. " * 20
        chunks = self.service.chunk_text(text, chunk_tokens=400, overlap_tokens=50)

        self.assertGreater(len(chunks), 0)

        for chunk in chunks:
            expected_tokens = len(_ENCODING.encode(chunk.content))
            self.assertEqual(
                chunk.token_count,
                expected_tokens,
                f"Token count mismatch for chunk: {chunk.content[:50]}...",
            )

    # -- Test 5: Empty text returns empty list ---------------------------

    def test_chunk_text_empty_text_returns_empty_list(self) -> None:
        """Empty string should return an empty list."""
        chunks = self.service.chunk_text("", chunk_tokens=400, overlap_tokens=50)
        self.assertEqual(chunks, [])

    # -- Test 6: Page number tracking ------------------------------------

    def test_chunk_text_page_number_tracking(self) -> None:
        """``pages`` should be correctly resolved from ``[PAGE N]`` markers."""
        text = (
            "[PAGE 1]\n"
            "Hello from page one. This is the first page of content.\n"
            "[PAGE 2]\n"
            "Second page content goes here. More text on the second page.\n"
            "[PAGE 3]\n"
            "Third page content."
        )
        # Use a large chunk_tokens so everything fits in one chunk.
        chunks = self.service.chunk_text(text, chunk_tokens=2000, overlap_tokens=200)

        self.assertGreaterEqual(len(chunks), 1)

        # The chunk should span pages 1 through 3.
        chunk = chunks[0]
        self.assertIn(1, chunk.pages)
        self.assertIn(3, chunk.pages)

    def test_chunk_text_page_tracking_multiple_chunks(self) -> None:
        """With multiple chunks, each chunk should have correct pages."""
        text = (
            "[PAGE 1]\n"
            + "A" * 600
            + "\n[PAGE 2]\n"
            + "B" * 600
            + "\n[PAGE 3]\n"
            + "C" * 600
        )
        chunks = self.service.chunk_text(text, chunk_tokens=200, overlap_tokens=50)

        self.assertGreaterEqual(len(chunks), 2)

        for chunk in chunks:
            self.assertGreaterEqual(len(chunk.pages), 1)


# ===================================================================
# Category 2: Integration Test (DB + Mocked Celery)
# ===================================================================


class FullPipelineIntegrationTests(TestCase):
    """Integration test that exercises the full document processing pipeline
    end-to-end with a real PDF and mocked Celery execution.

    This test fills a gap not covered by the existing task-level tests:
    it creates a real PDF file, uploads it as a ``Document``, calls
    ``process_document`` to create the ``ProcessingTask``, then manually
    invokes the Celery tasks synchronously to verify the full flow.
    """

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="pipeline@example.com",
            password="testpass123",
        )

        # Create a temporary PDF file.
        self.tmpdir = tempfile.mkdtemp()
        self.pdf_path = os.path.join(self.tmpdir, "integration.pdf")
        _create_sample_pdf(
            self.pdf_path,
            [
                "This is the first page of the integration test document.",
                "This is the second page with more content for chunking.",
                "Third page here, providing additional text to process.",
            ],
        )

        self.document = Document.objects.create(
            user=self.user,
            title="Integration Test Document",
            filename="integration.pdf",
            original_filename="integration.pdf",
            file_path=self.pdf_path,
            file_size=os.path.getsize(self.pdf_path),
            mime_type="application/pdf",
            processing_status="pending",
        )

    def tearDown(self) -> None:
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_full_pipeline_integration(self) -> None:
        """Create a real PDF, call ``process_document``, verify
        ``ProcessingTask`` created, then run the Celery tasks synchronously
        and verify chunks are created in the database."""
        document_id = str(self.document.id)

        # --- Step 1: Call process_document (orchestration) ---
        with patch("documents.services.processing_service.chain") as mock_chain:
            mock_result = MagicMock()
            mock_result.id = "integration-chain-id"
            mock_chain_obj = MagicMock()
            mock_chain_obj.apply_async.return_value = mock_result
            mock_chain.return_value = mock_chain_obj

            from documents.tasks import process_document  # noqa: PLC0415

            task_id = process_document(document_id)

        self.assertIsNotNone(task_id, "process_document should return a task ID")
        self.assertEqual(task_id, "integration-chain-id")

        # Verify a ProcessingTask was created with status="pending".
        processing_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="extract",
        )
        self.assertEqual(processing_task.status, "pending")
        self.assertEqual(
            processing_task.celery_task_id,
            "integration-chain-id",
        )

        # --- Step 2: Run extract_text_from_pdf synchronously ---
        with _mock_celery_request(extract_text_from_pdf, celery_task_id="extract-task-id"):
            extracted_text = extract_text_from_pdf(document_id)

        self.assertIn("[PAGE 1]", extracted_text)
        self.assertIn("[PAGE 2]", extracted_text)
        self.assertIn("[PAGE 3]", extracted_text)
        self.assertIn("first page", extracted_text)
        self.assertIn("second page", extracted_text)
        self.assertIn("Third page", extracted_text)

        # Verify the extract ProcessingTask was marked completed.
        processing_task.refresh_from_db()
        self.assertEqual(processing_task.status, "completed")
        self.assertIsNotNone(processing_task.started_at)
        self.assertIsNotNone(processing_task.completed_at)

        # Verify document fields were updated.
        self.document.refresh_from_db()
        self.assertGreater(self.document.extracted_text_length, 0)
        self.assertEqual(self.document.total_pages, 3)

        # --- Step 3: Run chunk_document synchronously ---
        with _mock_celery_request(chunk_document, celery_task_id="chunk-task-id"):
            chunk_document(extracted_text, document_id)

        # Verify DocumentChunks were created.
        chunks = DocumentChunk.objects.filter(
            document=self.document,
        ).order_by("chunk_index")
        self.assertGreater(len(chunks), 0, "Chunks should be created in the database")

        # Verify chunk structure.
        for chunk in chunks:
            self.assertEqual(chunk.document_id, self.document.id)
            self.assertIsNotNone(chunk.content)
            self.assertIsInstance(chunk.token_count, int)
            self.assertGreaterEqual(chunk.page_start, 1)
            self.assertGreaterEqual(chunk.page_end, chunk.page_start)

        # Verify the chunk ProcessingTask was created and marked completed.
        chunk_task = ProcessingTask.objects.get(
            document=self.document,
            task_type="chunk",
        )
        self.assertEqual(chunk_task.status, "completed")
        self.assertIsNotNone(chunk_task.started_at)
        self.assertIsNotNone(chunk_task.completed_at)

        # Verify document state after chunking (embed step not yet run).
        # processing_status remains "processing" because chunk_document no longer
        # sets it to "completed" — that responsibility moved to embed_document
        # (the final link in the Celery chain) to prevent the frontend from
        # stopping polling before embeddings are generated (Bug A fix).
        self.document.refresh_from_db()
        self.assertEqual(self.document.total_chunks, len(chunks))
        self.assertEqual(self.document.processing_status, "processing")


# ===================================================================
# Category 3: API Auth Tests (DB + HTTP)
# ===================================================================


class ProcessingEndpointsAuthTests(TestCase):
    """Verify that all 5 processing-related endpoints require authentication.

    This is a consolidated test that covers the auth gap: each individual
    view test file already tests ``unauthenticated_request_returns_401``,
    but this parametrized-style test provides a single source of truth
    that ALL endpoints consistently reject unauthenticated requests.
    """

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="auth-test@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Auth Test Document",
            filename="auth_test.pdf",
            original_filename="auth_test.pdf",
            file_path="/tmp/auth_test.pdf",
            file_size=1000,
            mime_type="application/pdf",
            processing_status="pending",
        )

    def _assert_returns_401(self, method: str, url: str) -> None:
        """Make an unauthenticated request and assert 401."""
        response = getattr(self.client, method)(url)
        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            f"Unauthenticated {method.upper()} {url} should return 401, "
            f"got {response.status_code}",
        )

    def test_all_endpoints_require_authentication(self) -> None:
        """Hit all 5 processing endpoints without auth — all should return 401."""
        endpoints = [
            # (method, url_name, kwargs)
            ("post", "documents:document-upload", {}),
            (
                "post",
                "documents:document-process",
                {"document_id": self.document.id},
            ),
            (
                "get",
                "documents:document-processing-status",
                {"document_id": self.document.id},
            ),
            (
                "get",
                "documents:document-chunks",
                {"document_id": self.document.id},
            ),
            (
                "post",
                "documents:processing-task-retry",
                {"task_id": "00000000-0000-0000-0000-000000000000"},
            ),
        ]

        for method, url_name, kwargs in endpoints:
            url = reverse(url_name, kwargs=kwargs)
            self._assert_returns_401(method, url)

    def test_authenticated_request_succeeds(self) -> None:
        """Sanity check: authenticated requests should not return 401."""
        # Use the processing-status endpoint (GET, no side effects).
        url = reverse(
            "documents:document-processing-status",
            kwargs={"document_id": self.document.id},
        )
        response = self.client.get(url, **_auth_header(self.user))
        # Should return 200 (document exists, no processing tasks yet).
        self.assertEqual(response.status_code, status.HTTP_200_OK)
