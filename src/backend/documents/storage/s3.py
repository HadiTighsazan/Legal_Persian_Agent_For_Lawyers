"""
S3 storage backend implementation using boto3.
"""

import logging
from typing import BinaryIO, Optional

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

from documents.storage.base import StorageBackend, StorageError

logger = logging.getLogger(__name__)


class S3StorageBackend(StorageBackend):
    """
    Storage backend that saves files to an AWS S3 bucket.

    Configuration is read from Django settings:
        - ``S3_BUCKET_NAME``
        - ``S3_REGION``
    AWS credentials are resolved by boto3 via environment variables,
    IAM roles, or the AWS credentials file.
    """

    def __init__(self) -> None:
        self._bucket_name: str = settings.S3_BUCKET_NAME
        self._region: str = settings.S3_REGION
        self._client = self._build_client()

    def _build_client(self):
        """Create and return a low-level S3 client."""
        try:
            client = boto3.client("s3", region_name=self._region)
            logger.info(
                "S3 client initialised for bucket '%s' in region '%s'",
                self._bucket_name,
                self._region,
            )
            return client
        except Exception as exc:
            raise StorageError(
                f"Failed to initialise S3 client: {exc}"
            ) from exc

    def save_file(self, uploaded_file: BinaryIO, relative_path: str) -> str:
        """
        Upload a file to the configured S3 bucket.

        Args:
            uploaded_file: A file-like object containing the file data.
            relative_path: The S3 object key (path within the bucket).

        Returns:
            str: The S3 object key (identical to ``relative_path``).
        """
        try:
            self._client.upload_fileobj(
                uploaded_file,
                self._bucket_name,
                relative_path,
            )
            logger.info(
                "File uploaded to s3://%s/%s",
                self._bucket_name,
                relative_path,
            )
        except ClientError as exc:
            raise StorageError(
                f"Failed to upload file to S3 (bucket='{self._bucket_name}', "
                f"key='{relative_path}'): {exc}"
            ) from exc

        return relative_path

    def get_file_url(self, storage_path: str) -> str:
        """
        Generate a presigned URL for retrieving the file from S3.

        The URL is valid for 1 hour (3600 seconds).

        Args:
            storage_path: The S3 object key returned by save_file().

        Returns:
            str: A presigned HTTPS URL to access the file.
        """
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket_name,
                    "Key": storage_path,
                },
                ExpiresIn=3600,
            )
            return url
        except ClientError as exc:
            raise StorageError(
                f"Failed to generate presigned URL for "
                f"s3://{self._bucket_name}/{storage_path}: {exc}"
            ) from exc

    def open(self, storage_path: str) -> BinaryIO:
        """
        Open a stored file from S3 for reading.

        Downloads the file content into an in-memory ``BytesIO`` buffer.

        Args:
            storage_path: The S3 object key returned by save_file().

        Returns:
            A ``BytesIO`` buffer containing the file contents.

        Raises:
            StorageError: If the file cannot be retrieved from S3.
        """
        try:
            response = self._client.get_object(
                Bucket=self._bucket_name,
                Key=storage_path,
            )
            return response["Body"]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                raise StorageError(
                    f"File not found in S3: s3://{self._bucket_name}/{storage_path}"
                ) from exc
            raise StorageError(
                f"Failed to open file from S3 "
                f"(bucket='{self._bucket_name}', "
                f"key='{storage_path}'): {exc}"
            ) from exc

    def delete_file(self, storage_path: str) -> bool:
        """
        Delete a file from the S3 bucket.

        Args:
            storage_path: The S3 object key returned by save_file().

        Returns:
            bool: True if the file was deleted, False if it did not exist.
        """
        try:
            self._client.delete_object(
                Bucket=self._bucket_name,
                Key=storage_path,
            )
            logger.info(
                "File deleted from s3://%s/%s",
                self._bucket_name,
                storage_path,
            )
            return True
        except ClientError as exc:
            # Treat NoSuchKey / 404 as "already deleted"
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                logger.warning(
                    "File not found in S3 for deletion: s3://%s/%s",
                    self._bucket_name,
                    storage_path,
                )
                return False
            raise StorageError(
                f"Failed to delete file from S3 "
                f"(bucket='{self._bucket_name}', "
                f"key='{storage_path}'): {exc}"
            ) from exc
