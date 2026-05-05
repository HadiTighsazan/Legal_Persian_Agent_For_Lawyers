"""
Tests for the Persian legal structure detector.

Tests cover:
- Detection of ماده (Article) with various numeral systems and spacing
- Detection of تبصره (Note) attached to articles
- Detection of بند (Clause) with numeric and alphabetic markers
- Detection of فصل (Chapter) with numerals and Persian ordinals
- Tatweel handling in structural markers
- Mixed numeral systems (Persian, Arabic, English)
- Documents with no legal structure (fallback to plain text)
- Metadata attachment (parent article, chapter)
"""

from __future__ import annotations

import pytest

from documents.services.legal_structure_detector import (
    LegalStructureDetector,
    LegalSegment,
)


@pytest.fixture
def detector() -> LegalStructureDetector:
    """Return a fresh :class:`LegalStructureDetector` instance for each test."""
    return LegalStructureDetector()


# ---------------------------------------------------------------------------
# ماده (Article) detection
# ---------------------------------------------------------------------------


class TestArticleDetection:
    def test_single_article(self, detector: LegalStructureDetector) -> None:
        """Single ماده ۱ is detected"""
        text = "ماده ۱: این قانون برای تنظیم روابط اجتماعی وضع می‌شود."
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 1
        assert articles[0].segment_number == "۱"

    def test_multiple_articles(self, detector: LegalStructureDetector) -> None:
        """Multiple مواد are detected"""
        text = "ماده ۱: متن ماده اول.\nماده ۲: متن ماده دوم.\nماده ۳: متن ماده سوم."
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 3
        assert articles[0].segment_number == "۱"
        assert articles[1].segment_number == "۲"
        assert articles[2].segment_number == "۳"

    def test_article_without_space(self, detector: LegalStructureDetector) -> None:
        """ماده1 (no space) is detected"""
        text = "ماده1: متن ماده اول."
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 1
        assert articles[0].segment_number == "1"

    def test_article_with_zwnj(self, detector: LegalStructureDetector) -> None:
        """ماده‌۱ (with ZWNJ) is detected"""
        text = "ماده\u200c۱: متن ماده اول."
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 1
        assert articles[0].segment_number == "۱"

    def test_article_with_tatweel(self, detector: LegalStructureDetector) -> None:
        """مـــاده ۱ (with Tatweel) is detected after stripping"""
        text = "مـــاده ۱: متن ماده اول."
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 1
        assert articles[0].segment_number == "۱"

    def test_article_with_english_numeral(self, detector: LegalStructureDetector) -> None:
        """ماده 1 (English numeral) is detected"""
        text = "ماده 1: متن ماده اول."
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 1
        assert articles[0].segment_number == "1"

    def test_article_with_arabic_numeral(self, detector: LegalStructureDetector) -> None:
        """ماده ١ (Arabic numeral) is detected"""
        text = "ماده ١: متن ماده اول."
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 1
        assert articles[0].segment_number == "١"


# ---------------------------------------------------------------------------
# تبصره (Note) detection
# ---------------------------------------------------------------------------


class TestNoteDetection:
    def test_note_with_number(self, detector: LegalStructureDetector) -> None:
        """تبصره ۱ is detected"""
        text = "ماده ۱: متن ماده.\nتبصره ۱: متن تبصره."
        segments = detector.detect_structure(text)
        notes = [s for s in segments if s.segment_type == "note"]
        assert len(notes) == 1
        assert notes[0].segment_number == "۱"

    def test_note_without_number(self, detector: LegalStructureDetector) -> None:
        """تبصره without number is detected"""
        text = "ماده ۱: متن ماده.\nتبصره: متن تبصره بدون شماره."
        segments = detector.detect_structure(text)
        notes = [s for s in segments if s.segment_type == "note"]
        assert len(notes) == 1
        assert notes[0].segment_number is None

    def test_multiple_notes(self, detector: LegalStructureDetector) -> None:
        """Multiple تبصره‌ها are detected"""
        text = "ماده ۱: متن.\nتبصره ۱: تبصره اول.\nتبصره ۲: تبصره دوم."
        segments = detector.detect_structure(text)
        notes = [s for s in segments if s.segment_type == "note"]
        assert len(notes) == 2
        assert notes[0].segment_number == "۱"
        assert notes[1].segment_number == "۲"


# ---------------------------------------------------------------------------
# بند (Clause) detection
# ---------------------------------------------------------------------------


class TestClauseDetection:
    def test_numeric_clause(self, detector: LegalStructureDetector) -> None:
        """۱- (numeric clause) is detected"""
        text = "ماده ۱:\n۱- بند اول\n۲- بند دوم"
        segments = detector.detect_structure(text)
        clauses = [s for s in segments if s.segment_type == "clause"]
        assert len(clauses) == 2
        assert clauses[0].segment_number == "۱"
        assert clauses[1].segment_number == "۲"

    def test_alphabetic_clause(self, detector: LegalStructureDetector) -> None:
        """الف- (alphabetic clause) is detected"""
        text = "ماده ۱:\nالف- بند الف\nب- بند ب"
        segments = detector.detect_structure(text)
        clauses = [s for s in segments if s.segment_type == "clause"]
        assert len(clauses) == 2
        assert clauses[0].segment_number == "الف"
        assert clauses[1].segment_number == "ب"

    def test_clause_with_zwnj(self, detector: LegalStructureDetector) -> None:
        """۱- with ZWNJ instead of dash is detected"""
        text = "ماده ۱:\n۱\u200cبند اول"
        segments = detector.detect_structure(text)
        clauses = [s for s in segments if s.segment_type == "clause"]
        assert len(clauses) >= 1


# ---------------------------------------------------------------------------
# فصل (Chapter) detection
# ---------------------------------------------------------------------------


class TestChapterDetection:
    def test_chapter_with_numeral(self, detector: LegalStructureDetector) -> None:
        """فصل ۱ is detected"""
        text = "فصل ۱: مقررات عمومی\nماده ۱: متن ماده."
        segments = detector.detect_structure(text)
        chapters = [s for s in segments if s.segment_type == "chapter"]
        assert len(chapters) == 1
        assert chapters[0].segment_number == "۱"

    def test_chapter_with_ordinal(self, detector: LegalStructureDetector) -> None:
        """فصل اول is detected"""
        text = "فصل اول: مقررات عمومی"
        segments = detector.detect_structure(text)
        chapters = [s for s in segments if s.segment_type == "chapter"]
        assert len(chapters) == 1
        assert chapters[0].segment_number == "اول"

    def test_multiple_chapters(self, detector: LegalStructureDetector) -> None:
        """Multiple chapters are detected"""
        text = "فصل ۱: مقررات عمومی\nفصل ۲: مقررات اختصاصی"
        segments = detector.detect_structure(text)
        chapters = [s for s in segments if s.segment_type == "chapter"]
        assert len(chapters) == 2


# ---------------------------------------------------------------------------
# Full document structure
# ---------------------------------------------------------------------------


class TestFullDocumentStructure:
    def test_complete_legal_document(self, detector: LegalStructureDetector) -> None:
        """A complete legal document with all structure types"""
        text = (
            "فصل ۱: مقررات عمومی\n"
            "ماده ۱: این قانون برای تنظیم روابط اجتماعی وضع می‌شود.\n"
            "تبصره ۱: مقررات این ماده شامل موارد زیر نمی‌شود.\n"
            "ماده ۲: مقررات مربوط به قراردادها\n"
            "۱- قراردادها باید کتبی باشند.\n"
            "۲- قراردادها باید ثبت شوند.\n"
            "تبصره: قراردادهای کوچک از این قاعده مستثنی هستند.\n"
            "فصل ۲: مقررات اختصاصی\n"
            "ماده ۳: مقررات ویژه"
        )
        segments = detector.detect_structure(text)

        chapters = [s for s in segments if s.segment_type == "chapter"]
        articles = [s for s in segments if s.segment_type == "article"]
        notes = [s for s in segments if s.segment_type == "note"]
        clauses = [s for s in segments if s.segment_type == "clause"]

        assert len(chapters) == 2
        assert len(articles) == 3
        assert len(notes) == 2
        assert len(clauses) == 2

    def test_metadata_attachment(self, detector: LegalStructureDetector) -> None:
        """Notes and clauses get parent_article metadata"""
        text = "فصل ۱: کلیات\nماده ۱: متن ماده.\nتبصره ۱: متن تبصره.\nماده ۲:\n۱- بند اول"
        segments = detector.detect_structure(text)

        # Find the note
        note = next(s for s in segments if s.segment_type == "note")
        assert note.metadata.get("parent_article") == "۱"
        assert note.metadata.get("chapter") == "۱"

        # Find the clause
        clause = next(s for s in segments if s.segment_type == "clause")
        assert clause.metadata.get("parent_article") == "۲"
        assert clause.metadata.get("chapter") == "۱"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_text(self, detector: LegalStructureDetector) -> None:
        """Empty text returns empty list"""
        assert detector.detect_structure("") == []

    def test_no_legal_structure(self, detector: LegalStructureDetector) -> None:
        """Plain text with no legal structure returns single text segment"""
        text = "این یک متن ساده است و ساختار حقوقی ندارد."
        segments = detector.detect_structure(text)
        assert len(segments) == 1
        assert segments[0].segment_type == "text"
        assert segments[0].segment_number is None

    def test_english_text(self, detector: LegalStructureDetector) -> None:
        """English text returns single text segment"""
        text = "This is a plain English document with no legal structure."
        segments = detector.detect_structure(text)
        assert len(segments) == 1
        assert segments[0].segment_type == "text"

    def test_has_legal_structure_true(self, detector: LegalStructureDetector) -> None:
        """has_legal_structure returns True for documents with ماده"""
        text = "ماده ۱: متن ماده."
        assert detector.has_legal_structure(text) is True

    def test_has_legal_structure_false(self, detector: LegalStructureDetector) -> None:
        """has_legal_structure returns False for plain text"""
        text = "این یک متن ساده است."
        assert detector.has_legal_structure(text) is False

    def test_has_legal_structure_empty(self, detector: LegalStructureDetector) -> None:
        """has_legal_structure returns False for empty text"""
        assert detector.has_legal_structure("") is False

    def test_mixed_numerals_in_document(self, detector: LegalStructureDetector) -> None:
        """Mixed Persian, Arabic, and English numerals are all detected"""
        text = "ماده ۱: Persian\nماده 2: English\nماده ٣: Arabic"
        segments = detector.detect_structure(text)
        articles = [s for s in segments if s.segment_type == "article"]
        assert len(articles) == 3
        numbers = [a.segment_number for a in articles]
        assert "۱" in numbers
        assert "2" in numbers
        assert "٣" in numbers
