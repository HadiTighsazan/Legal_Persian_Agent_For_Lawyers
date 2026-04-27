"""
Integration tests for the document upload endpoint (``POST /documents/upload/``).

Covers the full upload workflow:
  1. Valid PDF upload → 201 + DB record verification.
  2. Invalid file type (``.exe``) → 400.
  3. File too large (exceeds ``MAX_UPLOAD_SIZE``) → 400.
  4. Storage backend failure → 500.
  5. Unauthenticated request → 401.
"""

import io
import json
import uuid
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import Document
from documents.storage.base import StorageError
from users.jwt_utils import generate_access_token
from users.models import User


class DocumentUploadIntegrationTests(TestCase):
    """Integration test suite for ``POST /documents/upload/``."""

    def setUp(self) -> None:
        """Set up the test client, a test user, and a valid JWT access token."""
        self.client = APIClient()
        self.upload_url = "/documents/upload/"

        # Create a test user
        self.user = User.objects.create_user(
            email="uploadtest@example.com",
            password="SecurePass123!",
            full_name="Upload Test User",
        )

        # Generate a valid JWT access token for the test user
        self.access_token = generate_access_token(self.user)

        # Authenticate the client for tests 1-4
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access_token}"
        )

    # ------------------------------------------------------------------
    # Helper — build a simple in-memory PDF-like file
    # ------------------------------------------------------------------

    @staticmethod
    def _make_pdf_bytes() -> bytes:
        """Return minimal bytes that pass the PDF extension check."""
        return b"%PDF-1.4 fake pdf content for testing purposes.\n"

    @staticmethod
    def _make_file(
        name: str = "test.pdf",
        content: bytes | None = None,
        content_type: str = "application/pdf",
    ) -> SimpleUploadedFile:
        """Build a ``SimpleUploadedFile`` for use in multipart uploads."""
        if content is None:
            content = DocumentUploadIntegrationTests._make_pdf_bytes()
        return SimpleUploadedFile(
            name=name,
            content=content,
            content_type=content_type,
        )

    # ==================================================================
    # Test 1 — Valid PDF upload → 201 + DB record verification
    # ==================================================================

    def test_valid_pdf_upload_returns_201(self) -> None:
        """Upload a valid PDF and verify 201 + correct DB record."""
        uploaded_file = self._make_file()
        response = self.client.post(
            self.upload_url,
            {"file": uploaded_file},
            format="multipart",
        )

        # Assert HTTP 201 Created
        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            msg=f"Expected 201, got {response.status_code}: {response.data}",
        )

        data = response.json()

        # --- Verify response shape ---
        expected_keys = {
            "id", "title", "original_filename", "file_size",
            "mime_type", "file_path", "storage_type", "status",
            "created_at",
        }
        self.assertSetEqual(
            expected_keys,
            set(data.keys()),
            msg=f"Response keys mismatch. Extra/missing: "
                f"{expected_keys.symmetric_difference(data.keys())}",
        )

        # --- Verify response values ---
        self.assertEqual(data["original_filename"], "test.pdf")
        self.assertEqual(data["mime_type"], "application/pdf")
        self.assertEqual(data["file_size"], len(self._make_pdf_bytes()))
        self.assertEqual(data["status"], "uploaded")
        self.assertEqual(data["storage_type"], "local")

        # --- Verify DB record ---
        doc_id = data["id"]
        try:
            doc = Document.objects.get(id=doc_id)
        except Document.DoesNotExist:
            self.fail(f"Document with id={doc_id} was not found in the database.")

        self.assertEqual(doc.original_filename, "test.pdf")
        self.assertEqual(doc.mime_type, "application/pdf")
        self.assertEqual(doc.file_size, len(self._make_pdf_bytes()))
        self.assertEqual(doc.status, "uploaded")
        self.assertEqual(doc.user, self.user)
        self.assertIsNotNone(doc.file_path)
        self.assertTrue(doc.file_path.endswith(".pdf"))

    # ==================================================================
    # Test 2 — Invalid file type → 400
    # ==================================================================

    def test_invalid_file_type_returns_400(self) -> None:
        """Upload a ``.exe`` file and assert 400 Bad Request."""
        uploaded_file = self._make_file(
            name="malware.exe",
            content=b"MZ\x90\x00 fake exe content",
            content_type="application/x-msdownload",
        )
        response = self.client.post(
            self.upload_url,
            {"file": uploaded_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            msg=f"Expected 400 for invalid file type, got {response.status_code}",
        )

        # The response body should contain a descriptive error
        data = response.json()
        self.assertIn(
            "detail",
            data,
            msg="Response should contain a 'detail' key with the error message.",
        )
        # The error message should mention the invalid extension
        self.assertIn(
            ".exe",
            data["detail"],
            msg=f"Error message should mention '.exe', got: {data['detail']}",
        )

    # ==================================================================
    # Test 3 — File too large → 400
    # ==================================================================

    def test_file_too_large_returns_400(self) -> None:
        """Upload a file exceeding ``MAX_UPLOAD_SIZE`` and assert 400."""
        max_size = settings.MAX_UPLOAD_SIZE  # 50 MB in bytes
        oversized_content = b"x" * (max_size + 1)  # 1 byte over the limit

        uploaded_file = self._make_file(
            name="oversized.pdf",
            content=oversized_content,
        )
        response = self.client.post(
            self.upload_url,
            {"file": uploaded_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            msg=f"Expected 400 for oversized file, got {response.status_code}",
        )

        data = response.json()
        self.assertIn(
            "detail",
            data,
            msg="Response should contain a 'detail' key with the error message.",
        )
        # The error message should reference the size limit
        self.assertIn(
            "MB",
            data["detail"],
            msg=f"Error message should mention size limit, got: {data['detail']}",
        )

    # ==================================================================
    # Test 4 — Storage backend failure → 500
    # ==================================================================

    @patch("documents.services.upload_service.get_storage_backend")
    def test_storage_failure_returns_500(
        self, mock_get_storage_backend
    ) -> None:
        """Mock the storage backend to raise ``StorageError`` and assert 500."""
        # Arrange — make the mocked backend's save_file raise StorageError
        mock_storage = mock_get_storage_backend.return_value
        mock_storage.save_file.side_effect = StorageError(
            "Disk full — cannot write file"
        )
        # The storage_type attribute is read by the upload service
        mock_storage.storage_type = "local"

        uploaded_file = self._make_file()
        response = self.client.post(
            self.upload_url,
            {"file": uploaded_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            msg=f"Expected 500 on storage failure, got {response.status_code}",
        )

        data = response.json()
        self.assertIn(
            "detail",
            data,
            msg="Response should contain a 'detail' key with the error message.",
        )
        self.assertIn(
            "Storage error",
            data["detail"],
            msg=f"Error message should mention 'Storage error', got: {data['detail']}",
        )

        # Verify the mocked method was actually called
        mock_storage.save_file.assert_called_once()

    # ==================================================================
    # Test 5 — Unauthenticated request → 401
    # ==================================================================

    def test_unauthenticated_request_returns_401(self) -> None:
        """Make a request without a JWT token and assert 401."""
        # Create a fresh client without any credentials
        anon_client = APIClient()

        uploaded_file = self._make_file()
        response = anon_client.post(
            self.upload_url,
            {"file": uploaded_file},
            format="multipart",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            msg=f"Expected 401 for unauthenticated request, got {response.status_code}",
        )

        # DRF's JWTAuthentication returns JSON with a 'detail' key
        data = response.json()
        self.assertIn(
            "detail",
            data,
            msg="Response should contain a 'detail' key for unauthenticated requests.",
        )
