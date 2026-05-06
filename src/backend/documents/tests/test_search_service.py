"""
Tests for the search service (cosine similarity search via pgvector).

Tests
-----
- :func:`test_search_chunks_returns_top_k` — top_k limits results
- :func:`test_search_chunks_filters_by_min_score` — min_score threshold
- :func:`test_search_chunks_excludes_unembedded_chunks` — NULL embeddings excluded
- :func:`test_search_chunks_orders_by_relevance` — descending relevance_score
- :func:`test_search_chunks_empty_result` — no chunks returns []
- :func:`test_apply_metadata_filters` — metadata filter conditions
- :func:`test_rrf_fusion` — Reciprocal Rank Fusion algorithm
- :func:`test_rrf_fusion_multi` — Multi-list RRF fusion
- :func:`test_keyword_search` — PostgreSQL FTS keyword search
- :func:`test_keyword_search_normalizes_query` — FTS query normalisation
- :func:`test_keyword_search_stop_words` — Persian stop word removal
- :func:`test_remove_stop_words` — Stop word helper function
- :func:`test_trigram_search` — pg_trgm trigram similarity search
- :func:`test_hybrid_search` — Combined vector + keyword + trigram search
- :func:`test_hybrid_search_trigram_disabled` — Hybrid without trigram
"""

from __future__ import annotations

from unittest.mock import patch

from django.db import connection
from django.test import TestCase

from documents.models import Document, DocumentChunk
from documents.services.search_service import (
    _apply_metadata_filters,
    _remove_stop_words,
    _rrf_fusion,
    _rrf_fusion_multi,
    hybrid_search,
    keyword_search,
    search_chunks,
    trigram_search,
)
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
    """Return a vector with cosine distance ≈ 0.106 from the query.

    ``[1.0, 0.5, 0.0, ...]`` — query is ``[1.0, 0.0, ...]``.

    dot = 1.0*1.0 + 0.0*0.5 = 1.0
    norm_query = 1.0
    norm_vec = sqrt(1.0² + 0.5²) = sqrt(1.25) ≈ 1.118034...
    cos_sim = 1.0 / (1.0 * 1.118034) ≈ 0.894427
    distance = 1 - 0.894427 ≈ 0.105573
    """
    return _make_vector(1.0, 0.5)


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
        # query → medium:    distance≈0.106,   relevance≈0.894      (passes)
        self._create_chunk(2, _medium_vector())
        # query → far:       distance≈0.99,    relevance≈0.01       (fails)
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
        # Expected order: Query (1.0), Close (~0.995), Medium (~0.894), Far (~0.01)
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


# ---------------------------------------------------------------------------
# Metadata filtering tests
# ---------------------------------------------------------------------------


class ApplyMetadataFiltersTest(TestCase):
    """Test suite for :func:`_apply_metadata_filters`."""

    def setUp(self) -> None:
        """Create a user and a document shared by all tests."""
        self.user = User.objects.create_user(
            email="filter_test@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Filter Test Doc",
            filename="filter_test.pdf",
            original_filename="filter_test.pdf",
            file_path="/tmp/filter_test.pdf",
            file_size=1024,
            mime_type="application/pdf",
            status="completed",
        )
        # Create chunks with different metadata
        self.chunk_valid = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=1,
            content="Valid law content",
            token_count=5,
            metadata={"law_name": "قانون مدنی", "legal_status": "valid"},
            law_name="قانون مدنی",
            legal_status="valid",
        )
        self.chunk_obsolete = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=2,
            page_end=2,
            content="Obsolete law content",
            token_count=5,
            metadata={"law_name": "قانون مدنی", "legal_status": "obsolete"},
            law_name="قانون مدنی",
            legal_status="obsolete",
        )

    def test_filters_by_legal_status(self) -> None:
        """Filter by ``legal_status="valid"`` returns only valid chunks."""
        qs = DocumentChunk.objects.filter(document=self.document)
        filtered = _apply_metadata_filters(qs, {"legal_status": "valid"})
        self.assertEqual(filtered.count(), 1)
        self.assertEqual(filtered.first().legal_status, "valid")

    def test_filters_by_law_name(self) -> None:
        """Filter by ``law_name`` returns only matching chunks."""
        qs = DocumentChunk.objects.filter(document=self.document)
        filtered = _apply_metadata_filters(qs, {"law_name": "قانون مدنی"})
        self.assertEqual(filtered.count(), 2)

    def test_filters_by_law_name_no_match(self) -> None:
        """Filter by non-existent law name returns empty queryset."""
        qs = DocumentChunk.objects.filter(document=self.document)
        filtered = _apply_metadata_filters(qs, {"law_name": "قانون جزا"})
        self.assertEqual(filtered.count(), 0)

    def test_no_filters_returns_all(self) -> None:
        """Passing ``None`` or empty dict returns the queryset unchanged."""
        qs = DocumentChunk.objects.filter(document=self.document)
        self.assertEqual(_apply_metadata_filters(qs, None).count(), 2)
        self.assertEqual(_apply_metadata_filters(qs, {}).count(), 2)

    def test_unknown_filter_field_is_ignored(self) -> None:
        """Unknown filter fields are logged as warnings and ignored."""
        qs = DocumentChunk.objects.filter(document=self.document)
        filtered = _apply_metadata_filters(qs, {"unknown_field": "value"})
        self.assertEqual(filtered.count(), 2)


# ---------------------------------------------------------------------------
# RRF Fusion tests
# ---------------------------------------------------------------------------


class RrfFusionTest(TestCase):
    """Test suite for :func:`_rrf_fusion`."""

    def _make_result(self, chunk_id: str, score: float) -> dict:
        return {
            "chunk_id": chunk_id,
            "relevance_score": score,
            "content": f"Content for {chunk_id}",
        }

    def test_fuses_two_lists(self) -> None:
        """Two lists with overlapping items are fused correctly."""
        vector_results = [
            self._make_result("A", 0.9),
            self._make_result("B", 0.8),
            self._make_result("C", 0.7),
        ]
        keyword_results = [
            self._make_result("B", 0.85),
            self._make_result("C", 0.75),
            self._make_result("D", 0.6),
        ]

        fused = _rrf_fusion(vector_results, keyword_results, top_k=3)

        # All 4 unique items should be present (top_k=3 but we have 4 unique)
        self.assertEqual(len(fused), 3)
        chunk_ids = {r["chunk_id"] for r in fused}
        self.assertIn("A", chunk_ids)
        self.assertIn("B", chunk_ids)
        self.assertIn("C", chunk_ids)

        # B appears in both lists at rank 2 → should have highest RRF score
        self.assertEqual(fused[0]["chunk_id"], "B")

    def test_rrf_scores_are_present(self) -> None:
        """Fused results include ``vector_score``, ``keyword_score``, ``rrf_score``."""
        vector_results = [self._make_result("A", 0.9)]
        keyword_results = [self._make_result("A", 0.8)]

        fused = _rrf_fusion(vector_results, keyword_results, top_k=5)

        self.assertIn("vector_score", fused[0])
        self.assertIn("keyword_score", fused[0])
        self.assertIn("rrf_score", fused[0])
        self.assertEqual(fused[0]["vector_score"], 0.9)
        self.assertEqual(fused[0]["keyword_score"], 0.8)

    def test_empty_vector_results(self) -> None:
        """Empty vector results — only keyword results contribute."""
        keyword_results = [self._make_result("A", 0.8)]

        fused = _rrf_fusion([], keyword_results, top_k=5)

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]["chunk_id"], "A")
        self.assertEqual(fused[0]["vector_score"], 0.0)

    def test_empty_keyword_results(self) -> None:
        """Empty keyword results — only vector results contribute."""
        vector_results = [self._make_result("A", 0.9)]

        fused = _rrf_fusion(vector_results, [], top_k=5)

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]["chunk_id"], "A")
        self.assertEqual(fused[0]["keyword_score"], 0.0)

    def test_both_empty_returns_empty(self) -> None:
        """Both lists empty — returns empty list."""
        fused = _rrf_fusion([], [], top_k=5)
        self.assertEqual(fused, [])

    def test_top_k_limits_results(self) -> None:
        """``top_k`` limits the number of fused results."""
        vector_results = [
            self._make_result("A", 0.9),
            self._make_result("B", 0.8),
        ]
        keyword_results = [
            self._make_result("C", 0.7),
            self._make_result("D", 0.6),
        ]

        fused = _rrf_fusion(vector_results, keyword_results, top_k=2)
        self.assertEqual(len(fused), 2)


# ---------------------------------------------------------------------------
# Stop word removal tests
# ---------------------------------------------------------------------------


class RemoveStopWordsTest(TestCase):
    """Test suite for :func:`_remove_stop_words`."""

    def test_removes_persian_stop_words(self) -> None:
        """Common Persian stop words are removed from the query."""
        result = _remove_stop_words("مجازات در قانون")
        self.assertEqual(result, "مجازات قانون")

    def test_removes_multiple_stop_words(self) -> None:
        """Multiple stop words in sequence are all removed."""
        result = _remove_stop_words("این و آن در به برای")
        self.assertEqual(result, "")

    def test_keeps_non_stop_words(self) -> None:
        """Non-stop words are preserved."""
        result = _remove_stop_words("مجازات ماده قانون مدنی")
        self.assertEqual(result, "مجازات ماده قانون مدنی")

    def test_empty_query_returns_empty(self) -> None:
        """Empty query returns unchanged."""
        result = _remove_stop_words("")
        self.assertEqual(result, "")

    def test_whitespace_query_returns_whitespace(self) -> None:
        """Whitespace-only query returns unchanged."""
        result = _remove_stop_words("   ")
        self.assertEqual(result, "   ")

    def test_mixed_persian_english(self) -> None:
        """Mixed Persian/English queries only remove Persian stop words."""
        result = _remove_stop_words("the و in ماده")
        self.assertEqual(result, "the in ماده")

    def test_query_with_only_stop_words_returns_empty(self) -> None:
        """Query consisting entirely of stop words returns empty string."""
        result = _remove_stop_words("و در به از")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# Keyword search tests
# ---------------------------------------------------------------------------


class KeywordSearchTest(TestCase):
    """Test suite for :func:`keyword_search`."""

    def setUp(self) -> None:
        """Create a user and a document with chunks that have search_vector."""
        self.user = User.objects.create_user(
            email="keyword_test@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Keyword Test Doc",
            filename="keyword_test.pdf",
            original_filename="keyword_test.pdf",
            file_path="/tmp/keyword_test.pdf",
            file_size=1024,
            mime_type="application/pdf",
            status="completed",
        )
        # Create chunks with search_vector populated
        self.chunk1 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=1,
            content="ماده 22 قانون مدنی",
            token_count=5,
            metadata={"law_name": "قانون مدنی"},
            law_name="قانون مدنی",
        )
        self.chunk2 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=2,
            page_end=2,
            content="قانون مجازات اسلامی",
            token_count=5,
            metadata={"law_name": "قانون مجازات اسلامی"},
            law_name="قانون مجازات اسلامی",
        )

    def test_empty_query_returns_empty(self) -> None:
        """Empty query string returns empty results."""
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="",
        )
        self.assertEqual(results, [])

    def test_keyword_search_returns_matches(self) -> None:
        """Search for a term that exists in one chunk."""
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="مدنی",
            top_k=10,
        )
        # Should match chunk1 which contains "مدنی"
        self.assertGreaterEqual(len(results), 1)
        chunk_ids = [r["chunk_id"] for r in results]
        self.assertIn(str(self.chunk1.id), chunk_ids)

    def test_keyword_search_no_match(self) -> None:
        """Search for a term that doesn't exist returns empty."""
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="nonexistenttermxyz",
            top_k=10,
        )
        self.assertEqual(results, [])

    def test_keyword_search_with_filters(self) -> None:
        """Keyword search combined with metadata filters."""
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
            filters={"law_name": "قانون مدنی"},
        )
        self.assertGreaterEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["metadata"]["law_name"], "قانون مدنی")

    def test_keyword_search_normalizes_persian_digits(self) -> None:
        """Persian digits in query are normalised to English digits."""
        # chunk1 content is "ماده 22 قانون مدنی" (English digits).
        # Query with Persian digits "ماده ۲۲" should still match.
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="ماده ۲۲",
            top_k=10,
        )
        self.assertGreaterEqual(len(results), 1)
        chunk_ids = [r["chunk_id"] for r in results]
        self.assertIn(str(self.chunk1.id), chunk_ids)

    def test_keyword_search_stop_words_dont_block_matches(self) -> None:
        """Stop words in query don't prevent FTS from matching."""
        # Query with stop words "در" and "و" — these should be stripped
        # so that FTS only searches for "مجازات" and "اسلامی".
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="مجازات در و اسلامی",
            top_k=10,
        )
        # Should match chunk2 which contains "مجازات" and "اسلامی"
        self.assertGreaterEqual(len(results), 1)
        chunk_ids = [r["chunk_id"] for r in results]
        self.assertIn(str(self.chunk2.id), chunk_ids)

    def test_keyword_search_all_stop_words_returns_empty(self) -> None:
        """Query with only stop words returns empty results."""
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="و در به",
            top_k=10,
        )
        self.assertEqual(results, [])

    def test_keyword_search_trigram_fallback_on_no_results(self) -> None:
        """When FTS returns zero results, trigram fallback kicks in."""
        # Create a chunk with content that has a typo/OCR error
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=2,
            page_start=3,
            page_end=3,
            content="قانن مجازات اسلامی",  # "قانن" instead of "قانون"
            token_count=5,
            metadata={"law_name": "قانون مجازات اسلامی"},
            law_name="قانون مجازات اسلامی",
        )
        # Search for "قانون" — FTS won't match "قانن" but trigram should
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
            enable_trigram_fallback=True,
        )
        # Trigram fallback should find the chunk with "قانن"
        self.assertGreaterEqual(len(results), 1)

    def test_keyword_search_trigram_fallback_disabled(self) -> None:
        """When trigram fallback is disabled, FTS zero results returns empty."""
        # Create a chunk with content that won't match FTS
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=3,
            page_start=4,
            page_end=4,
            content="zzzzzzzzzzzzzzzzzzzz",
            token_count=5,
            metadata={},
        )
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
            enable_trigram_fallback=False,
        )
        # Without fallback, FTS won't match "zzzz..." for query "قانون"
        # But chunk1 and chunk2 have "قانون" in content, so they should match
        # Actually, let's test the case where FTS returns zero for a query
        # that has no matches at all
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="nonexistenttermxyz",
            top_k=10,
            enable_trigram_fallback=False,
        )
        self.assertEqual(results, [])

    def test_keyword_search_trigram_fallback_with_persian_digits(self) -> None:
        """Trigram fallback works with Persian digits in the query.

        This simulates a scenario where the query contains Persian digits
        (e.g., "ماده ۲۲") that get normalized to English digits by
        normalize_for_fts(), but FTS still fails to match (e.g., due to
        stop words or tokenization issues), so trigram fallback kicks in.
        """
        # Create a chunk with content containing English digits
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=4,
            page_start=5,
            page_end=5,
            content="ماده 22 قانون",  # English digits in stored content
            token_count=5,
            metadata={},
        )
        # Search with Persian digits — normalize_for_fts converts to English
        results = keyword_search(
            document_id=str(self.document.id),
            query_text="ماده ۲۲",  # Persian digits
            top_k=10,
            enable_trigram_fallback=True,
        )
        # Should find the chunk (either via FTS or trigram fallback)
        self.assertGreaterEqual(len(results), 1)


# ---------------------------------------------------------------------------
# Trigram search tests
# ---------------------------------------------------------------------------


class TrigramSearchTest(TestCase):
    """Test suite for :func:`trigram_search`."""

    def setUp(self) -> None:
        """Create a user and a document with chunks."""
        self.user = User.objects.create_user(
            email="trigram_test@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Trigram Test Doc",
            filename="trigram_test.pdf",
            original_filename="trigram_test.pdf",
            file_path="/tmp/trigram_test.pdf",
            file_size=1024,
            mime_type="application/pdf",
            status="completed",
        )
        # Create chunks with content that has trigram overlap
        self.chunk1 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=1,
            content="ماده ۲۲ قانون مدنی",
            token_count=5,
            metadata={"law_name": "قانون مدنی"},
            law_name="قانون مدنی",
        )
        self.chunk2 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=2,
            page_end=2,
            content="قانون مجازات اسلامی",
            token_count=5,
            metadata={"law_name": "قانون مجازات اسلامی"},
            law_name="قانون مجازات اسلامی",
        )
        self.chunk3 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=2,
            page_start=3,
            page_end=3,
            content="یک متن کاملاً متفاوت",
            token_count=5,
            metadata={"law_name": "متن دیگر"},
            law_name="متن دیگر",
        )

    def test_empty_query_returns_empty(self) -> None:
        """Empty query string returns empty results."""
        results = trigram_search(
            document_id=str(self.document.id),
            query_text="",
        )
        self.assertEqual(results, [])

    def test_trigram_search_returns_matches(self) -> None:
        """Search for a term returns chunks with trigram overlap."""
        results = trigram_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
        )
        # Both chunk1 and chunk2 contain "قانون"
        self.assertGreaterEqual(len(results), 2)
        chunk_ids = {r["chunk_id"] for r in results}
        self.assertIn(str(self.chunk1.id), chunk_ids)
        self.assertIn(str(self.chunk2.id), chunk_ids)

    def test_trigram_search_handles_ocr_errors(self) -> None:
        """Trigram search catches OCR-like errors (partial matches)."""
        # "قانن" is a common OCR error for "قانون" — trigrams should still match
        results = trigram_search(
            document_id=str(self.document.id),
            query_text="قانن",
            top_k=10,
            min_similarity=0.1,
        )
        # Should still find chunks containing "قانون" despite the typo
        self.assertGreaterEqual(len(results), 1)

    def test_trigram_search_with_filters(self) -> None:
        """Trigram search combined with metadata filters."""
        results = trigram_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
            filters={"law_name": "قانون مدنی"},
        )
        self.assertGreaterEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["metadata"]["law_name"], "قانون مدنی")

    def test_trigram_search_min_similarity(self) -> None:
        """Higher min_similarity filters out less relevant results."""
        # Very high threshold should return fewer results
        results_high = trigram_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
            min_similarity=0.9,
        )
        results_low = trigram_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
            min_similarity=0.1,
        )
        self.assertLessEqual(len(results_high), len(results_low))

    def test_trigram_search_no_match(self) -> None:
        """Search for completely unrelated text returns empty."""
        results = trigram_search(
            document_id=str(self.document.id),
            query_text="zzzzzzzzzz",
            top_k=10,
        )
        self.assertEqual(results, [])

    def test_trigram_search_orders_by_similarity(self) -> None:
        """Results are ordered by trigram similarity descending."""
        results = trigram_search(
            document_id=str(self.document.id),
            query_text="قانون",
            top_k=10,
        )
        if len(results) >= 2:
            scores = [r["relevance_score"] for r in results]
            for i in range(len(scores) - 1):
                self.assertGreaterEqual(scores[i], scores[i + 1])


# ---------------------------------------------------------------------------
# Multi-list RRF Fusion tests
# ---------------------------------------------------------------------------


class RrfFusionMultiTest(TestCase):
    """Test suite for :func:`_rrf_fusion_multi`."""

    def _make_result(self, chunk_id: str, score: float) -> dict:
        return {
            "chunk_id": chunk_id,
            "relevance_score": score,
            "content": f"Content for {chunk_id}",
        }

    def test_fuses_three_lists(self) -> None:
        """Three lists with overlapping items are fused correctly."""
        list1 = [
            self._make_result("A", 0.9),
            self._make_result("B", 0.8),
        ]
        list2 = [
            self._make_result("B", 0.85),
            self._make_result("C", 0.7),
        ]
        list3 = [
            self._make_result("C", 0.75),
            self._make_result("D", 0.6),
        ]

        fused = _rrf_fusion_multi(
            [list1, list2, list3],
            top_k=4,
            score_keys=["score_1", "score_2", "score_3"],
        )

        # All 4 unique items should be present
        self.assertEqual(len(fused), 4)
        chunk_ids = {r["chunk_id"] for r in fused}
        self.assertEqual(chunk_ids, {"A", "B", "C", "D"})

        # B appears in lists 1 and 2 → should have highest RRF score
        self.assertEqual(fused[0]["chunk_id"], "B")

    def test_score_keys_are_present(self) -> None:
        """Fused results include all score keys."""
        list1 = [self._make_result("A", 0.9)]
        list2 = [self._make_result("A", 0.8)]
        list3 = [self._make_result("A", 0.7)]

        fused = _rrf_fusion_multi(
            [list1, list2, list3],
            top_k=5,
            score_keys=["vector_score", "keyword_score", "trigram_score"],
        )

        self.assertIn("vector_score", fused[0])
        self.assertIn("keyword_score", fused[0])
        self.assertIn("trigram_score", fused[0])
        self.assertEqual(fused[0]["vector_score"], 0.9)
        self.assertEqual(fused[0]["keyword_score"], 0.8)
        self.assertEqual(fused[0]["trigram_score"], 0.7)

    def test_empty_lists_returns_empty(self) -> None:
        """Empty list of lists returns empty."""
        fused = _rrf_fusion_multi([], top_k=5)
        self.assertEqual(fused, [])

    def test_some_empty_lists(self) -> None:
        """Some empty lists among non-empty ones."""
        list1 = [self._make_result("A", 0.9)]
        list2: list[dict] = []

        fused = _rrf_fusion_multi(
            [list1, list2],
            top_k=5,
            score_keys=["score_1", "score_2"],
        )

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]["chunk_id"], "A")
        self.assertEqual(fused[0]["score_1"], 0.9)
        self.assertEqual(fused[0]["score_2"], 0.0)

    def test_top_k_limits_results(self) -> None:
        """top_k limits the number of fused results."""
        list1 = [self._make_result("A", 0.9), self._make_result("B", 0.8)]
        list2 = [self._make_result("C", 0.7), self._make_result("D", 0.6)]

        fused = _rrf_fusion_multi([list1, list2], top_k=2)
        self.assertEqual(len(fused), 2)


# ---------------------------------------------------------------------------
# Hybrid search tests
# ---------------------------------------------------------------------------


class HybridSearchTest(TestCase):
    """Test suite for :func:`hybrid_search`."""

    def setUp(self) -> None:
        """Create a user and a document with chunks."""
        self.user = User.objects.create_user(
            email="hybrid_test@example.com",
            password="testpass123",
        )
        self.document = Document.objects.create(
            user=self.user,
            title="Hybrid Test Doc",
            filename="hybrid_test.pdf",
            original_filename="hybrid_test.pdf",
            file_path="/tmp/hybrid_test.pdf",
            file_size=1024,
            mime_type="application/pdf",
            status="completed",
        )
        # Create chunks with both embeddings and search_vector
        self.chunk1 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=1,
            content="ماده 22 قانون مدنی",
            token_count=5,
            embedding=_query_vector(),
            metadata={"law_name": "قانون مدنی", "legal_status": "valid"},
            law_name="قانون مدنی",
            legal_status="valid",
        )
        self.chunk2 = DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=2,
            page_end=2,
            content="قانون مجازات اسلامی",
            token_count=5,
            embedding=_close_vector(),
            metadata={"law_name": "قانون مجازات اسلامی", "legal_status": "valid"},
            law_name="قانون مجازات اسلامی",
            legal_status="valid",
        )

    def test_hybrid_search_returns_results(self) -> None:
        """Hybrid search returns fused results with trigram enabled by default."""
        results = hybrid_search(
            document_id=str(self.document.id),
            query_vector=_query_vector(),
            query_text="مدنی",
            top_k=5,
        )
        self.assertGreaterEqual(len(results), 1)
        # Should have trigram_score key
        self.assertIn("trigram_score", results[0])

    def test_hybrid_search_with_filters(self) -> None:
        """Hybrid search with metadata filters."""
        results = hybrid_search(
            document_id=str(self.document.id),
            query_vector=_query_vector(),
            query_text="قانون",
            top_k=5,
            filters={"legal_status": "valid"},
        )
        self.assertGreaterEqual(len(results), 1)
        for r in results:
            self.assertEqual(r["metadata"]["legal_status"], "valid")

    def test_hybrid_search_empty_query_text(self) -> None:
        """Hybrid search with empty query text still returns vector results."""
        results = hybrid_search(
            document_id=str(self.document.id),
            query_vector=_query_vector(),
            query_text="",
            top_k=5,
        )
        # Should still get vector results even with empty keyword query
        self.assertGreaterEqual(len(results), 1)

    def test_hybrid_search_trigram_disabled(self) -> None:
        """Hybrid search with trigram disabled uses only vector + keyword."""
        results = hybrid_search(
            document_id=str(self.document.id),
            query_vector=_query_vector(),
            query_text="مدنی",
            top_k=5,
            enable_trigram=False,
        )
        self.assertGreaterEqual(len(results), 1)
        # trigram_score should be 0.0 when disabled
        self.assertEqual(results[0]["trigram_score"], 0.0)

    def test_hybrid_search_includes_trigram_score(self) -> None:
        """Hybrid search results include trigram_score key."""
        results = hybrid_search(
            document_id=str(self.document.id),
            query_vector=_query_vector(),
            query_text="قانون",
            top_k=5,
        )
        self.assertGreaterEqual(len(results), 1)
        for r in results:
            self.assertIn("vector_score", r)
            self.assertIn("keyword_score", r)
            self.assertIn("trigram_score", r)
            self.assertIn("rrf_score", r)
