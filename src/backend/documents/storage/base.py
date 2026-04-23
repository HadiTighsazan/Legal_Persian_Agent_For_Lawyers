"""
Abstract base class for storage backends.

Defines the interface that all storage backends must implement.
"""

from abc import ABC, abstractmethod
from typing import BinaryIO


class StorageBackend(ABC):
    """
    Abstract base class for file storage backends.

    All storage backends (local, S3, etc.) must implement these methods.
    """

    @abstractmethod
    def save_file(self, uploaded_file: BinaryIO, relative_path: str) -> str:
        """
        Save an uploaded file to storage.

        Args:
            uploaded_file: A file-like object containing the file data.
            relative_path: The relative path (including filename) where the
                           file should be stored.

        Returns:
            str: The full storage path (local path or S3 key) where the
                 file was saved.

        Raises:
            StorageError: If the file could not be saved.
        """
        ...

    @abstractmethod
    def get_file_url(self, storage_path: str) -> str:
        """
        Get the URL or local filesystem path for retrieving a stored file.

        Args:
            storage_path: The storage path returned by save_file().

        Returns:
            str: A URL or absolute filesystem path that can be used to
                 retrieve the file.
        """
        ...

    @abstractmethod
    def delete_file(self, storage_path: str) -> bool:
        """
        Delete a file from storage.

        Args:
            storage_path: The storage path returned by save_file().

        Returns:
            bool: True if the file was successfully deleted, False otherwise.

        Raises:
            StorageError: If an unexpected error occurs during deletion.
        """
        ...


class StorageError(Exception):
    """Base exception for storage backend errors."""
    pass
