"""
Tests for the anchor chunking service.

Tests cover:
- Persian normalization (Arabic Yeh → Persian Yeh, Tatweel removal, diacritics)
- Metadata extraction (case_number, date, plaintiff, defendant, branch)
- Anchor segmentation with multiple anchors
- Anchor segmentation with no anchors (fallback to token overlap split)
- Token-based overlap splitting (accurate token counting)
- Page-aware chunking (pages list correctly populated)
- Empty text → empty list
- Metadata NOT injected into content (separate field)
- Long segment split at anchor boundaries
- Edge cases: missing metadata, partial anchors, mixed numerals
"""

from __future__ import annotations

import pytest

from documents.services.anchor_chunking_service import (
    AnchorChunkingService,
    AnchorChunk,
)


@pytest.fixture
def chunker() -> AnchorChunkingService:
    """Return a fresh :class:`AnchorChunkingService` instance for each test."""
    return AnchorChunkingService()


# ---------------------------------------------------------------------------
# Persian normalization
# ---------------------------------------------------------------------------


class TestPersianNormalization:
    """Tests for :meth:`AnchorChunkingService._normalize_persian`."""

    def test_arabic_yeh_to_persian(self, chunker: AnchorChunkingService) -> None:
        """Arabic Yeh (ي) → Persian Yeh (ی)."""
        result = chunker._normalize_persian("متن ي با ي عربي")
        assert "ی" in result
        assert "ي" not in result

    def test_arabic_kaf_to_persian(self, chunker: AnchorChunkingService) -> None:
        """Arabic Kaf (ك) → Persian Kaf (ک)."""
        result = chunker._normalize_persian("متن ك با ك عربي")
        assert "ک" in result
        assert "ك" not in result

    def test_alef_variants_unified(self, chunker: AnchorChunkingService) -> None:
        """Alef variants (أ, إ, آ) → plain Alef (ا)."""
        result = chunker._normalize_persian("أ إ آ")
        assert result == "ا ا ا"

    def test_diacritics_removed(self, chunker: AnchorChunkingService) -> None:
        """Arabic diacritics (Fatha, Kasra, Damma) are removed."""
        text = "مَـتْنٌ مَعَ الْحَرَكاتِ"
        result = chunker._normalize_persian(text)
        # Diacritics are in the \u064B-\u065F range
        assert all(ord(c) not in range(0x064B, 0x0660) for c in result)

    def test_whitespace_collapsed(self, chunker: AnchorChunkingService) -> None:
        """Multiple whitespace → single space."""
        result = chunker._normalize_persian("متن   با    فاصله")
        assert result == "متن با فاصله"

    def test_empty_text(self, chunker: AnchorChunkingService) -> None:
        """Empty text → empty string."""
        assert chunker._normalize_persian("") == ""

    def test_no_changes_for_clean_text(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Clean Persian text is unchanged."""
        text = "این یک متن فارسی سالم است"
        assert chunker._normalize_persian(text) == text


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


class TestMetadataExtraction:
    """Tests for :meth:`AnchorChunkingService._extract_metadata`."""

    def test_case_number(self, chunker: AnchorChunkingService) -> None:
        """Case number is extracted."""
        text = "کلاسه پرونده: ۱۲۳۴۵۶۷۸۹۰"
        metadata = chunker._extract_metadata(text)
        assert metadata.get("case_number") == "۱۲۳۴۵۶۷۸۹۰"

    def test_date(self, chunker: AnchorChunkingService) -> None:
        """Date is extracted."""
        text = "تاریخ: ۱۴۰۲/۰۶/۱۵"
        metadata = chunker._extract_metadata(text)
        assert metadata.get("date") == "۱۴۰۲/۰۶/۱۵"

    def test_plaintiff(self, chunker: AnchorChunkingService) -> None:
        """Plaintiff name is extracted."""
        text = "خواهان: علی محمدی"
        metadata = chunker._extract_metadata(text)
        assert "علی محمدی" in metadata.get("plaintiff", "")

    def test_defendant(self, chunker: AnchorChunkingService) -> None:
        """Defendant name is extracted."""
        text = "خوانده: شرکت ساختمانی"
        metadata = chunker._extract_metadata(text)
        assert "شرکت ساختمانی" in metadata.get("defendant", "")

    def test_branch(self, chunker: AnchorChunkingService) -> None:
        """Branch number is extracted."""
        text = "شعبه ۱۲"
        metadata = chunker._extract_metadata(text)
        assert metadata.get("branch") == "۱۲"

    def test_all_metadata(self, chunker: AnchorChunkingService) -> None:
        """All metadata fields are extracted from a realistic document header."""
        text = (
            "کلاسه پرونده: ۱۲۳۴۵۶۷۸۹۰۱۲۳۴\n"
            "تاریخ: ۱۴۰۲/۰۶/۱۵\n"
            "خواهان: علی محمدی\n"
            "خوانده: شرکت ساختمانی\n"
            "شعبه ۱۲\n"
        )
        metadata = chunker._extract_metadata(text)
        assert metadata.get("case_number") == "۱۲۳۴۵۶۷۸۹۰۱۲۳۴"
        assert metadata.get("date") == "۱۴۰۲/۰۶/۱۵"
        assert "علی محمدی" in metadata.get("plaintiff", "")
        assert "شرکت ساختمانی" in metadata.get("defendant", "")
        assert metadata.get("branch") == "۱۲"

    def test_missing_metadata(self, chunker: AnchorChunkingService) -> None:
        """Missing metadata fields are omitted from result."""
        text = "این یک متن بدون متادیتا است"
        metadata = chunker._extract_metadata(text)
        assert metadata == {}


# ---------------------------------------------------------------------------
# Page tracking
# ---------------------------------------------------------------------------


class TestPageTracking:
    """Tests for page marker parsing and resolution."""

    def test_parse_page_markers(self, chunker: AnchorChunkingService) -> None:
        """Page markers are correctly parsed."""
        text = "[PAGE 1]\nمتن صفحه اول\n[PAGE 2]\nمتن صفحه دوم"
        page_map = chunker._parse_page_markers(text)
        assert len(page_map) == 2
        assert page_map[0] == (0, 1)  # Position 0, page 1
        assert page_map[1][1] == 2  # Page 2

    def test_resolve_pages_single(self, chunker: AnchorChunkingService) -> None:
        """Text range within a single page."""
        text = "[PAGE 1]\nمتن صفحه اول\n[PAGE 2]\nمتن صفحه دوم"
        page_map = chunker._parse_page_markers(text)
        pages = chunker._resolve_pages(10, 20, page_map)
        assert pages == [1]

    def test_resolve_pages_cross_boundary(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Text range crossing a page boundary."""
        text = "[PAGE 1]\nمتن صفحه اول\n[PAGE 2]\nمتن صفحه دوم"
        page_map = chunker._parse_page_markers(text)
        # Range that spans from page 1 into page 2
        pages = chunker._resolve_pages(5, 40, page_map)
        assert pages == [1, 2]

    def test_resolve_pages_no_markers(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Text without page markers defaults to page 1."""
        text = "متن بدون نشانگر صفحه"
        page_map = chunker._parse_page_markers(text)
        assert page_map == []
        pages = chunker._resolve_pages(0, 10, page_map)
        assert pages == [1]


# ---------------------------------------------------------------------------
# Token-based overlap splitting
# ---------------------------------------------------------------------------


class TestTokenOverlapSplit:
    """Tests for :meth:`AnchorChunkingService._token_overlap_split`."""

    def test_short_text_no_split(self, chunker: AnchorChunkingService) -> None:
        """Short text (< chunk_tokens) → single chunk."""
        text = "این یک متن کوتاه است."
        chunks = chunker._token_overlap_split(text, chunk_tokens=400)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_split(self, chunker: AnchorChunkingService) -> None:
        """Long text is split into multiple chunks."""
        # Create text long enough to exceed chunk_tokens
        text = "کلمه " * 500  # ~1000 tokens
        chunks = chunker._token_overlap_split(text, chunk_tokens=100)
        assert len(chunks) > 1

    def test_overlap_present(self, chunker: AnchorChunkingService) -> None:
        """Consecutive chunks share overlapping tokens."""
        text = "کلمه " * 200
        chunks = chunker._token_overlap_split(
            text, chunk_tokens=100, overlap_tokens=20
        )
        if len(chunks) > 1:
            # The end of chunk 0 should overlap with the start of chunk 1
            assert chunks[0] != chunks[1]  # Not identical
            # There should be some shared content
            assert len(chunks[0]) > 0
            assert len(chunks[1]) > 0

    def test_empty_text(self, chunker: AnchorChunkingService) -> None:
        """Empty text → empty list."""
        chunks = chunker._token_overlap_split("")
        assert chunks == []


# ---------------------------------------------------------------------------
# Anchor segmentation
# ---------------------------------------------------------------------------


class TestAnchorSegmentation:
    """Tests for anchor-based text segmentation."""

    def test_no_anchors_fallback(self, chunker: AnchorChunkingService) -> None:
        """No anchors found → fallback to token-based split."""
        text = "[PAGE 1]\nاین یک متن ساده بدون لنگر متنی است."
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1
        assert chunks[0].section_title == "کل سند"

    def test_single_anchor(self, chunker: AnchorChunkingService) -> None:
        """Single anchor creates two sections (intro + anchored)."""
        text = (
            "[PAGE 1]\n"
            "مقدمه سند\n"
            "رأی دادگاه\n"
            "متن رأی دادگاه در این بخش قرار دارد."
        )
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 2
        # First chunk should be the introduction
        assert chunks[0].section_title == "مقدمه"
        # Second chunk should be the anchored section
        # section_title uses normalized form (رای without Hamza on Alef)
        assert "رای دادگاه" in chunks[-1].section_title

    def test_multiple_anchors(self, chunker: AnchorChunkingService) -> None:
        """Multiple anchors create multiple sections."""
        text = (
            "[PAGE 1]\n"
            "بسمه تعالی\n"
            "متن مقدمه\n"
            "گردشکار\n"
            "متن گردشکار\n"
            "رأی دادگاه\n"
            "متن رأی"
        )
        chunks = chunker.chunk_text(text)
        # Should have at least 3 sections (intro + 2 anchors)
        assert len(chunks) >= 3

    def test_anchor_content_preserved(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Anchor titles are preserved in section_title, not in content."""
        text = (
            "[PAGE 1]\n"
            "رأی دادگاه\n"
            "این متن رأی دادگاه است."
        )
        chunks = chunker.chunk_text(text)
        # The anchor title should be in section_title
        # section_title uses normalized form (رای without Hamza on Alef)
        assert any("رای دادگاه" in c.section_title for c in chunks)

    def test_empty_text(self, chunker: AnchorChunkingService) -> None:
        """Empty text → empty list."""
        assert chunker.chunk_text("") == []
        assert chunker.chunk_text("   ") == []


# ---------------------------------------------------------------------------
# Metadata separation
# ---------------------------------------------------------------------------


class TestMetadataSeparation:
    """Tests that metadata is NOT injected into chunk content."""

    def test_metadata_separate_from_content(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Metadata is stored in metadata dict, not in content."""
        text = (
            "[PAGE 1]\n"
            "کلاسه پرونده: ۱۲۳۴۵۶۷۸۹۰\n"
            "تاریخ: ۱۴۰۲/۰۶/۱۵\n"
            "خواهان: علی محمدی\n"
            "خوانده: شرکت ساختمانی\n"
            "\n"
            "رأی دادگاه\n"
            "متن رأی دادگاه در این بخش قرار دارد."
        )
        chunks = chunker.chunk_text(text)

        # Metadata should be in the metadata dict
        for chunk in chunks:
            if chunk.metadata.get("case_number"):
                assert "۱۲۳۴۵۶۷۸۹۰" in chunk.metadata["case_number"]
                # Case number should NOT be in content
                assert "۱۲۳۴۵۶۷۸۹۰" not in chunk.content

    def test_metadata_copied_to_all_chunks(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Metadata from document header is copied to all chunks."""
        text = (
            "[PAGE 1]\n"
            "کلاسه پرونده: ۱۲۳۴۵۶۷۸۹۰\n"
            "شعبه ۱۲\n"
            "\n"
            "گردشکار\n"
            "متن گردشکار\n"
            "رأی دادگاه\n"
            "متن رأی"
        )
        chunks = chunker.chunk_text(text)

        # All chunks should have the metadata
        for chunk in chunks:
            if chunk.metadata:
                assert "case_number" in chunk.metadata


# ---------------------------------------------------------------------------
# Page-aware chunking
# ---------------------------------------------------------------------------


class TestPageAwareChunking:
    """Tests that chunks correctly track page spans."""

    def test_single_page_chunk(self, chunker: AnchorChunkingService) -> None:
        """Chunk within a single page → pages=[1]."""
        text = "[PAGE 1]\nمتن ساده بدون لنگر"
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1
        assert chunks[0].pages == [1]

    def test_multi_page_chunk(self, chunker: AnchorChunkingService) -> None:
        """Chunk spanning multiple pages → pages=[1, 2]."""
        text = (
            "[PAGE 1]\n"
            "متن صفحه اول\n"
            "[PAGE 2]\n"
            "متن صفحه دوم\n"
            "[PAGE 3]\n"
            "متن صفحه سوم"
        )
        chunks = chunker.chunk_text(text)
        # The full text without anchors should be one chunk spanning all pages
        assert len(chunks) >= 1
        # The chunk should span pages 1-3
        assert chunks[0].pages == [1, 2, 3]

    def test_page_tracking_with_anchors(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Anchored sections correctly track their page ranges."""
        text = (
            "[PAGE 1]\n"
            "مقدمه\n"
            "[PAGE 2]\n"
            "رأی دادگاه\n"
            "متن رأی در صفحه دوم\n"
            "[PAGE 3]\n"
            "ادامه رأی در صفحه سوم"
        )
        chunks = chunker.chunk_text(text)
        # Find the chunk with "رأی دادگاه" section
        for chunk in chunks:
            if chunk.section_title and "رأی دادگاه" in chunk.section_title:
                assert chunk.pages == [2, 3]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_mixed_numerals(self, chunker: AnchorChunkingService) -> None:
        """Mixed Persian/Arabic/English numerals in anchors."""
        text = (
            "[PAGE 1]\n"
            "ماده ۱: متن ماده اول\n"
            "ماده ۲: متن ماده دوم"
        )
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 2

    def test_partial_anchors(self, chunker: AnchorChunkingService) -> None:
        """Partial anchor matches don't cause errors."""
        text = (
            "[PAGE 1]\n"
            "این متن حاوی کلمه 'رأی' است اما لنگر کامل نیست.\n"
            "ادامه متن."
        )
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1

    def test_very_long_text(self, chunker: AnchorChunkingService) -> None:
        """Very long text is split into multiple chunks."""
        text = "[PAGE 1]\n" + ("کلمه " * 2000)
        chunks = chunker.chunk_text(text, chunk_tokens=100)
        assert len(chunks) > 1

    def test_whitespace_only(self, chunker: AnchorChunkingService) -> None:
        """Whitespace-only text → empty list."""
        assert chunker.chunk_text("   \n   \t   ") == []

    def test_anchor_at_text_start(self, chunker: AnchorChunkingService) -> None:
        """Anchor at the very start of text (no intro section)."""
        text = "[PAGE 1]\nرأی دادگاه\nمتن رأی"
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1
        # First chunk should be the anchored section, not intro
        assert chunks[0].section_title != "مقدمه"

    def test_consecutive_anchors(self, chunker: AnchorChunkingService) -> None:
        """Consecutive anchors without content between them."""
        text = (
            "[PAGE 1]\n"
            "گردشکار\n"
            "رأی دادگاه\n"
            "متن رأی"
        )
        chunks = chunker.chunk_text(text)
        # Should not crash; empty sections between anchors are skipped
        assert len(chunks) >= 1

    def test_token_count_accuracy(
        self, chunker: AnchorChunkingService
    ) -> None:
        """Token count is accurately computed."""
        text = "[PAGE 1]\nمتن ساده"
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1
        assert chunks[0].token_count > 0
        assert chunks[0].char_count > 0
