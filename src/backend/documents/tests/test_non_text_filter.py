"""
Tests for the safe non-text section filtering module.

Covers:
- :class:`~documents.services.non_text_filter.TableOfContentsDetector`
- :class:`~documents.services.non_text_filter.NonTextChunkFilter`
- Integration with :class:`~documents.services.chunking_service.ChunkingService`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from documents.services.non_text_filter import (
    NonTextChunkFilter,
    TableOfContentsDetector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeChunkResult:
    """Minimal stand-in for :class:`~documents.services.anchor_chunking_service.AnchorChunk`.

    Only exposes the ``content`` attribute needed by the filter.
    """

    content: str
    page_start: int = 0
    page_end: int = 0
    char_count: int = 0
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    legal_type: Optional[str] = None
    legal_number: Optional[str] = None
    parent_article: Optional[str] = None


# ---------------------------------------------------------------------------
# TableOfContentsDetector
# ---------------------------------------------------------------------------


class TestTableOfContentsDetector:
    """Conservative TOC detection tests."""

    @pytest.fixture
    def detector(self) -> TableOfContentsDetector:
        return TableOfContentsDetector()

    def test_toc_with_title_and_page_numbers(
        self, detector: TableOfContentsDetector
    ) -> None:
        """Persian TOC with title and page numbers is detected."""
        text = (
            "فهرست مطالب\n"
            "مقدمه ۱\n"
            "فصل اول ۲\n"
            "فصل دوم ۳\n"
            "فصل سوم ۴\n"
            "فصل چهارم ۵"
        )
        assert detector.is_non_text(text) is True

    def test_toc_with_dotted_lines(
        self, detector: TableOfContentsDetector
    ) -> None:
        """Persian TOC with dotted separators is detected."""
        text = (
            "فهرست مطالب\n"
            "مقدمه........ ۱\n"
            "فصل اول...... ۲\n"
            "فصل دوم...... ۳"
        )
        assert detector.is_non_text(text) is True

    def test_no_title_returns_false(
        self, detector: TableOfContentsDetector
    ) -> None:
        """Without an explicit TOC title, detection returns False."""
        text = (
            "مقدمه ۱\n"
            "فصل اول ۲\n"
            "فصل دوم ۳"
        )
        assert detector.is_non_text(text) is False

    def test_few_structural_lines(
        self, detector: TableOfContentsDetector
    ) -> None:
        """Fewer than 3 structural lines is not detected as TOC."""
        text = (
            "فهرست مطالب\n"
            "مقدمه... ۱\n"
            "فصل اول... ۲"
        )
        assert detector.is_non_text(text) is False

    def test_low_structural_ratio(
        self, detector: TableOfContentsDetector
    ) -> None:
        """Structural ratio below 40% is not detected as TOC."""
        text = (
            "فهرست مطالب\n"
            "مقدمه... ۱\n"
            "متن بلند اینجا قرار دارد که نسبت را پایین می‌آورد\n"
            "متن بلند دیگر\n"
            "متن بلند دیگر"
        )
        assert detector.is_non_text(text) is False

    def test_english_toc(self, detector: TableOfContentsDetector) -> None:
        """English 'Table of Contents' is detected."""
        text = (
            "Table of Contents\n"
            "Introduction 1\n"
            "Chapter 1 2\n"
            "Chapter 2 3\n"
            "Chapter 3 4"
        )
        assert detector.is_non_text(text) is True

    def test_legal_article_not_toc(
        self, detector: TableOfContentsDetector
    ) -> None:
        """A real legal article containing the word 'فهرست' is NOT filtered."""
        text = (
            "ماده ۱: فهرست اموال منقول شامل موارد زیر است:\n"
            "۱- خودرو\n"
            "۲- ملک\n"
            "۳- اثاثیه"
        )
        assert detector.is_non_text(text) is False

    def test_empty_text(self, detector: TableOfContentsDetector) -> None:
        """Empty text returns False."""
        assert detector.is_non_text("") is False

    def test_whitespace_only(self, detector: TableOfContentsDetector) -> None:
        """Whitespace-only text returns False."""
        assert detector.is_non_text("   \n  ") is False

    def test_persian_toc_alternative_title(
        self, detector: TableOfContentsDetector
    ) -> None:
        """Alternative Persian TOC title 'فهرست مندرجات' is detected."""
        text = (
            "فهرست مندرجات\n"
            "بخش اول ۱\n"
            "بخش دوم ۲\n"
            "بخش سوم ۳\n"
            "بخش چهارم ۴"
        )
        assert detector.is_non_text(text) is True

    def test_toc_with_arabic_digits(
        self, detector: TableOfContentsDetector
    ) -> None:
        """TOC with Arabic (Eastern) digits is detected."""
        text = (
            "فهرست مطالب\n"
            "المقدمة ١\n"
            "الفصل الأول ٢\n"
            "الفصل الثاني ٣"
        )
        assert detector.is_non_text(text) is True

    def test_toc_title_appears_later_in_text(
        self, detector: TableOfContentsDetector
    ) -> None:
        """TOC title beyond the first 300 chars is not detected (safe miss)."""
        # Build a long preamble so the title falls outside the scan window
        preamble = "x" * 301
        text = (
            f"{preamble}\n"
            "فهرست مطالب\n"
            "مقدمه ۱\n"
            "فصل اول ۲\n"
            "فصل دوم ۳\n"
            "فصل سوم ۴"
        )
        # Title is at char 302+, beyond the 300-char scan limit
        assert detector.is_non_text(text) is False


# ---------------------------------------------------------------------------
# NonTextChunkFilter
# ---------------------------------------------------------------------------


class TestNonTextChunkFilter:
    """Orchestrator-level tests."""

    @pytest.fixture
    def filter_(self) -> NonTextChunkFilter:
        return NonTextChunkFilter()

    def test_filters_toc_chunks(self, filter_: NonTextChunkFilter) -> None:
        """TOC chunks are removed, real chunks are preserved."""
        chunks = [
            FakeChunkResult(content="ماده ۱: این یک ماده قانونی است."),
            FakeChunkResult(
                content=(
                    "فهرست مطالب\n"
                    "مقدمه ۱\n"
                    "فصل اول ۲\n"
                    "فصل دوم ۳\n"
                    "فصل سوم ۴"
                )
            ),
            FakeChunkResult(content="ماده ۲: این ماده دوم است."),
        ]
        result = filter_.filter_chunks(chunks)
        assert len(result) == 2
        assert all("فهرست" not in c.content for c in result)

    def test_passes_all_real_chunks(self, filter_: NonTextChunkFilter) -> None:
        """All real content chunks are preserved unchanged."""
        chunks = [
            FakeChunkResult(content="ماده ۱: متن قانونی."),
            FakeChunkResult(content="ماده ۲: متن قانونی دیگر."),
            FakeChunkResult(content="ماده ۳: متن قانونی سوم."),
        ]
        result = filter_.filter_chunks(chunks)
        assert len(result) == 3
        assert result == chunks

    def test_empty_chunks_list(self, filter_: NonTextChunkFilter) -> None:
        """Empty input returns empty output."""
        assert filter_.filter_chunks([]) == []

    def test_single_toc_chunk(self, filter_: NonTextChunkFilter) -> None:
        """A single TOC chunk results in an empty list."""
        chunks = [
            FakeChunkResult(
                content=(
                    "فهرست مطالب\n"
                    "بخش اول ۱\n"
                    "بخش دوم ۲\n"
                    "بخش سوم ۳"
                )
            ),
        ]
        assert filter_.filter_chunks(chunks) == []

    def test_custom_detector_chain(
        self,
    ) -> None:
        """Custom detector chain is used when provided."""
        class AlwaysTrueDetector:
            def is_non_text(self, chunk_text: str) -> bool:
                return True

        filter_ = NonTextChunkFilter(detectors=[AlwaysTrueDetector()])
        chunks = [
            FakeChunkResult(content="any content"),
        ]
        assert filter_.filter_chunks(chunks) == []

    def test_custom_detector_chain_all_pass(
        self,
    ) -> None:
        """Custom detector chain preserves chunks when none match."""
        class AlwaysFalseDetector:
            def is_non_text(self, chunk_text: str) -> bool:
                return False

        filter_ = NonTextChunkFilter(detectors=[AlwaysFalseDetector()])
        chunks = [
            FakeChunkResult(content="any content"),
        ]
        result = filter_.filter_chunks(chunks)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Integration with ChunkingService (via FakeChunkResult)
# ---------------------------------------------------------------------------


class TestIntegrationWithChunkingService:
    """Simulates the real pipeline: chunking → filtering → persistence."""

    @pytest.fixture
    def filter_(self) -> NonTextChunkFilter:
        return NonTextChunkFilter()

    def test_toc_at_start_of_document(
        self, filter_: NonTextChunkFilter
    ) -> None:
        """TOC at the start is filtered; article chunks are preserved."""
        # Simulate chunks as they would come from ChunkingService
        chunks = [
            FakeChunkResult(
                content=(
                    "فهرست مطالب\n"
                    "مقدمه ۱\n"
                    "فصل اول ۲\n"
                    "فصل دوم ۳\n"
                    "فصل سوم ۴"
                ),
                page_start=1,
                page_end=1,
            ),
            FakeChunkResult(
                content="ماده ۱: این قانون برای تنظیم روابط اجتماعی وضع می‌شود.",
                page_start=2,
                page_end=2,
            ),
            FakeChunkResult(
                content="ماده ۲: اجرای این قانون از تاریخ تصویب لازم‌الاجراست.",
                page_start=2,
                page_end=3,
            ),
        ]
        result = filter_.filter_chunks(chunks)
        assert len(result) == 2
        assert all(c.page_start >= 2 for c in result)

    def test_toc_in_middle_of_document(
        self, filter_: NonTextChunkFilter
    ) -> None:
        """TOC between chapters is filtered; surrounding chunks preserved."""
        chunks = [
            FakeChunkResult(
                content="ماده ۱: متن فصل اول.",
                page_start=1,
                page_end=2,
            ),
            FakeChunkResult(
                content=(
                    "فهرست مطالب\n"
                    "فصل اول ۱\n"
                    "فصل دوم ۲\n"
                    "فصل سوم ۳\n"
                    "فصل چهارم ۴"
                ),
                page_start=3,
                page_end=3,
            ),
            FakeChunkResult(
                content="ماده ۱۰: متن فصل دوم.",
                page_start=4,
                page_end=5,
            ),
        ]
        result = filter_.filter_chunks(chunks)
        assert len(result) == 2
        # The middle TOC chunk should be removed
        assert all("فهرست" not in c.content for c in result)
        assert result[0].page_start == 1
        assert result[1].page_start == 4
