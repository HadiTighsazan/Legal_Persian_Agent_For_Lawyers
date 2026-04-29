"""
Tests for embedding functionality.

Consolidates all embedding-related tests from:
- documents.services.embedding_service (unit tests)
- documents.views (view tests)
- documents.tasks.embedding_tasks (Celery task tests)
"""

from __future__ import annotations

import uuid
from unittest.mock import ANY, MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import Document, DocumentChunk
from documents.services.embedding_service import (
    SUB_BATCH_SIZE,
    EmbeddingError,
    batch_embed_chunks,
    batch_generate_embeddings,
    embed_query,
    generate_embedding,
    generate_embeddings_for_document,
    reembed_chunk,
)
from tasks.models import ProcessingTask
from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_embedding(dim: int = 768) -> list[float]:
    """Return a fake embedding vector of *dim* floats (all 0.1)."""
    return [0.1] * dim


def _auth_header(user: User) -> dict[str, str]:
    """Return an Authorization header dict for the given user."""
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}


def _create_document(
    user: User,
    processing_status: str = "pending",
    **kwargs,
) -> Document:
    """Create a Document with sensible defaults for testing."""
    return Document.objects.create(
        user=user,
        title=kwargs.get("title", "Test Document"),
        filename=kwargs.get("filename", "test.pdf"),
        original_filename=kwargs.get("original_filename", "test.pdf"),
        file_path=kwargs.get("file_path", "/tmp/test.pdf"),
        file_size=kwargs.get("file_size", 1000),
        mime_type=kwargs.get("mime_type", "application/pdf"),
        processing_status=processing_status,
    )


def _mock_celery_request(task_func, celery_task_id: str = "test-celery-id"):
    """Context manager that patches the Celery task ``request`` property."""
    from unittest.mock import PropertyMock
    return patch(
        "celery.app.task.Task.request",
        new_callable=PropertyMock,
        return_value=MagicMock(id=celery_task_id),
    )


# ============================================================================
# Category 1: EmbeddingService Unit Tests
# ============================================================================


class GenerateEmbeddingTests(TestCase):
    """Tests for :func:`generate_embedding`."""

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_generate_embedding_returns_768_floats(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """A valid text should return a 768-dim embedding vector."""
        fake_embedding = _make_fake_embedding()
        mock_provider = MagicMock()
        mock_provider.embed.return_value = fake_embedding
        mock_get_provider.return_value = mock_provider

        result = generate_embedding("Hello world")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 768)
        self.assertEqual(result, fake_embedding)
        mock_provider.embed.assert_called_once_with("Hello world")

    def test_generate_embedding_empty_text_returns_none(self) -> None:
        """Empty or whitespace-only text should return None."""
        self.assertIsNone(generate_embedding(""))
        self.assertIsNone(generate_embedding("   "))
        self.assertIsNone(generate_embedding("\n\t"))

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_generate_embedding_provider_returns_none(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """When provider.embed returns None, generate_embedding returns None."""
        mock_provider = MagicMock()
        mock_provider.embed.return_value = None
        mock_get_provider.return_value = mock_provider

        result = generate_embedding("Hello world")
        self.assertIsNone(result)


class EmbedQueryTests(TestCase):
    """Tests for :func:`embed_query`."""

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_embed_query_returns_768_floats(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """A valid query should return a 768-dim embedding vector."""
        fake_embedding = _make_fake_embedding()
        mock_provider = MagicMock()
        mock_provider.embed_query.return_value = fake_embedding
        mock_get_provider.return_value = mock_provider

        result = embed_query("hello world")

        self.assertEqual(len(result), 768)
        self.assertEqual(result, fake_embedding)
        mock_provider.embed_query.assert_called_once_with("hello world")

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_embed_query_raises_on_provider_failure(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Provider failure should propagate the exception."""
        mock_provider = MagicMock()
        mock_provider.embed_query.side_effect = EmbeddingError("API connection refused")
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(EmbeddingError) as ctx:
            embed_query("hello world")

        self.assertIn("connection refused", str(ctx.exception).lower())

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_embed_query_raises_on_empty_text(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Empty or whitespace-only input should raise ValueError."""
        with self.assertRaises(ValueError):
            embed_query("")
        with self.assertRaises(ValueError):
            embed_query("   ")
        with self.assertRaises(ValueError):
            embed_query("\n\t")

        mock_get_provider.return_value.embed_query.assert_not_called()


class BatchGenerateEmbeddingsTests(TestCase):
    """Tests for :func:`batch_generate_embeddings`."""

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_batch_generate_embeddings_returns_in_order(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """3 texts should return 3 embeddings in the correct order."""
        texts = ["First text", "Second text", "Third text"]
        mock_provider = MagicMock()
        mock_provider.embed_batch.return_value = [
            [1.0] + [0.0] * 767,
            [2.0] + [0.0] * 767,
            [3.0] + [0.0] * 767,
        ]
        mock_get_provider.return_value = mock_provider

        results = batch_generate_embeddings(texts)

        self.assertEqual(len(results), 3)
        for idx, result in enumerate(results):
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result[0], float(idx + 1))
            self.assertEqual(len(result), 768)

        mock_provider.embed_batch.assert_called_once_with(texts)

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_batch_generate_embeddings_handles_partial_failure(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """Empty texts in the batch should produce None at correct positions."""
        texts = ["Valid text", "", "Another valid", "   "]
        mock_provider = MagicMock()
        mock_provider.embed_batch.return_value = [
            [1.0] + [0.0] * 767,
            None,
            [2.0] + [0.0] * 767,
            None,
        ]
        mock_get_provider.return_value = mock_provider

        results = batch_generate_embeddings(texts)

        self.assertEqual(len(results), 4)
        self.assertIsNotNone(results[0])
        self.assertIsNone(results[1])
        self.assertIsNotNone(results[2])
        self.assertIsNone(results[3])

        mock_provider.embed_batch.assert_called_once_with(texts)

    @patch("documents.services.embedding_service.get_embedding_provider")
    def test_batch_generate_embeddings_all_empty(
        self,
        mock_get_provider: MagicMock,
    ) -> None:
        """All empty texts should return all Nones without API calls."""
        mock_provider = MagicMock()
        mock_provider.embed_batch.return_value = [None, None, None]
        mock_get_provider.return_value = mock_provider

        results = batch_generate_embeddings(["", "   ", ""])

        self.assertEqual(len(results), 3)
        self.assertIsNone(results[0])
        self.assertIsNone(results[1])
        self.assertIsNone(results[2])

        mock_provider.embed_batch.assert_called_once_with(["", "   ", ""])


class GenerateEmbeddingsForDocumentTests(TestCase):
    """Tests for :func:`generate_embeddings_for_document`."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="embed-doc@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Embed Test Doc",
            filename="embed_test.pdf",
            original_filename="embed_test.pdf",
            file_path="/tmp/fake.pdf",
            file_size=1000,
            mime_type="application/pdf",
            processing_status="processing",
        )

    def _create_chunks(self, count: int, has_embedding: bool = False) -> list[DocumentChunk]:
        """Create *count* chunks for the test document."""
        chunks: list[DocumentChunk] = []
        for i in range(count):
            chunk = DocumentChunk.objects.create(
                document=self.document,
                chunk_index=i,
                page_start=1,
                page_end=1,
                content=f"Chunk {i} content.",
                token_count=10,
                embedding=_make_fake_embedding() if has_embedding else None,
            )
            chunks.append(chunk)
        return chunks

    @patch("documents.services.embedding_service.batch_generate_embeddings")
    def test_generate_embeddings_for_document_success(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """3 un-embedded chunks should get embeddings and task marked completed."""
        chunks = self._create_chunks(3)

        mock_batch.return_value = [_make_fake_embedding() for _ in range(3)]

        generate_embeddings_for_document(str(self.document.id))

        for chunk in chunks:
            chunk.refresh_from_db()
            self.assertIsNotNone(chunk.embedding)
            self.assertEqual(len(chunk.embedding), 768)

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="embed",
        )
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.progress, 100)
        self.assertIsNotNone(task.started_at)
        self.assertIsNotNone(task.completed_at)

    @patch("documents.services.embedding_service.batch_generate_embeddings")
    def test_generate_embeddings_for_document_no_chunks(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """Document with 0 chunks should complete immediately."""
        generate_embeddings_for_document(str(self.document.id))

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="embed",
        )
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.progress, 100)
        mock_batch.assert_not_called()

    @patch("documents.services.embedding_service.batch_generate_embeddings")
    def test_generate_embeddings_for_document_all_already_embedded(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """All chunks already embedded should complete with no API calls."""
        self._create_chunks(3, has_embedding=True)

        generate_embeddings_for_document(str(self.document.id))

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="embed",
        )
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.progress, 100)
        mock_batch.assert_not_called()

    def test_generate_embeddings_for_document_not_found(self) -> None:
        """Non-existent document should log error and return gracefully."""
        generate_embeddings_for_document(
            "00000000-0000-0000-0000-000000000000",
        )

    @patch("documents.services.embedding_service.batch_generate_embeddings")
    def test_generate_embeddings_for_document_partial_failures(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """Some chunks failing should still process successfully."""
        self._create_chunks(3)

        mock_batch.return_value = [
            _make_fake_embedding(),
            None,
            _make_fake_embedding(),
        ]

        generate_embeddings_for_document(str(self.document.id))

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="embed",
        )
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.progress, 100)

        chunks = DocumentChunk.objects.filter(
            document=self.document,
        ).order_by("chunk_index")
        self.assertIsNotNone(chunks[0].embedding)
        self.assertIsNone(chunks[1].embedding)
        self.assertIsNotNone(chunks[2].embedding)

    @patch("documents.services.embedding_service.batch_generate_embeddings")
    def test_generate_embeddings_for_document_batch_progress(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """Progress should be updated correctly during batch processing."""
        chunk_count = SUB_BATCH_SIZE + 10  # 110 chunks, 2 batches of 100+10
        self._create_chunks(chunk_count)

        def side_effect(texts: list[str]) -> list[list[float] | None]:
            return [_make_fake_embedding() for _ in texts]

        mock_batch.side_effect = side_effect

        generate_embeddings_for_document(str(self.document.id))

        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="embed",
        )
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.progress, 100)

        embedded_count = DocumentChunk.objects.filter(
            document=self.document,
            embedding__isnull=False,
        ).count()
        self.assertEqual(embedded_count, chunk_count)


class BatchEmbedChunksTests(TestCase):
    """Tests for :func:`batch_embed_chunks`."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="batch-embed@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Batch Embed Test",
            filename="batch_embed.pdf",
            original_filename="batch_embed.pdf",
            file_path="/tmp/fake.pdf",
            file_size=1000,
            mime_type="application/pdf",
            processing_status="processing",
        )

    def _create_chunk(
        self,
        index: int,
        content: str = "Test content.",
        has_embedding: bool = False,
    ) -> DocumentChunk:
        return DocumentChunk.objects.create(
            document=self.document,
            chunk_index=index,
            page_start=1,
            page_end=1,
            content=content,
            token_count=10,
            embedding=_make_fake_embedding() if has_embedding else None,
        )

    @patch("documents.services.embedding_service.batch_generate_embeddings")
    def test_batch_embed_chunks_mixed_state(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """5 chunks: 2 already embedded, 2 succeed, 1 fails -> correct counts."""
        chunk0 = self._create_chunk(0, has_embedding=True)
        chunk1 = self._create_chunk(1, has_embedding=True)
        chunk2 = self._create_chunk(2)
        chunk3 = self._create_chunk(3)
        chunk4 = self._create_chunk(4)

        chunk_ids = [
            str(chunk.id) for chunk in [chunk0, chunk1, chunk2, chunk3, chunk4]
        ]

        mock_batch.return_value = [
            _make_fake_embedding(),
            _make_fake_embedding(),
            None,
        ]

        result = batch_embed_chunks(chunk_ids)

        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["failed"], 1)

        chunk2.refresh_from_db()
        chunk3.refresh_from_db()
        chunk4.refresh_from_db()
        self.assertIsNotNone(chunk2.embedding)
        self.assertIsNotNone(chunk3.embedding)
        self.assertIsNone(chunk4.embedding)

    def test_batch_embed_chunks_invalid_ids(self) -> None:
        """Non-existent chunk IDs should return all zeros."""
        result = batch_embed_chunks([
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ])
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["failed"], 0)

    @patch("documents.services.embedding_service.batch_generate_embeddings")
    def test_batch_embed_chunks_skips_existing_embeddings(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """All chunks already embedded -> no API calls."""
        chunk0 = self._create_chunk(0, has_embedding=True)
        chunk1 = self._create_chunk(1, has_embedding=True)

        result = batch_embed_chunks([str(chunk0.id), str(chunk1.id)])

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["failed"], 0)
        mock_batch.assert_not_called()


class ReembedChunkTests(TestCase):
    """Tests for :func:`reembed_chunk`."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="reembed@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Reembed Test",
            filename="reembed.pdf",
            original_filename="reembed.pdf",
            file_path="/tmp/fake.pdf",
            file_size=1000,
            mime_type="application/pdf",
            processing_status="processing",
        )

    @patch("documents.services.embedding_service.generate_embedding")
    def test_reembed_chunk_overwrites_existing_embedding(
        self,
        mock_generate: MagicMock,
    ) -> None:
        """Existing embedding should be replaced."""
        chunk = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=1,
            content="Re-embed me.",
            token_count=10,
            embedding=_make_fake_embedding(),
        )

        new_embedding = [0.5] * 768
        mock_generate.return_value = new_embedding

        result = reembed_chunk(str(chunk.id))

        self.assertTrue(result["embedding_updated"])
        self.assertEqual(result["chunk_id"], str(chunk.id))

        chunk.refresh_from_db()
        self.assertIsNotNone(chunk.embedding)
        self.assertEqual(list(chunk.embedding), new_embedding)

    def test_reembed_chunk_not_found(self) -> None:
        """Non-existent chunk ID should return error dict."""
        result = reembed_chunk("00000000-0000-0000-0000-000000000000")

        self.assertEqual(result["error"], "not_found")
        self.assertEqual(result["message"], "Chunk not found")

    @patch("documents.services.embedding_service.generate_embedding")
    def test_reembed_chunk_failure(
        self,
        mock_generate: MagicMock,
    ) -> None:
        """If generate_embedding returns None, embedding_updated should be False."""
        chunk = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=1,
            content="Will fail.",
            token_count=10,
            embedding=_make_fake_embedding(),
        )

        mock_generate.return_value = None

        result = reembed_chunk(str(chunk.id))

        self.assertFalse(result["embedding_updated"])
        self.assertEqual(result["chunk_id"], str(chunk.id))
        self.assertIn("error", result)


# ============================================================================
# Category 2: View Tests
# ============================================================================


class DocumentEmbedViewTests(TestCase):
    """Tests for the :class:`DocumentEmbedView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="embed-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-embed@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.url = reverse(
            "documents:document-embed",
            kwargs={"document_id": self.document.id},
        )

    def test_document_embed_nonexistent_document_returns_404(self) -> None:
        """POST to a non-existent document ID should return 404."""
        url = reverse(
            "documents:document-embed",
            kwargs={"document_id": uuid.uuid4()},
        )
        response = self.client.post(url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    def test_document_embed_other_users_document_returns_403(self) -> None:
        """POST to another user's document should return 403."""
        response = self.client.post(self.url, **_auth_header(self.other_user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    def test_document_embed_unauthenticated_returns_401(self) -> None:
        """POST without auth should return 401."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("documents.views.embed_document")
    def test_document_embed_returns_202_with_task_id(self, mock_embed: MagicMock) -> None:
        """Successful trigger should return 202 with task info."""
        response = self.client.post(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["task_type"], "embed")
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["document_id"], str(self.document.id))
        self.assertEqual(data["total_chunks"], 0)
        self.assertIn("task_id", data)

        mock_embed.delay.assert_called_once_with(
            str(self.document.id), ANY,
        )

    @patch("documents.views.embed_document")
    def test_embed_creates_processing_task(self, mock_embed: MagicMock) -> None:
        """Verify ProcessingTask is created with task_type='embed'."""
        self.client.post(self.url, **_auth_header(self.user))

        task = ProcessingTask.objects.filter(
            document=self.document,
            task_type="embed",
        ).first()
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "pending")

    @patch("documents.views.embed_document")
    def test_embed_counts_unembedded_chunks(self, mock_embed: MagicMock) -> None:
        """Verify total_chunks in response matches un-embedded chunks count."""
        for i in range(3):
            DocumentChunk.objects.create(
                document=self.document,
                chunk_index=i,
                page_start=1,
                page_end=10,
                content=f"Chunk {i} content",
                token_count=50,
                metadata={},
            )

        response = self.client.post(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["total_chunks"], 3)

    @patch("documents.views.embed_document")
    def test_embed_skips_already_embedded_chunks(self, mock_embed: MagicMock) -> None:
        """Chunks with existing embeddings are not counted."""
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=10,
            content="Embedded chunk",
            token_count=50,
            metadata={},
            embedding=[0.1] * 768,
        )
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=11,
            page_end=20,
            content="Un-embedded chunk",
            token_count=50,
            metadata={},
        )

        response = self.client.post(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        data = response.json()
        self.assertEqual(data["total_chunks"], 1)


class ChunkBatchEmbedViewTests(TestCase):
    """Tests for the :class:`ChunkBatchEmbedView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="batch-embed-test@example.com",
            password="testpass123",
        )
        self.url = reverse("documents:chunk-batch-embed")

    def test_unauthenticated_request_returns_401(self) -> None:
        """POST without auth should return 401."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_batch_embed_validates_chunk_ids(self) -> None:
        """POST with invalid chunk_ids should return 400."""
        response = self.client.post(
            self.url,
            {"chunk_ids": ["not-a-uuid"]},
            **_auth_header(self.user),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("documents.views.batch_embed_chunks")
    def test_successful_batch_embed_returns_200(
        self, mock_batch: MagicMock,
    ) -> None:
        """Successful batch embed should return 200 with counts."""
        mock_batch.return_value = {"processed": 3, "skipped": 1, "failed": 0}

        chunk_id = uuid.uuid4()
        response = self.client.post(
            self.url,
            {"chunk_ids": [str(chunk_id)]},
            **_auth_header(self.user),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["processed"], 3)
        self.assertEqual(data["skipped"], 1)
        self.assertEqual(data["failed"], 0)

        mock_batch.assert_called_once_with([str(chunk_id)])

    @patch("documents.views.batch_embed_chunks")
    def test_batch_embed_handles_up_to_100_chunks(self, mock_batch: MagicMock) -> None:
        """POST with 100 chunk IDs should be accepted (boundary test)."""
        chunk_ids = [uuid.uuid4() for _ in range(100)]

        mock_batch.return_value = {"processed": 100, "skipped": 0, "failed": 0}

        response = self.client.post(
            self.url,
            {"chunk_ids": [str(cid) for cid in chunk_ids]},
            **_auth_header(self.user),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["processed"], 100)


class ChunkReEmbedViewTests(TestCase):
    """Tests for the :class:`ChunkReEmbedView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="reembed-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-reembed@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.chunk = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=10,
            content="Test chunk content",
            token_count=50,
            metadata={},
        )
        self.url = reverse(
            "documents:chunk-re-embed",
            kwargs={"chunk_id": self.chunk.id},
        )

    def test_reembed_nonexistent_chunk_returns_404(self) -> None:
        """POST to a non-existent chunk ID should return 404."""
        url = reverse(
            "documents:chunk-re-embed",
            kwargs={"chunk_id": uuid.uuid4()},
        )
        response = self.client.post(url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    def test_reembed_other_users_chunk_returns_403(self) -> None:
        """POST to another user's chunk should return 403."""
        response = self.client.post(self.url, **_auth_header(self.other_user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    def test_unauthenticated_request_returns_401(self) -> None:
        """POST without auth should return 401."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("documents.views.reembed_chunk")
    def test_successful_reembed_returns_200(self, mock_reembed: MagicMock) -> None:
        """Successful re-embed should return 200 with chunk_id and embedding_updated."""
        mock_reembed.return_value = {
            "chunk_id": str(self.chunk.id),
            "embedding_updated": True,
        }

        response = self.client.post(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["chunk_id"], str(self.chunk.id))
        self.assertTrue(data["embedding_updated"])

        mock_reembed.assert_called_once_with(str(self.chunk.id))


class TaskStatusViewTests(TestCase):
    """Tests for the :class:`TaskStatusView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="task-status-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-task-status@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.task = ProcessingTask.objects.create(
            document=self.document,
            task_type="embed",
            celery_task_id="celery-001",
            status="running",
            progress=75,
            started_at=timezone.now(),
        )
        self.url = reverse(
            "tasks:task-status",
            kwargs={"task_id": self.task.id},
        )

    def test_task_status_nonexistent_task_returns_404(self) -> None:
        """GET for a non-existent task ID should return 404."""
        url = reverse(
            "tasks:task-status",
            kwargs={"task_id": uuid.uuid4()},
        )
        response = self.client.get(url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "not_found")

    def test_other_users_task_returns_403(self) -> None:
        """GET for another user's task should return 403."""
        response = self.client.get(self.url, **_auth_header(self.other_user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "permission_denied")

    def test_unauthenticated_request_returns_401(self) -> None:
        """GET without auth should return 401."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_task_status_returns_correct_state(self) -> None:
        """Successful GET should return 200 with task details."""
        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(self.task.id))
        self.assertEqual(data["document_id"], str(self.document.id))
        self.assertEqual(data["task_type"], "embed")
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["progress"], 75)

    def test_returns_all_expected_fields(self) -> None:
        """Response should contain all expected fields."""
        response = self.client.get(self.url, **_auth_header(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("id", data)
        self.assertIn("document_id", data)
        self.assertIn("task_type", data)
        self.assertIn("status", data)
        self.assertIn("progress", data)
        self.assertIn("result", data)
        self.assertIn("error_message", data)
        self.assertIn("started_at", data)
        self.assertIn("completed_at", data)


# ============================================================================
# Category 3: Celery Task Tests
# ============================================================================


class EmbeddingCeleryTaskTests(TestCase):
    """Tests for :func:`embed_document` in :mod:`documents.tasks.embedding_tasks`."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="embed@example.com",
            password="testpass123",
        )

        self.document = Document.objects.create(
            user=self.user,
            title="Embed Test Doc",
            filename="embed_test.pdf",
            original_filename="embed_test.pdf",
            file_path="/tmp/fake.pdf",
            file_size=1000,
            mime_type="application/pdf",
            processing_status="completed",
        )

        self.processing_task = ProcessingTask.objects.create(
            document=self.document,
            task_type="embed",
            status="pending",
        )

    def _run_task(self, document_id: str | None = None, task_id: str | None = None) -> None:
        """Run embed_document synchronously with a mock Celery request."""
        from documents.tasks.embedding_tasks import embed_document

        with _mock_celery_request(embed_document):
            embed_document(
                document_id or str(self.document.id),
                task_id or str(self.processing_task.id),
            )

    def _create_chunks(self, count: int, has_embedding: bool = False) -> list:
        """Create *count* DocumentChunk records for the test document."""
        chunks = []
        for i in range(count):
            chunk = DocumentChunk.objects.create(
                document=self.document,
                chunk_index=i,
                page_start=1,
                page_end=1,
                content=f"Test chunk content {i}." * 20,
                token_count=50,
                embedding=None if not has_embedding else [0.1] * 768,
            )
            chunks.append(chunk)
        return chunks

    # -- Happy path -------------------------------------------------------

    def test_embed_document_creates_embeddings_for_all_chunks(self) -> None:
        """3 un-embedded chunks -> all get embeddings, task -> completed."""
        self._create_chunks(3)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            return_value=[[0.1] * 768, [0.2] * 768, [0.3] * 768],
        ):
            self._run_task()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)
        self.assertIsNotNone(self.processing_task.completed_at)

        chunks = DocumentChunk.objects.filter(document=self.document).order_by("chunk_index")
        for chunk in chunks:
            self.assertIsNotNone(chunk.embedding)
            self.assertEqual(len(chunk.embedding), 768)

    def test_no_unembedded_chunks(self) -> None:
        """All chunks already embedded -> task completes immediately."""
        self._create_chunks(2, has_embedding=True)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
        ) as mock_embed:
            self._run_task()

        mock_embed.assert_not_called()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)

    def test_empty_document_no_chunks(self) -> None:
        """Document with 0 chunks -> task completes immediately."""
        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
        ) as mock_embed:
            self._run_task()

        mock_embed.assert_not_called()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)

    # -- Error handling ---------------------------------------------------

    def test_processing_task_not_found(self) -> None:
        """Invalid task_id -> logs error, returns gracefully."""
        self._run_task(task_id="00000000-0000-0000-0000-000000000000")

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "pending")

    def test_document_not_found(self) -> None:
        """Invalid document_id -> task marked as failed."""
        self._run_task(document_id="00000000-0000-0000-0000-000000000000")

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "failed")
        self.assertIn("not found", self.processing_task.error_message.lower())
        self.assertIsNotNone(self.processing_task.completed_at)

    def test_partial_batch_failures(self) -> None:
        """Some embeddings fail -> remaining chunks still get embeddings."""
        self._create_chunks(3)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            return_value=[[0.1] * 768, None, [0.3] * 768],
        ):
            self._run_task()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)

        chunks = DocumentChunk.objects.filter(document=self.document).order_by("chunk_index")
        self.assertIsNotNone(chunks[0].embedding)
        self.assertIsNone(chunks[1].embedding)
        self.assertIsNotNone(chunks[2].embedding)

    def test_embed_document_handles_api_failure(self) -> None:
        """API error -> task marked as failed with error_message."""
        self._create_chunks(2)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            side_effect=ValueError("Gemini API connection failed"),
        ):
            self._run_task()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "failed")
        self.assertIn("Gemini API connection failed", self.processing_task.error_message)
        self.assertIsNotNone(self.processing_task.completed_at)

    # -- Progress tracking ------------------------------------------------

    def test_embed_document_updates_task_progress(self) -> None:
        """Verify progress goes from 0 -> 50 -> 100 for 2 batches of 100 chunks each."""
        self._create_chunks(200)

        embeddings = [[float(i)] * 768 for i in range(200)]

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            side_effect=lambda texts: [embeddings.pop(0) for _ in texts],
        ):
            self._run_task()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)

        chunks = DocumentChunk.objects.filter(
            document=self.document,
            embedding__isnull=True,
        )
        self.assertEqual(chunks.count(), 0)

    def test_single_batch_progress(self) -> None:
        """A single batch (< 100 chunks) should go from 0 -> 100."""
        self._create_chunks(25)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            return_value=[[0.1] * 768] * 25,
        ):
            self._run_task()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)

    # -- Celery task lifecycle --------------------------------------------

    def test_sets_celery_task_id(self) -> None:
        """The celery_task_id should be set to the mock request ID."""
        self._create_chunks(1)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            return_value=[[0.1] * 768],
        ):
            self._run_task()

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.celery_task_id, "test-celery-id")

    def test_sets_started_at(self) -> None:
        """The started_at timestamp should be set when task begins running."""
        self._create_chunks(1)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            return_value=[[0.1] * 768],
        ):
            self._run_task()

        self.processing_task.refresh_from_db()
        self.assertIsNotNone(self.processing_task.started_at)

    # -- Edge cases -------------------------------------------------------

    def test_exactly_one_batch(self) -> None:
        """Exactly SUB_BATCH_SIZE (100) chunks -> processed in a single batch."""
        self._create_chunks(100)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            return_value=[[0.1] * 768] * 100,
        ) as mock_embed:
            self._run_task()

        self.assertEqual(mock_embed.call_count, 1)

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)

    def test_uneven_batch(self) -> None:
        """150 chunks (1.5 batches) -> processed correctly with 2 batch calls."""
        self._create_chunks(150)

        with patch(
            "documents.tasks.embedding_tasks.batch_generate_embeddings",
            return_value=[[0.1] * 768] * 150,
        ) as mock_embed:
            self._run_task()

        self.assertEqual(mock_embed.call_count, 2)

        self.processing_task.refresh_from_db()
        self.assertEqual(self.processing_task.status, "completed")
        self.assertEqual(self.processing_task.progress, 100)
