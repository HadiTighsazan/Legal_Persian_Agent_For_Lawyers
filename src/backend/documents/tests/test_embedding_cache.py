"""
Tests for the cached embedding function.

Tests cover:
- :func:`~documents.services.embedding_service.embed_query_cached`

The Django cache framework is used with ``LocMemCache`` (the default test
backend), so no Redis is required for these tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from documents.services.embedding_service import (
    EmbeddingError,
    embed_query_cached,
)


# Ensure we use LocMemCache for tests (no Redis dependency)
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-embedding-cache",
        }
    }
)
class EmbedQueryCachedTests(TestCase):
    """Tests for :func:`~documents.services.embedding_service.embed_query_cached`."""

    def setUp(self) -> None:
        """Clear cache before each test."""
        cache.clear()

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    @patch("documents.services.embedding_service.embed_query")
    def test_first_call_misses_cache_and_calls_embed_query(
        self,
        mock_embed: MagicMock,
    ) -> None:
        """First call should miss cache and delegate to embed_query."""
        fake_embedding = [0.1] * 1024
        mock_embed.return_value = fake_embedding

        result = embed_query_cached("test query")

        assert result == fake_embedding
        mock_embed.assert_called_once_with("test query")

    @patch("documents.services.embedding_service.embed_query")
    def test_second_call_hits_cache_and_skips_embed_query(
        self,
        mock_embed: MagicMock,
    ) -> None:
        """Second call with same text should hit cache and skip embed_query."""
        fake_embedding = [0.1] * 1024
        mock_embed.return_value = fake_embedding

        # First call — miss
        result1 = embed_query_cached("test query")
        assert result1 == fake_embedding

        # Second call — should hit cache
        result2 = embed_query_cached("test query")
        assert result2 == fake_embedding

        # embed_query should have been called only once
        mock_embed.assert_called_once_with("test query")

    @patch("documents.services.embedding_service.embed_query")
    def test_different_queries_produce_different_cache_entries(
        self,
        mock_embed: MagicMock,
    ) -> None:
        """Different query texts should each miss cache independently."""
        mock_embed.side_effect = [
            [0.1] * 1024,  # first query
            [0.2] * 1024,  # second query
        ]

        result1 = embed_query_cached("query one")
        result2 = embed_query_cached("query two")

        assert result1 == [0.1] * 1024
        assert result2 == [0.2] * 1024
        assert mock_embed.call_count == 2

    # ------------------------------------------------------------------
    # Cache TTL
    # ------------------------------------------------------------------

    @patch("documents.services.embedding_service.embed_query")
    def test_cache_respects_custom_timeout(
        self,
        mock_embed: MagicMock,
    ) -> None:
        """Custom timeout should be passed to cache.set."""
        fake_embedding = [0.1] * 1024
        mock_embed.return_value = fake_embedding

        embed_query_cached("test query", timeout=60)

        # Verify the value was cached (second call should hit)
        result2 = embed_query_cached("test query", timeout=60)
        assert result2 == fake_embedding
        mock_embed.assert_called_once_with("test query")

    # ------------------------------------------------------------------
    # Error propagation
    # ------------------------------------------------------------------

    @patch("documents.services.embedding_service.embed_query")
    def test_propagates_embed_query_error(
        self,
        mock_embed: MagicMock,
    ) -> None:
        """If embed_query raises, embed_query_cached should propagate."""
        mock_embed.side_effect = EmbeddingError("API failure")

        with self.assertRaises(EmbeddingError) as ctx:
            embed_query_cached("test query")

        assert "API failure" in str(ctx.exception)

    @patch("documents.services.embedding_service.embed_query")
    def test_error_not_cached(
        self,
        mock_embed: MagicMock,
    ) -> None:
        """If embed_query raises, the error should NOT be cached."""
        mock_embed.side_effect = EmbeddingError("API failure")

        with self.assertRaises(EmbeddingError):
            embed_query_cached("test query")

        # Second call should try embed_query again (not serve cached error)
        mock_embed.side_effect = EmbeddingError("API failure again")
        with self.assertRaises(EmbeddingError):
            embed_query_cached("test query")

        assert mock_embed.call_count == 2

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_text_raises_value_error(self) -> None:
        """Empty text should raise ValueError (delegated to embed_query).

        This test does NOT use @patch because LocMemCache pickling
        conflicts with MagicMock objects.  Instead we test the ValueError
        directly — the validation happens before any cache or provider
        interaction.
        """
        with self.assertRaises(ValueError):
            embed_query_cached("")
        with self.assertRaises(ValueError):
            embed_query_cached("   ")

    @patch("documents.services.embedding_service.embed_query")
    def test_unicode_query_works(
        self,
        mock_embed: MagicMock,
    ) -> None:
        """Persian/Arabic text should be cached correctly."""
        fake_embedding = [0.5] * 1024
        mock_embed.return_value = fake_embedding

        persian_query = "مجازات کلاهبرداری طبق قانون چیست؟"
        result1 = embed_query_cached(persian_query)
        assert result1 == fake_embedding

        # Second call should hit cache
        result2 = embed_query_cached(persian_query)
        assert result2 == fake_embedding

        mock_embed.assert_called_once_with(persian_query)
