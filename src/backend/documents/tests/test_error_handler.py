"""
Tests for :mod:`documents.services.error_handler`.

Covers:
- ``_has_pdf_magic_bytes`` handles ``FileNotFoundError`` gracefully.
- ``_has_pdf_magic_bytes`` handles ``PermissionError`` gracefully.
- ``_has_pdf_magic_bytes`` returns ``True`` for valid PDF headers.
- ``_has_pdf_magic_bytes`` returns ``False`` for non-PDF files.
- ``classify_pdf_error`` handles non-existent file paths without crashing.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from documents.services.error_handler import (
    _has_pdf_magic_bytes,
    classify_pdf_error,
)


class HasPdfMagicBytesTests(SimpleTestCase):
    """Tests for :func:`_has_pdf_magic_bytes`."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nonexistent_file_returns_false(self) -> None:
        """``_has_pdf_magic_bytes`` should return ``False`` (not crash)
        when the file does not exist."""
        path = os.path.join(self.tmpdir, "nonexistent.pdf")
        result = _has_pdf_magic_bytes(path)
        self.assertFalse(result)

    def test_permission_error_returns_false(self) -> None:
        """``_has_pdf_magic_bytes`` should return ``False`` (not crash)
        when the file cannot be read due to permissions."""
        path = os.path.join(self.tmpdir, "restricted.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 test")

        # Mock open to raise PermissionError.
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            result = _has_pdf_magic_bytes(path)
        self.assertFalse(result)

    def test_valid_pdf_header_returns_true(self) -> None:
        """``_has_pdf_magic_bytes`` should return ``True`` for a file
        starting with ``%PDF``."""
        path = os.path.join(self.tmpdir, "valid.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4\n%%EOF")
        result = _has_pdf_magic_bytes(path)
        self.assertTrue(result)

    def test_non_pdf_header_returns_false(self) -> None:
        """``_has_pdf_magic_bytes`` should return ``False`` for a file
        that does not start with ``%PDF``."""
        path = os.path.join(self.tmpdir, "not-a-pdf.txt")
        with open(path, "wb") as f:
            f.write(b"Not a PDF file")
        result = _has_pdf_magic_bytes(path)
        self.assertFalse(result)

    def test_empty_file_returns_false(self) -> None:
        """``_has_pdf_magic_bytes`` should return ``False`` for an empty file."""
        path = os.path.join(self.tmpdir, "empty.pdf")
        with open(path, "wb") as f:
            pass  # empty file
        result = _has_pdf_magic_bytes(path)
        self.assertFalse(result)


class ClassifyPdfErrorTests(SimpleTestCase):
    """Tests for :func:`classify_pdf_error`."""

    def test_nonexistent_file_path_does_not_crash(self) -> None:
        """``classify_pdf_error`` should not crash when the PDF path
        does not exist (the underlying ``_has_pdf_magic_bytes`` should
        handle it gracefully)."""
        exception = Exception("Some error")
        path = "/nonexistent/path/to/file.pdf"
        # This should not raise any exception.
        result = classify_pdf_error(exception, path)
        # Since the file doesn't exist, _has_pdf_magic_bytes returns False,
        # so classify_pdf_error returns "File is not a valid PDF".
        self.assertEqual(result, "File is not a valid PDF")
