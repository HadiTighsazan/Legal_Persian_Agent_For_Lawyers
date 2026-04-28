"""
Tests for the search service (cosine similarity search via pgvector).

Tests
-----
- :func:`test_search_chunks_returns_top_k` — top_k limits results
- :func:`test_search_chunks_filters_by_min_score` — min_score threshold
- :func:`test_search_chunks_excludes_unembedded_chunks` — NULL embeddings excluded
- :func:`test_search_chunks_orders_by_relevance` — descending relevance_score
- :func:`test_search_chunks_empty_result` — no chunks returns []
"""

from __future__ import annotations

from unittest.mock import patch

from django.db import connection
from django.test import TestCase

from documents.models import Document, DocumentChunk
from documents.services.search_service import search_chunks
from users.models import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM: int = 768
"""Standard embedding dimension (Gemini gemini-embedding-001)."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vector(*values: float) -> list[float]:
    """Build an embedding vector from the given *values*, padded with zeros.

    The first N dimensions are set to *values*; the rest are zero.  This
    allows predictable cosine distances when compared against a query vector
    like ``[1.0, 0.0, 0.0, ...]``.

    Args:
        *values: The first N components of the vector.

    Returns:
        A 768-dim list of floats.
    """
    vec = list(values)
    vec.extend([0.0] * (EMBEDDING_DIM - len(vec)))
    return vec


def _query_vector() -> list[float]:
    """Return the query vector ``[1.0, 0.0, 0.0, ...]``."""
    return _make_vector(1.0)


def _close_vector() -> list[float]:
    """Return a vector with cosine distance ≈ 0.1 from the query.

    ``[1.0, 0.1, 0.0, ...]`` — query is ``[1.0, 0.0, ...]``.

    dot = 1.0*1.0 + 0.0*0.1 = 1.0
    norm_query = 1.0
    norm_vec = sqrt(1.0² + 0.1²) = sqrt(1.01) ≈ 1.004987...
    cos_sim = 1.0 / (1.0 * 1.004987) ≈ 0.995037
    distance = 1 - 0.995037 ≈ 0.004963
    """
    return _make_vector(1.0, 0.1)


def _medium_vector() -> list[float]:
    """Return a vector with cosine distance ≈ 0.5 from the query.

    ``[1.0, 1.0, 0.0, ...]`` — query is ``[1.0, 0.0, ...]``.

    dot = 1.0*1.0 + 0.0*1.0 = 1.0
    norm_query = 1.0
    norm_vec = sqrt(1.0² + 1.0²) = sqrt(2) ≈ 1.414213...
    cos_sim = 1.0 / (1.0 * 1.414213) ≈ 0.707106
    distance = 1 - 0.707106 ≈ 0.292893
    """
    return _make_vector(1.0, 1.0)


def _far_vector() -> list[float]:
    """Return a vector with cosine distance ≈ 1.0 from the query.

    ``[0.0, 1.0, 0.0, ...]`` — query is ``[1.0, 0.0, ...]``.

    dot = 1.0*0.0 + 0.0*1.0 = 0.0
    norm_query = 1.0
    norm_vec = 1.0
    cos_sim = 0.0
    distance = 1.0
    """
    return _make_vector(0.0, 1.0)


# ---------------------------------------------------------------------------
# Test Case
# ---------------------------------------------------------------------------


class SearchChunksTest(TestCase):
    """Test suite for :func:`search_chunks`."""

    def setUp(self) -> None:
        """Create a user and a document shared by all tests."""
        self.user = User.objects.create_user(
            email="search_test@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Search Test Doc",
            filename="search_test.pdf",
            original_filename="search_test.pdf",
            file_path="/tmp/search_test.pdf",
            file_size=1024,
            mime_type="application/pdf",
            status="completed",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_chunk(
        self,
        chunk_index: int,
        embedding: list[float] | None,
        content: str = "Some chunk content",
    ) -> DocumentChunk:
        """Create a :class:`DocumentChunk` with the given index and embedding."""
        return DocumentChunk.objects.create(
            document=self.document,
            chunk_index=chunk_index,
            page_start=1,
            page_end=1,
            content=content,
            embedding=embedding,
            token_count=len(content.split()),
            metadata={"source": "test"},
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_search_chunks_returns_top_k(self) -> None:
        """Seed 5 chunks with known embeddings, set ``top_k=3``, expect 3 results."""
        # Arrange
        self._create_chunk(0, _query_vector())
        self._create_chunk(1, _close_vector())
        self._create_chunk(2, _medium_vector())
        self._create_chunk(3, _far_vector())
        self._create_chunk(4, _query_vector())

        query_vector = _query_vector()

        # Act
        results = search_chunks(
            document_id=str(self.document.id),
            query_vector=query_vector,
            top_k=3,
        )

        # Assert
        self.assertEqual(len(results), 3)

    def test_search_chunks_filters_by_min_score(self) -> None:
        """Create chunks with varying relevance, set ``min_score=0.7``, expect only
        chunks with score >= 0.7."""
        # Arrange
        # query → query:     distance=0,       relevance=1.0        (passes)
        self._create_chunk(0, _query_vector())
        # query → close:     distance≈0.005,   relevance≈0.995      (passes)
        self._create_chunk(1, _close_vector())
        # query → medium:    distance≈0.293,   relevance≈0.707      (passes)
        self._create_chunk(2, _medium_vector())
        # query → far:       distance=1.0,     relevance=0.0        (fails)
        self._create_chunk(3, _far_vector())

        query_vector = _query_vector()

        # Act
        results = search_chunks(
            document_id=str(self.document.id),
            query_vector=query_vector,
            top_k=10,
            min_score=0.7,
        )

        # Assert
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertGreaterEqual(r["relevance_score"], 0.7)

    def test_search_chunks_excludes_unembedded_chunks(self) -> None:
        """Create one chunk with embedding and one with ``embedding=None``.
        Only the embedded chunk should appear in results."""
        # Arrange
        self._create_chunk(0, _query_vector(), content="Has embedding")
        self._create_chunk(1, None, content="No embedding")

        query_vector = _query_vector()

        # Act
        results = search_chunks(
            document_id=str(self.document.id),
            query_vector=query_vector,
        )

        # Assert
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Has embedding")

    def test_search_chunks_orders_by_relevance(self) -> None:
        """Create chunks with known distances and verify results are ordered
        by ``relevance_score`` descending (highest first)."""
        # Arrange — create in arbitrary order
        self._create_chunk(0, _far_vector(), content="Far")
        self._create_chunk(1, _query_vector(), content="Query")
        self._create_chunk(2, _close_vector(), content="Close")
        self._create_chunk(3, _medium_vector(), content="Medium")

        query_vector = _query_vector()

        # Act
        results = search_chunks(
            document_id=str(self.document.id),
            query_vector=query_vector,
            top_k=10,
        )

        # Assert
        self.assertEqual(len(results), 4)
        # Expected order: Query (1.0), Close (~0.995), Medium (~0.707), Far (0.0)
        expected_order = ["Query", "Close", "Medium", "Far"]
        actual_order = [r["content"] for r in results]
        self.assertEqual(actual_order, expected_order)

        # Also verify scores are strictly descending
        scores = [r["relevance_score"] for r in results]
        for i in range(len(scores) - 1):
            self.assertGreater(scores[i], scores[i + 1])

    def test_search_service_sets_probes(self) -> None:
        """Verify that _set_probes executes SET ivfflat.probes with the correct value."""
        from documents.services.search_service import _set_probes

        with patch.object(connection, "cursor") as mock_cursor:
            mock_cursor.return_value.__enter__.return_value = mock_cursor.return_value
            _set_probes(probes=10)

        mock_cursor.assert_called_once()
        mock_cursor.return_value.execute.assert_called_once_with(
            "SET ivfflat.probes = %s", [10]
        )

    def test_search_chunks_empty_result(self) -> None:
        """Query a document with no chunks at all — expect ``[]``."""
        # Arrange — document has no chunks
        query_vector = _query_vector()

        # Act
        results = search_chunks(
            document_id=str(self.document.id),
            query_vector=query_vector,
        )

        # Assert
        self.assertEqual(results, [])
