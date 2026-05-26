"""
Unit tests for embedding provider implementations.

Tests cover:
- :class:`~providers.gemini_embedding.GeminiEmbeddingProvider`
- :class:`~providers.openai_embedding.OpenAIEmbeddingProvider`
- :class:`~providers.ollama_embedding.OllamaEmbeddingProvider`

All external HTTP/API calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase, override_settings

from providers.base import EmbeddingBatchError
from providers.gemini_embedding import GeminiEmbeddingProvider
from providers.openai_embedding import OpenAIEmbeddingProvider
from providers.ollama_embedding import OllamaEmbeddingProvider


@override_settings(
    GOOGLE_API_KEY="test-gemini-key",
    GEMINI_EMBEDDING_MODEL="gemini-embedding-001",
)
class GeminiEmbeddingProviderTests(TestCase):
    """Tests for :class:`GeminiEmbeddingProvider`."""

    def setUp(self) -> None:
        self.provider = GeminiEmbeddingProvider()
        # Replace the real session with a mock so no real HTTP calls are made.
        self.mock_session = MagicMock(spec=requests.Session)
        self.provider._session = self.mock_session

    def test_dimensions_property(self) -> None:
        """dimensions returns 768."""
        self.assertEqual(self.provider.dimensions, 768)

    def test_session_property_lazy_init(self) -> None:
        """The ``session`` property lazily creates a ``Session`` with an ``HTTPAdapter``."""
        # Reset _session to None to force lazy init
        self.provider._session = None
        sess = self.provider.session
        self.assertIsNotNone(sess)
        # Calling again returns the same instance
        self.assertIs(sess, self.provider.session)

    # -- embed() tests ----------------------------------------------------

    def test_embed_returns_embedding(self) -> None:
        """A valid text returns an embedding vector."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embedding": {"values": [0.1] * 768},
        }
        self.mock_session.post.return_value = mock_response

        result = self.provider.embed("Hello world")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 768)
        self.mock_session.post.assert_called_once()

    def test_embed_empty_text_returns_none(self) -> None:
        """Empty or whitespace-only text returns None without API call."""
        self.assertIsNone(self.provider.embed(""))
        self.assertIsNone(self.provider.embed("   "))
        self.mock_session.post.assert_not_called()

    def test_embed_api_error_returns_none(self) -> None:
        """API error returns None after retries."""
        from requests.exceptions import ConnectionError
        self.mock_session.post.side_effect = ConnectionError("connection refused")

        with patch("providers.gemini_embedding.time.sleep"):
            result = self.provider.embed("Hello")

        self.assertIsNone(result)

    # -- embed_batch() tests ----------------------------------------------

    def test_embed_batch_returns_in_order(self) -> None:
        """Multiple texts return embeddings in correct order."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [
                {"values": [1.0] + [0.0] * 767},
                {"values": [2.0] + [0.0] * 767},
            ],
        }
        self.mock_session.post.return_value = mock_response

        results = self.provider.embed_batch(["First", "Second"])

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        assert results[0] is not None
        assert results[1] is not None
        self.assertEqual(results[0][0], 1.0)
        self.assertEqual(results[1][0], 2.0)

    def test_embed_batch_empty_texts(self) -> None:
        """Empty texts in batch produce None at correct positions."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [{"values": [1.0] + [0.0] * 767}],
        }
        self.mock_session.post.return_value = mock_response

        results = self.provider.embed_batch(["Valid", "", "Another"])

        self.assertEqual(len(results), 3)
        self.assertIsNotNone(results[0])
        self.assertIsNone(results[1])
        # The API returned only 1 embedding for 2 valid texts, so results[2] stays None.
        self.assertIsNone(results[2])

    # -- embed_query() tests ----------------------------------------------

    def test_embed_query_returns_embedding(self) -> None:
        """A valid query returns an embedding vector."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embedding": {"values": [0.1] * 768},
        }
        self.mock_session.post.return_value = mock_response

        result = self.provider.embed_query("test query")

        self.assertEqual(len(result), 768)

    def test_embed_query_empty_text_raises(self) -> None:
        """Empty or whitespace-only query raises ValueError."""
        with self.assertRaises(ValueError):
            self.provider.embed_query("")
        with self.assertRaises(ValueError):
            self.provider.embed_query("   ")

    def test_embed_query_api_error_raises(self) -> None:
        """API error propagates the exception."""
        from requests.exceptions import ConnectionError
        self.mock_session.post.side_effect = ConnectionError("API error")

        with patch("providers.gemini_embedding.time.sleep"):
            with self.assertRaises(ConnectionError):
                self.provider.embed_query("test")


# ============================================================================
# OpenAIEmbeddingProvider Tests
# ============================================================================


@override_settings(
    OPENAI_API_KEY="test-openai-key",
    OPENAI_EMBEDDING_MODEL="text-embedding-3-small",
    EMBEDDING_DIMENSION=768,
)
class OpenAIEmbeddingProviderTests(TestCase):
    """Tests for :class:`OpenAIEmbeddingProvider`."""

    def setUp(self) -> None:
        # Patch the OpenAI client to avoid real API calls.
        patcher = patch("openai.OpenAI")
        self.mock_openai_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_client = MagicMock()
        self.mock_openai_cls.return_value = self.mock_client
        self.provider = OpenAIEmbeddingProvider()

    def test_dimensions_property(self) -> None:
        """dimensions returns the configured value."""
        self.assertEqual(self.provider.dimensions, 768)

    # -- embed() tests ----------------------------------------------------

    def test_embed_returns_embedding(self) -> None:
        """A valid text returns an embedding vector."""
        mock_response = MagicMock()
        mock_response.data = [MagicMock()]
        mock_response.data[0].embedding = [0.1] * 768
        self.mock_client.embeddings.create.return_value = mock_response

        result = self.provider.embed("Hello world")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 768)

    def test_embed_empty_text_returns_none(self) -> None:
        """Empty or whitespace-only text returns None."""
        self.assertIsNone(self.provider.embed(""))
        self.assertIsNone(self.provider.embed("   "))

    def test_embed_api_error_returns_none(self) -> None:
        """API error returns None."""
        self.mock_client.embeddings.create.side_effect = Exception(
            "API error"
        )

        result = self.provider.embed("Hello")
        self.assertIsNone(result)

    # -- embed_batch() tests ----------------------------------------------

    def test_embed_batch_returns_in_order(self) -> None:
        """Multiple texts return embeddings in correct order."""
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[1.0] + [0.0] * 767),
            MagicMock(embedding=[2.0] + [0.0] * 767),
        ]
        self.mock_client.embeddings.create.return_value = mock_response

        results = self.provider.embed_batch(["First", "Second"])

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        assert results[0] is not None
        assert results[1] is not None
        self.assertEqual(results[0][0], 1.0)
        self.assertEqual(results[1][0], 2.0)

    def test_embed_batch_empty_texts(self) -> None:
        """Empty texts in batch produce None at correct positions."""
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[1.0] + [0.0] * 767),
            MagicMock(embedding=[2.0] + [0.0] * 767),
        ]
        self.mock_client.embeddings.create.return_value = mock_response

        results = self.provider.embed_batch(["Valid", "", "Another"])

        self.assertEqual(len(results), 3)
        self.assertIsNotNone(results[0])
        self.assertIsNone(results[1])
        self.assertIsNotNone(results[2])

    # -- embed_query() tests ----------------------------------------------

    def test_embed_query_returns_embedding(self) -> None:
        """A valid query returns an embedding vector."""
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 768)]
        self.mock_client.embeddings.create.return_value = mock_response

        result = self.provider.embed_query("test query")
        self.assertEqual(len(result), 768)

    def test_embed_query_empty_text_raises(self) -> None:
        """Empty or whitespace-only query raises ValueError."""
        with self.assertRaises(ValueError):
            self.provider.embed_query("")
        with self.assertRaises(ValueError):
            self.provider.embed_query("   ")

    def test_embed_query_api_error_raises(self) -> None:
        """API error propagates the exception."""
        self.mock_client.embeddings.create.side_effect = Exception(
            "API error"
        )

        with self.assertRaises(Exception):
            self.provider.embed_query("test")


# ============================================================================
# OllamaEmbeddingProvider Tests
# ============================================================================


@override_settings(
    OLLAMA_BASE_URL="http://localhost:11434",
    OLLAMA_EMBEDDING_MODEL="nomic-embed-text",
    EMBEDDING_DIMENSION=768,
)
class OllamaEmbeddingProviderTests(TestCase):
    """Tests for :class:`OllamaEmbeddingProvider`."""

    def setUp(self) -> None:
        self.provider = OllamaEmbeddingProvider()

    def test_dimensions_property(self) -> None:
        """dimensions returns the configured value."""
        self.assertEqual(self.provider.dimensions, 768)

    # -- embed() tests ----------------------------------------------------

    @patch("providers.ollama_embedding.requests.post")
    def test_embed_returns_embedding(self, mock_post: MagicMock) -> None:
        """A valid text returns an embedding vector."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [[0.1] * 768],
        }
        mock_post.return_value = mock_response

        result = self.provider.embed("Hello world")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 768)

    def test_embed_empty_text_returns_none(self) -> None:
        """Empty or whitespace-only text returns None without API call."""
        self.assertIsNone(self.provider.embed(""))
        self.assertIsNone(self.provider.embed("   "))

    @patch("providers.ollama_embedding.requests.post")
    def test_embed_api_error_returns_none(self, mock_post: MagicMock) -> None:
        """API error returns None."""
        mock_post.side_effect = Exception("connection refused")

        result = self.provider.embed("Hello")
        self.assertIsNone(result)

    # -- embed_batch() tests ----------------------------------------------

    @patch("providers.ollama_embedding.requests.post")
    def test_embed_batch_returns_in_order(self, mock_post: MagicMock) -> None:
        """Multiple texts return embeddings in correct order."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [
                [1.0] + [0.0] * 767,
                [2.0] + [0.0] * 767,
            ],
        }
        mock_post.return_value = mock_response

        results = self.provider.embed_batch(["First", "Second"])

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        assert results[0] is not None
        assert results[1] is not None
        self.assertEqual(results[0][0], 1.0)
        self.assertEqual(results[1][0], 2.0)

    @patch("providers.ollama_embedding.requests.post")
    def test_embed_batch_empty_texts(self, mock_post: MagicMock) -> None:
        """Empty texts in batch produce None at correct positions."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [
                [1.0] + [0.0] * 767,
                [2.0] + [0.0] * 767,
            ],
        }
        mock_post.return_value = mock_response

        results = self.provider.embed_batch(["Valid", "", "Another"])

        self.assertEqual(len(results), 3)
        self.assertIsNotNone(results[0])
        self.assertIsNone(results[1])
        self.assertIsNotNone(results[2])

    # -- embed_query() tests ----------------------------------------------

    @patch("providers.ollama_embedding.requests.post")
    def test_embed_query_returns_embedding(self, mock_post: MagicMock) -> None:
        """A valid query returns an embedding vector."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [[0.1] * 768],
        }
        mock_post.return_value = mock_response

        result = self.provider.embed_query("test query")
        self.assertEqual(len(result), 768)

    def test_embed_query_empty_text_raises(self) -> None:
        """Empty or whitespace-only query raises ValueError."""
        with self.assertRaises(ValueError):
            self.provider.embed_query("")
        with self.assertRaises(ValueError):
            self.provider.embed_query("   ")

    @patch("providers.ollama_embedding.requests.post")
    def test_embed_query_api_error_raises(self, mock_post: MagicMock) -> None:
        """API error propagates the exception."""
        mock_post.side_effect = Exception("API error")

        with self.assertRaises(Exception):
            self.provider.embed_query("test")
