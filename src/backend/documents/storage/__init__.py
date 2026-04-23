"""
Storage abstraction layer for DocuChat.

Provides a factory function ``get_storage_backend()`` that returns the
appropriate storage backend based on ``settings.STORAGE_TYPE``.
"""

import logging

from django.conf import settings

from documents.storage.base import StorageBackend, StorageError

logger = logging.getLogger(__name__)


def get_storage_backend() -> StorageBackend:
    """
    Factory function that returns a storage backend instance based on the
    ``STORAGE_TYPE`` Django setting.

    Supported storage types:
        - ``"local"`` → :class:`documents.storage.local.LocalStorageBackend`
        - ``"s3"``    → :class:`documents.storage.s3.S3StorageBackend`

    Returns:
        An instance of a :class:`StorageBackend` subclass.

    Raises:
        StorageError: If ``STORAGE_TYPE`` is unknown or the backend cannot
                      be instantiated.
    """
    storage_type = settings.STORAGE_TYPE.lower().strip()

    if storage_type == "local":
        from documents.storage.local import LocalStorageBackend

        logger.info("Using LocalStorageBackend")
        return LocalStorageBackend()

    if storage_type == "s3":
        from documents.storage.s3 import S3StorageBackend

        logger.info("Using S3StorageBackend")
        return S3StorageBackend()

    raise StorageError(
        f"Unknown STORAGE_TYPE '{settings.STORAGE_TYPE}'. "
        f"Expected 'local' or 's3'."
    )
