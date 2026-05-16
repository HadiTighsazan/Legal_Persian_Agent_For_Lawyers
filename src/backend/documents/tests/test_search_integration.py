"""
Integration test for the semantic search pipeline.

Exercises the full end-to-end flow:
1. A document with chunks and known embedding vectors is created in the DB.
2. ``embed_query`` is mocked to return a deterministic query vector.
3. The ``DocumentSearchView`` endpoint is called via ``APIClient``.
4. Results are verified against expected cosine similarity ordering.

This test runs against a real test database with pgvector enabled
(``transaction=True`` is required for pgvector isolation).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import Document, DocumentChunk
from users.models import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBEDDING_DIM: int = 1024
"""Standard embedding dimension."""

# ---------------------------------------------------------------------------
# Helpers (reused from test_search_service.py)
# ---------------------------------------------------------------------------


def _make_vector(*values: float) -> list[float]:
    """Build an embedding vector from the given *values*, padded with zeros.

    The first N dimensions are set to *values*; the rest are zero.  This
    allows predictable cosine distances when compared against a query vector
    like ``[1.0, 0.0, 0.0, ...]``.

    Args:
        *values: The first N components of the vector.

    Returns:
        A 1024-dim list of floats.
    """
    vec = list(values)
    vec.extend([0.0] * (EMBEDDING_DIM - len(vec)))
    return vec


def _query_vector() -> list[float]:
    """Return the query vector ``[1.0, 0.0, 0.0, ...]``."""
    return _make_vector(1.0)


def _close_vector() -> list[float]:
    """Return a vector with cosine distance ≈ 0.005 from the query.

    ``[1.0, 0.1, 0.0, ...]`` — query is ``[1.0, 0.0, ...]``.

    dot = 1.0*1.0 + 0.0*0.1 = 1.0
    norm_query = 1.0
    norm_vec = sqrt(1.0² + 0.1²) = sqrt(1.01) ≈ 1.004987...
    cos_sim = 1.0 / (1.0 * 1.004987) ≈ 0.995037
    distance = 1 - 0.995037 ≈ 0.004963
    """
    return _make_vector(1.0, 0.1)


def _far_vector() -> list[float]:
    """Return a vector with cosine distance ≈ 0.99 from the query.

    ``[0.01, 1.0, 0.0, ...]`` — query is ``[1.0, 0.0, ...]``.

    dot = 1.0*0.01 + 0.0*1.0 = 0.01
    norm_query = 1.0
    norm_vec = sqrt(0.01² + 1.0²) = sqrt(1.0001) ≈ 1.00005...
    cos_sim = 0.01 / (1.0 * 1.00005) ≈ 0.0099995
    distance = 1 - 0.0099995 ≈ 0.9900005
    """
    return _make_vector(0.01, 1.0)


# ---------------------------------------------------------------------------
# Integration Test
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class DocumentSearchIntegrationTest(TestCase):
    """End-to-end integration test for the semantic search pipeline.

    Mocks only ``embed_query`` (the external Gemini API call) so that
    ``search_chunks`` runs against real pgvector in the test database.
    """

    def setUp(self) -> None:
        """Create a user, document, and three chunks with known embeddings."""
        # -- User -----------------------------------------------------------
        self.user = User.objects.create_user(
            email="search-integration@example.com",
            password="testpass123",
        )

        # -- Document -------------------------------------------------------
        self.document = Document.objects.create(
            user=self.user,
            title="Integration Test Doc",
            filename="integration_test.pdf",
            original_filename="integration_test.pdf",
            file_path="/tmp/integration_test.pdf",
            file_size=2048,
            mime_type="application/pdf",
            status="completed",
            processing_status="completed",
        )

        # -- Chunks with known embeddings -----------------------------------
        self.chunk0 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=1,
            content="Exact match chunk",
            embedding=_query_vector(),
            token_count=3,
            metadata={"source": "integration_test"},
        )
        self.chunk1 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=2,
            page_end=2,
            content="Close match chunk",
            embedding=_close_vector(),
            token_count=3,
            metadata={"source": "integration_test"},
        )
        self.chunk2 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=2,
            page_start=3,
            page_end=3,
            content="Distant match chunk",
            embedding=_far_vector(),
            token_count=3,
            metadata={"source": "integration_test"},
        )

        # -- API client -----------------------------------------------------
        self.client = APIClient()
        self.url = reverse(
            "documents:document-search",
            kwargs={"document_id": self.document.id},
        )

        # -- Auth header ----------------------------------------------------
        from rest_framework_simplejwt.tokens import RefreshToken  # noqa: PLC0415

        refresh = RefreshToken.for_user(self.user)
        self.auth_header = f"Bearer {refresh.access_token}"

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @patch("documents.views.embed_query")
    def test_search_integration_end_to_end(self, mock_embed_query) -> None:
        """Verify the full search pipeline works end-to-end.

        Mocks only ``embed_query`` so that ``search_chunks`` runs against
        real pgvector in the test database.
        """
        # Arrange — mock embed_query to return the query vector
        mock_embed_query.return_value = _query_vector()

        # Act
        response = self.client.post(
            self.url,
            {"query": "test query", "top_k": 5},
            format="json",
            HTTP_AUTHORIZATION=self.auth_header,
        )

        # Assert — status code
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        # Assert — top-level response keys
        self.assertIn("results", data)
        self.assertIn("query", data)
        self.assertIn("top_k", data)
        self.assertIn("min_score", data)
        self.assertIn("total_results", data)

        # Assert — at least one result
        self.assertGreaterEqual(data["total_results"], 1)

        # Assert — results are ordered by relevance_score descending
        results = data["results"]
        for i in range(len(results) - 1):
            self.assertGreaterEqual(
                results[i]["relevance_score"],
                results[i + 1]["relevance_score"],
                msg="Results must be ordered by relevance_score descending",
            )

        # Assert — first result is the exact match (chunk 0)
        self.assertEqual(
            results[0]["chunk_id"],
            str(self.chunk0.id),
            msg="First result should be the exact-match chunk",
        )

        # Assert — each result has all expected keys
        # Hybrid search results include extra keys from RRF fusion.
        expected_keys = {
            "chunk_id",
            "chunk_index",
            "page_start",
            "page_end",
            "content",
            "relevance_score",
            "token_count",
            "metadata",
            "legal_context",
            "vector_score",
            "keyword_score",
            "trigram_score",
            "rrf_score",
        }
        for result in results:
            self.assertEqual(
                set(result.keys()),
                expected_keys,
                msg=f"Result {result['chunk_id']} is missing expected keys",
            )

        # Assert — relevance scores are in the expected range
        for result in results:
            self.assertGreaterEqual(result["relevance_score"], 0.0)
            self.assertLessEqual(result["relevance_score"], 1.0)

        # Assert — embed_query was called with the correct query
        mock_embed_query.assert_called_once_with("test query")
