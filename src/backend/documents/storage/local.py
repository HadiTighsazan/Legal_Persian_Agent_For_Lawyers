"""
Local filesystem storage backend implementation.
"""

import io
import logging
import os
import shutil
from pathlib import Path
from typing import BinaryIO

from django.conf import settings

from documents.storage.base import StorageBackend, StorageError

logger = logging.getLogger(__name__)


class LocalStorageBackend(StorageBackend):
    """
    Storage backend that saves files to the local filesystem.

    Files are stored under the directory specified by
    ``settings.LOCAL_STORAGE_PATH``.
    """

    def __init__(self) -> None:
        self._storage_root = Path(settings.LOCAL_STORAGE_PATH)
        self._ensure_storage_root()

    def _ensure_storage_root(self) -> None:
        """Create the storage root directory if it does not exist."""
        try:
            self._storage_root.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Local storage root ensured at %s", self._storage_root
            )
        except OSError as exc:
            raise StorageError(
                f"Failed to create storage root '{self._storage_root}': {exc}"
            ) from exc

    def _resolve_path(self, relative_path: str) -> Path:
        """
        Resolve a relative path against the storage root.

        Performs a directory-traversal check to ensure the resolved path
        stays within the storage root.
        """
        # Sanitize: strip any leading slashes to prevent absolute-path issues
        sanitized = relative_path.lstrip("/\\")
        resolved = (self._storage_root / sanitized).resolve()

        # Directory traversal protection
        if not str(resolved).startswith(str(self._storage_root.resolve())):
            raise StorageError(
                f"Path '{relative_path}' escapes the storage root."
            )

        return resolved

    def open(self, storage_path: str) -> BinaryIO:
        """
        Open a stored file for reading.

        If *storage_path* is an absolute path, it is used directly.
        Otherwise, it is resolved relative to the storage root.

        Returns an in-memory ``BytesIO`` buffer so the returned stream is
        seekable and compatible with libraries (e.g. PyMuPDF) that expect
        a full ``BytesIO``-like object.

        Args:
            storage_path: The storage path returned by save_file(), or an
                          absolute filesystem path.

        Returns:
            A ``BytesIO`` buffer containing the file contents.

        Raises:
            StorageError: If the file cannot be opened or does not exist.
        """
        if os.path.isabs(storage_path):
            resolved = Path(storage_path)
        else:
            resolved = self._resolve_path(storage_path)

        if not resolved.exists():
            raise StorageError(
                f"File not found at '{resolved}'"
            )

        try:
            with open(resolved, "rb") as f:
                return io.BytesIO(f.read())
        except OSError as exc:
            raise StorageError(
                f"Failed to open file '{resolved}': {exc}"
            ) from exc

    def save_file(self, uploaded_file: BinaryIO, relative_path: str) -> str:
        """
        Save an uploaded file to the local filesystem.

        Args:
            uploaded_file: A file-like object containing the file data.
            relative_path: Relative path under the storage root.

        Returns:
            str: The absolute filesystem path of the saved file.
        """
        destination = self._resolve_path(relative_path)

        # Ensure parent directories exist
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"Failed to create parent directories for '{destination}': {exc}"
            ) from exc

        try:
            with open(destination, "wb") as dest_file:
                shutil.copyfileobj(uploaded_file, dest_file)
            logger.info("File saved locally at %s", destination)
        except OSError as exc:
            raise StorageError(
                f"Failed to write file to '{destination}': {exc}"
            ) from exc

        return str(destination)

    def get_file_url(self, storage_path: str) -> str:
        """
        Return the local filesystem path for a stored file.

        Args:
            storage_path: The absolute path returned by save_file().

        Returns:
            str: The absolute filesystem path.
        """
        return storage_path

    def delete_file(self, storage_path: str) -> bool:
        """
        Delete a file from the local filesystem.

        Args:
            storage_path: The absolute path returned by save_file().

        Returns:
            bool: True if the file was deleted, False if it did not exist.
        """
        path = Path(storage_path)

        if not path.exists():
            logger.warning("File not found for deletion: %s", storage_path)
            return False

        try:
            path.unlink()
            logger.info("File deleted: %s", storage_path)
            return True
        except OSError as exc:
            raise StorageError(
                f"Failed to delete file '{storage_path}': {exc}"
            ) from exc
