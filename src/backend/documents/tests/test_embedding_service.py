"""
Tests for the embedding service layer.

Covers all 5 public functions in
:mod:`documents.services.embedding_service`:

- :func:`~documents.services.embedding_service.generate_embedding`
- :func:`~documents.services.embedding_service.batch_generate_embeddings`
- :func:`~documents.services.embedding_service.generate_embeddings_for_document`
- :func:`~documents.services.embedding_service.batch_embed_chunks`
- :func:`~documents.services.embedding_service.reembed_chunk`
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import openai
from django.test import TestCase
from django.utils import timezone

from documents.models import Document, DocumentChunk
from documents.services.embedding_service import (
    SUB_BATCH_SIZE,
    batch_embed_chunks,
    batch_generate_embeddings,
    generate_embedding,
    generate_embeddings_for_document,
    reembed_chunk,
)
from tasks.models import ProcessingTask
from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_embedding(dim: int = 1536) -> list[float]:
    """Return a fake embedding vector of *dim* floats (all 0.1)."""
    return [0.1] * dim


def _mock_openai_response(
    texts: list[str],
    dim: int = 1536,
) -> MagicMock:
    """Build a mock OpenAI embeddings response for the given *texts*.

    Each text gets a unique embedding where the first element equals the
    index of the text in the list (to verify ordering).
    """
    mock_data = []
    for idx, _text in enumerate(texts):
        embedding = [float(idx + 1)] + [0.0] * (dim - 1)
        mock_item = MagicMock()
        mock_item.embedding = embedding
        mock_data.append(mock_item)

    mock_response = MagicMock()
    mock_response.data = mock_data
    return mock_response


# ---------------------------------------------------------------------------
# Tests — generate_embedding
# ---------------------------------------------------------------------------


class GenerateEmbeddingTests(TestCase):
    """Tests for :func:`generate_embedding`."""

    @patch("documents.services.embedding_service._get_openai_client")
    def test_generate_embedding_success(self, mock_get_client: MagicMock) -> None:
        """A valid text should return a 1536-dim embedding vector."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        fake_embedding = _make_fake_embedding()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=fake_embedding)]
        mock_client.embeddings.create.return_value = mock_response

        result = generate_embedding("Hello world")

        self.assertIsNotNone(result)
        assert result is not None  # Type narrowing.
        self.assertEqual(len(result), 1536)
        self.assertEqual(result, fake_embedding)

        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input="Hello world",
        )

    def test_generate_embedding_empty_text(self) -> None:
        """Empty or whitespace-only text should return None."""
        self.assertIsNone(generate_embedding(""))
        self.assertIsNone(generate_embedding("   "))
        self.assertIsNone(generate_embedding("\n\t"))

    @patch("documents.services.embedding_service._get_openai_client")
    def test_generate_embedding_rate_limit_retry(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """RateLimitError on first 2 calls should retry; 3rd should succeed."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        fake_embedding = _make_fake_embedding()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=fake_embedding)]

        mock_client.embeddings.create.side_effect = [
            openai.RateLimitError(
                "rate_limited",
                response=MagicMock(),
                body=None,
            ),
            openai.RateLimitError(
                "rate_limited",
                response=MagicMock(),
                body=None,
            ),
            mock_response,
        ]

        with patch("documents.services.embedding_service.time.sleep") as mock_sleep:
            result = generate_embedding("Hello world")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1536)
        self.assertEqual(mock_sleep.call_count, 2)
        # Exponential backoff: 2^0=1, 2^1=2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("documents.services.embedding_service._get_openai_client")
    def test_generate_embedding_rate_limit_exhausted(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """All retries exhausted on RateLimitError should return None."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.embeddings.create.side_effect = openai.RateLimitError(
            "rate_limited",
            response=MagicMock(),
            body=None,
        )

        with patch("documents.services.embedding_service.time.sleep"):
            result = generate_embedding("Hello world")

        self.assertIsNone(result)

    @patch("documents.services.embedding_service._get_openai_client")
    def test_generate_embedding_api_error(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """An APIError should return None without retry."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.embeddings.create.side_effect = openai.APIError(
            "api_error",
            request=MagicMock(),
            body=None,
        )

        result = generate_embedding("Hello world")

        self.assertIsNone(result)
        # Should only be called once (no retry for non-rate-limit errors).
        mock_client.embeddings.create.assert_called_once()

    @patch("documents.services.embedding_service._get_openai_client")
    def test_generate_embedding_authentication_error(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """An AuthenticationError should return None."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.embeddings.create.side_effect = openai.AuthenticationError(
            "auth_error",
            response=MagicMock(),
            body=None,
        )

        result = generate_embedding("Hello world")

        self.assertIsNone(result)

    @patch("documents.services.embedding_service._get_openai_client")
    def test_generate_embedding_connection_error(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """An APIConnectionError should return None."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.embeddings.create.side_effect = openai.APIConnectionError(
            message="connection_error",
            request=MagicMock(),
        )

        result = generate_embedding("Hello world")

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests — batch_generate_embeddings
# ---------------------------------------------------------------------------


class BatchGenerateEmbeddingsTests(TestCase):
    """Tests for :func:`batch_generate_embeddings`."""

    @patch("documents.services.embedding_service._get_openai_client")
    def test_batch_generate_embeddings_success(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """3 texts should return 3 embeddings in the correct order."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        texts = ["First text", "Second text", "Third text"]
        mock_response = _mock_openai_response(texts)
        mock_client.embeddings.create.return_value = mock_response

        results = batch_generate_embeddings(texts)

        self.assertEqual(len(results), 3)
        for idx, result in enumerate(results):
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result[0], float(idx + 1))
            self.assertEqual(len(result), 1536)

    @patch("documents.services.embedding_service._get_openai_client")
    def test_batch_generate_embeddings_mixed_failures(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """Empty texts in the batch should produce None at correct positions."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        texts = ["Valid text", "", "Another valid", "   "]
        valid_texts = ["Valid text", "Another valid"]
        mock_response = _mock_openai_response(valid_texts)
        mock_client.embeddings.create.return_value = mock_response

        results = batch_generate_embeddings(texts)

        self.assertEqual(len(results), 4)
        # Index 0: valid
        self.assertIsNotNone(results[0])
        # Index 1: empty string → None
        self.assertIsNone(results[1])
        # Index 2: valid
        self.assertIsNotNone(results[2])
        # Index 3: whitespace → None
        self.assertIsNone(results[3])

    @patch("documents.services.embedding_service._get_openai_client")
    def test_batch_generate_embeddings_sub_batch_splitting(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """120 texts should split into 3 sub-batches (50, 50, 20)."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        texts = [f"Text {i}" for i in range(120)]

        # Track global index across sub-batches.
        global_idx = 0

        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            nonlocal global_idx
            input_texts = kwargs.get("input", [])
            assert isinstance(input_texts, list)
            # Build response where first element tracks global position.
            mock_data = []
            for _ in input_texts:
                embedding = [float(global_idx + 1)] + [0.0] * 1535
                mock_item = MagicMock()
                mock_item.embedding = embedding
                mock_data.append(mock_item)
                global_idx += 1
            mock_response = MagicMock()
            mock_response.data = mock_data
            return mock_response

        mock_client.embeddings.create.side_effect = side_effect

        results = batch_generate_embeddings(texts)

        self.assertEqual(len(results), 120)
        # Verify all results are non-None and in correct global order.
        for idx, result in enumerate(results):
            self.assertIsNotNone(result, f"Result at index {idx} is None")
            assert result is not None
            self.assertEqual(result[0], float(idx + 1))

        # Should have been called 3 times (50 + 50 + 20).
        self.assertEqual(mock_client.embeddings.create.call_count, 3)

    @patch("documents.services.embedding_service._get_openai_client")
    def test_batch_generate_embeddings_all_empty(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """All empty texts should return all Nones without API calls."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        results = batch_generate_embeddings(["", "   ", ""])

        self.assertEqual(len(results), 3)
        self.assertIsNone(results[0])
        self.assertIsNone(results[1])
        self.assertIsNone(results[2])
        mock_client.embeddings.create.assert_not_called()

    @patch("documents.services.embedding_service._get_openai_client")
    def test_batch_generate_embeddings_rate_limit_retry(
        self,
        mock_get_client: MagicMock,
    ) -> None:
        """RateLimitError on sub-batch should retry with backoff."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        texts = ["Hello", "World"]
        mock_response = _mock_openai_response(texts)

        mock_client.embeddings.create.side_effect = [
            openai.RateLimitError(
                "rate_limited",
                response=MagicMock(),
                body=None,
            ),
            mock_response,
        ]

        with patch("documents.services.embedding_service.time.sleep") as mock_sleep:
            results = batch_generate_embeddings(texts)

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        mock_sleep.assert_called_once_with(1.0)


# ---------------------------------------------------------------------------
# Tests — generate_embeddings_for_document
# ---------------------------------------------------------------------------


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

        # Mock batch_generate_embeddings to return embeddings for all 3.
        mock_batch.return_value = [_make_fake_embedding() for _ in range(3)]

        generate_embeddings_for_document(str(self.document.id))

        # Verify all chunks now have embeddings.
        for chunk in chunks:
            chunk.refresh_from_db()
            self.assertIsNotNone(chunk.embedding)
            self.assertEqual(len(chunk.embedding), 1536)

        # Verify ProcessingTask was created and marked completed.
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
        # Should not raise.
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

        # Return None for the middle chunk.
        mock_batch.return_value = [
            _make_fake_embedding(),
            None,
            _make_fake_embedding(),
        ]

        generate_embeddings_for_document(str(self.document.id))

        # Verify task completed (partial failures don't fail the task).
        task = ProcessingTask.objects.get(
            document=self.document,
            task_type="embed",
        )
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.progress, 100)

        # Chunks 0 and 2 should have embeddings; chunk 1 should not.
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
        # Create enough chunks to require multiple batches.
        chunk_count = SUB_BATCH_SIZE + 10  # 60 chunks → 2 batches.
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

        # Verify all chunks got embeddings.
        embedded_count = DocumentChunk.objects.filter(
            document=self.document,
            embedding__isnull=False,
        ).count()
        self.assertEqual(embedded_count, chunk_count)


# ---------------------------------------------------------------------------
# Tests — batch_embed_chunks
# ---------------------------------------------------------------------------


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
        """5 chunks: 2 already embedded, 2 succeed, 1 fails → correct counts."""
        # Chunks 0, 1: already embedded (skipped).
        chunk0 = self._create_chunk(0, has_embedding=True)
        chunk1 = self._create_chunk(1, has_embedding=True)
        # Chunks 2, 3: will succeed.
        chunk2 = self._create_chunk(2)
        chunk3 = self._create_chunk(3)
        # Chunk 4: will fail.
        chunk4 = self._create_chunk(4)

        chunk_ids = [
            str(chunk.id) for chunk in [chunk0, chunk1, chunk2, chunk3, chunk4]
        ]

        # Mock: 2 succeed, 1 fails.
        mock_batch.return_value = [
            _make_fake_embedding(),
            _make_fake_embedding(),
            None,
        ]

        result = batch_embed_chunks(chunk_ids)

        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["failed"], 1)

        # Verify chunks 2 and 3 got embeddings.
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
    def test_batch_embed_chunks_all_already_embedded(
        self,
        mock_batch: MagicMock,
    ) -> None:
        """All chunks already embedded → no API calls."""
        chunk0 = self._create_chunk(0, has_embedding=True)
        chunk1 = self._create_chunk(1, has_embedding=True)

        result = batch_embed_chunks([str(chunk0.id), str(chunk1.id)])

        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["failed"], 0)
        mock_batch.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — reembed_chunk
# ---------------------------------------------------------------------------


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
    def test_reembed_chunk_success(
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
            embedding=_make_fake_embedding(),  # Existing embedding.
        )

        new_embedding = [0.5] * 1536
        mock_generate.return_value = new_embedding

        result = reembed_chunk(str(chunk.id))

        self.assertTrue(result["embedding_updated"])
        self.assertEqual(result["chunk_id"], str(chunk.id))

        chunk.refresh_from_db()
        # pgvector's VectorField returns a list-like object; compare element-wise.
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
