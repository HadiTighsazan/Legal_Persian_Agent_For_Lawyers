"""
Tests for :class:`~documents.storage.local.LocalStorageBackend`.

Covers:
- ``save_file`` returns a **relative** path (not absolute).
- ``open`` resolves relative paths correctly.
- ``open`` handles absolute paths for backward compatibility.
- ``open`` raises ``StorageError`` for non-existent files.
- ``delete_file`` works with relative paths.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from documents.storage.base import StorageError
from documents.storage.local import LocalStorageBackend


class LocalStorageBackendTests(TestCase):
    """Unit tests for :class:`LocalStorageBackend`."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        # Override LOCAL_STORAGE_PATH to a temp directory for isolation.
        self.storage_root = os.path.join(self.tmpdir, "documents")
        self.settings_patcher = override_settings(
            LOCAL_STORAGE_PATH=self.storage_root,
        )
        self.settings_patcher.enable()
        self.backend = LocalStorageBackend()

    def tearDown(self) -> None:
        self.settings_patcher.disable()
        # Clean up temp directory.
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # save_file returns relative path
    # ------------------------------------------------------------------

    def test_save_file_returns_relative_path(self) -> None:
        """``save_file`` should return a relative path, not absolute."""
        file_data = io.BytesIO(b"%PDF-1.4 test content")
        relative_path = "test/uuid-file.pdf"

        result = self.backend.save_file(file_data, relative_path)

        # The returned path should be the same relative path we passed in.
        self.assertEqual(
            result,
            relative_path,
            "save_file should return the relative path, not an absolute path",
        )

        # Verify the file was actually written to the storage root.
        expected_abs = os.path.join(self.storage_root, relative_path)
        self.assertTrue(
            os.path.exists(expected_abs),
            f"File should exist at {expected_abs}",
        )

    # ------------------------------------------------------------------
    # open resolves relative paths
    # ------------------------------------------------------------------

    def test_open_relative_path(self) -> None:
        """``open`` should resolve a relative path against the storage root."""
        relative_path = "test/hello.txt"
        content = b"Hello, World!"
        abs_path = os.path.join(self.storage_root, relative_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(content)

        result = self.backend.open(relative_path)
        self.assertEqual(result.read(), content)

    # ------------------------------------------------------------------
    # open handles absolute paths (backward compat)
    # ------------------------------------------------------------------

    def test_open_absolute_path_backward_compat(self) -> None:
        """``open`` should still work with absolute paths for backward compat."""
        content = b"Old absolute path content"
        abs_path = os.path.join(self.storage_root, "legacy.pdf")
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(content)

        result = self.backend.open(abs_path)
        self.assertEqual(result.read(), content)

    # ------------------------------------------------------------------
    # open raises StorageError for non-existent files
    # ------------------------------------------------------------------

    def test_open_nonexistent_file_raises_storage_error(self) -> None:
        """``open`` should raise ``StorageError`` when the file does not exist."""
        with self.assertRaises(StorageError):
            self.backend.open("nonexistent/file.pdf")

    # ------------------------------------------------------------------
    # delete_file with relative path
    # ------------------------------------------------------------------

    def test_delete_file_relative_path(self) -> None:
        """``delete_file`` should work with relative paths."""
        relative_path = "test/to-delete.txt"
        abs_path = os.path.join(self.storage_root, relative_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(b"delete me")

        # Delete using the relative path.
        result = self.backend.delete_file(relative_path)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(abs_path))

    def test_delete_file_nonexistent_returns_false(self) -> None:
        """``delete_file`` should return ``False`` for non-existent files."""
        result = self.backend.delete_file("does-not-exist.pdf")
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # get_file_url returns the path as-is
    # ------------------------------------------------------------------

    def test_get_file_url_returns_path_as_is(self) -> None:
        """``get_file_url`` should return the path unchanged."""
        path = "relative/path.pdf"
        self.assertEqual(self.backend.get_file_url(path), path)
