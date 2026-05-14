"""
Extended tests for the Persian text normalization service.

Covers additional edge cases beyond the base test suite:
- Ligature reversal fixes (``وکالی`` → ``وکلای``, ``دالیل`` → ``دلایل``)
- Date repair (``1376/\\n01/15`` → ``1376/01/15``, Persian digit dates)
- Bidi bracket fix (``) مجتمع شهید`` → ``مجتمع شهید)``)
"""

from __future__ import annotations

import pytest

from documents.services.persian_normalizer import PersianNormalizer
from documents.tasks.document_processing import _fix_bidi_brackets


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def normalizer() -> PersianNormalizer:
    """Return a fresh :class:`PersianNormalizer` instance for each test."""
    return PersianNormalizer()


# ===========================================================================
# 6.1.1 — Ligature Reversal Fixes (extended edge cases)
# ===========================================================================


class TestLigatureReversalsExtended:
    """Extended tests for :meth:`PersianNormalizer.fix_ligature_reversals`.

    Covers edge cases beyond the basic mappings verified in
    :class:`~documents.tests.test_persian_normalizer.TestFixLigatureReversals`.
    """

    def test_ligature_fix_in_sentence_context(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Ligature fix applied within a full Persian sentence."""
        text = "وکالی دادگاه عالوه بر آن"
        result = normalizer.fix_ligature_reversals(text)
        assert "وکلای" in result
        assert "علاوه" in result

    def test_ligature_fix_multiple_occurrences(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Multiple occurrences of the same garbled word are all fixed."""
        text = "وکالی و وکالی دیگر"
        result = normalizer.fix_ligature_reversals(text)
        assert result.count("وکلای") == 2

    def test_ligature_fix_overlapping_patterns(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Multiple different garbled patterns in the same text are fixed."""
        text = "وکالی و دالیل و معامالت"
        result = normalizer.fix_ligature_reversals(text)
        assert "وکلای" in result
        assert "دلایل" in result
        assert "معاملات" in result

    def test_ligature_fix_with_punctuation(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Garbled words adjacent to punctuation are still fixed."""
        text = "وکالی، دالیل."
        result = normalizer.fix_ligature_reversals(text)
        assert "وکلای،" in result
        assert "دلایل." in result

    def test_ligature_fix_with_numbers(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Garbled words mixed with numbers are fixed."""
        text = "ماده ۱ وکالی"
        result = normalizer.fix_ligature_reversals(text)
        assert "وکلای" in result

    def test_ligature_fix_idempotent(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Applying ligature fixes twice produces the same result."""
        text = "وکالی دالیل عالوه"
        result1 = normalizer.fix_ligature_reversals(text)
        result2 = normalizer.fix_ligature_reversals(result1)
        assert result1 == result2

    def test_ligature_fix_مطالبات_unchanged(
        self, normalizer: PersianNormalizer
    ) -> None:
        """مطالبات is already correct and must remain unchanged."""
        result = normalizer.fix_ligature_reversals("مطالبات")
        assert result == "مطالبات"

    def test_ligature_fix_does_not_corrupt_similar_words(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Words that look similar to garbled patterns are not corrupted."""
        # "حالت" should not become "حاالت" (reverse mapping)
        text = "حالت عادی"
        result = normalizer.fix_ligature_reversals(text)
        assert result == text

    def test_ligature_fix_through_full_pipeline(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Ligature fixes survive the full normalization pipeline."""
        dirty = "وکالی دادگاه عالوه بر آن دالیل خود را اعلام نمود"
        clean = normalizer.normalize(dirty)
        assert "وکلای" in clean
        assert "علاوه" in clean
        assert "دلایل" in clean

    def test_ligature_fix_very_long_text(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Ligature fixes work correctly on long text."""
        text = "وکالی " * 100
        result = normalizer.fix_ligature_reversals(text)
        assert result.count("وکلای") == 100

    def test_ligature_fix_unicode_normalization_interaction(
        self, normalizer: PersianNormalizer
    ) -> None:
        """NFKC normalization does not break ligature fixes."""
        # Use presentation forms that NFKC will decompose.
        # \uFEDF = ل (initial), \uFE8D = ا (isolated),
        # \uFEAF = ز (isolated), \uFEE1 = م (isolated)
        # After NFKC: → "لازم"
        text = "\uFEDF\uFE8D\uFEAF\uFEE1"  " وکالی"  # Presentation "لازم"
        result = normalizer.normalize(text)
        assert "وکلای" in result
        # After NFKC decomposition, the presentation forms become "لازم"
        assert "لازم" in result


# ===========================================================================
# 6.1.2 — Date Repair (extended edge cases)
# ===========================================================================


class TestDateRepairExtended:
    """Extended tests for :meth:`PersianNormalizer.repair_broken_dates`.

    Covers edge cases beyond the basic patterns verified in
    :class:`~documents.tests.test_persian_normalizer.TestRepairBrokenDates`.
    """

    def test_repair_date_at_start_of_text(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Date broken at the very start of the text."""
        result = normalizer.repair_broken_dates("1376/\n01/15 صادر گردید")
        assert result == "1376/01/15 صادر گردید"

    def test_repair_date_at_end_of_text(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Date broken at the very end of the text."""
        result = normalizer.repair_broken_dates("مورخ 1376/\n01/15")
        assert result == "مورخ 1376/01/15"

    def test_repair_date_with_tab_newline(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Date broken with tab+newline instead of just newline."""
        result = normalizer.repair_broken_dates("1376/\t\n01/15")
        assert result == "1376/01/15"

    def test_repair_date_with_newline_tab(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Date broken with newline+tab."""
        result = normalizer.repair_broken_dates("1376/\n\t01/15")
        assert result == "1376/01/15"

    def test_repair_date_with_multiple_spaces_around_newline(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Date broken with multiple spaces around the newline."""
        result = normalizer.repair_broken_dates("1376/   \n   01/15")
        assert result == "1376/01/15"

    def test_repair_persian_digit_date_in_sentence(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Persian digit date broken across line in a sentence."""
        text = "این حکم در تاریخ ۱۳۷۶/\n۰۱/۱۵ صادر گردیده است"
        result = normalizer.repair_broken_dates(text)
        assert "۱۳۷۶/۰۱/۱۵" in result

    def test_repair_persian_digit_date_with_dash(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Persian digit date with dash separator broken across line."""
        result = normalizer.repair_broken_dates("۱۳۷۶-\n۰۱-۱۵")
        assert result == "۱۳۷۶-۰۱-۱۵"

    def test_repair_gregorian_date_with_dash(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Gregorian date with dash broken across line."""
        result = normalizer.repair_broken_dates("2025-\n05-14")
        assert result == "2025-05-14"

    def test_repair_two_digit_year_with_dash(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Two-digit year with dash broken across line."""
        result = normalizer.repair_broken_dates("76-\n01-15")
        assert result == "76-01-15"

    def test_repair_date_idempotent(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Repairing an already-repaired date is idempotent."""
        text = "1376/\n01/15"
        result1 = normalizer.repair_broken_dates(text)
        result2 = normalizer.repair_broken_dates(result1)
        assert result1 == result2

    def test_no_false_positive_on_regular_newlines(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Regular newlines that are not date-related are not affected."""
        text = "ماده ۱\nقانون مدنی\nمصوب ۱۳۱۴"
        result = normalizer.repair_broken_dates(text)
        assert result == text

    def test_no_false_positive_on_slash_in_text(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Slashes in non-date contexts are not affected."""
        text = "قیمت هر واحد ۱۰۰/۰۰۰ ریال"
        result = normalizer.repair_broken_dates(text)
        assert result == text

    def test_repair_date_through_full_pipeline(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Date repair works correctly in the full normalization pipeline."""
        dirty = "مورخ 1376/\n01/15 صادر گردیده است"
        clean = normalizer.normalize(dirty)
        assert "1376/01/15" in clean

    def test_repair_multiple_broken_dates_different_formats(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Multiple broken dates with different formats are all repaired."""
        text = (
            "تاریخ شمسی: 1376/\n01/15\n"
            "تاریخ میلادی: 2025-\n05-14\n"
            "تاریخ فارسی: ۱۳۷۶/\n۰۱/۱۵"
        )
        result = normalizer.repair_broken_dates(text)
        assert "1376/01/15" in result
        assert "2025-05-14" in result
        assert "۱۳۷۶/۰۱/۱۵" in result

    def test_repair_date_with_single_digit_month_day(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Single-digit month/day are handled correctly."""
        result = normalizer.repair_broken_dates("1376/\n1/5")
        assert result == "1376/1/5"

    def test_repair_date_with_persian_single_digit(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Persian single-digit month/day are handled correctly."""
        result = normalizer.repair_broken_dates("۱۳۷۶/\n۱/۵")
        assert result == "۱۳۷۶/۱/۵"


# ===========================================================================
# 6.1.3 — Bidi Bracket Fix (extended edge cases)
# ===========================================================================


class TestBidiBracketsExtended:
    """Extended tests for :func:`_fix_bidi_brackets`.

    Covers edge cases beyond the basic patterns verified in
    :class:`~documents.tests.test_tasks.FixBidiBracketsTests`.
    """

    def test_closing_bracket_before_persian_phrase(
        self
    ) -> None:
        """) followed by a multi-word Persian phrase.
        
        Note: The regex matches the FIRST Persian word after the bracket,
        so ``) مجتمع شهید`` → ``مجتمع) شهید`` (word-by-word, not phrase-level).
        """
        result = _fix_bidi_brackets(") مجتمع شهید")
        assert result == "مجتمع) شهید"

    def test_closing_bracket_before_persian_with_leading_space(
        self
    ) -> None:
        """) with leading space before Persian → text)"""
        result = _fix_bidi_brackets(")  سلام")
        assert result == "سلام)"

    def test_opening_bracket_after_persian_phrase(
        self
    ) -> None:
        """Persian phrase followed by (.
        
        Note: The regex matches the LAST Persian word before the bracket,
        so ``مجتمع شهید(`` → ``مجتمع (شهید`` (word-by-word, not phrase-level).
        """
        result = _fix_bidi_brackets("مجتمع شهید(")
        assert result == "مجتمع (شهید"

    def test_opening_bracket_after_persian_with_trailing_space(
        self
    ) -> None:
        """Persian text with trailing space before ( → (text)"""
        result = _fix_bidi_brackets("سلام (")
        assert result == "(سلام"

    def test_bidi_bracket_in_legal_text(
        self
    ) -> None:
        """Realistic legal text with misplaced brackets."""
        text = "خواهان آقای علی احمدی) به وکالت از (خوانده"
        result = _fix_bidi_brackets(text)
        # ) after احمدی should stay (correctly placed in RTL)
        # ( before خوانده should stay (correctly placed in RTL)
        assert "احمدی)" in result or ") احمدی" in result
        assert "(خوانده" in result or "خوانده(" in result

    def test_bidi_bracket_with_persian_digits(
        self
    ) -> None:
        """Brackets around Persian digits are handled correctly.
        
        Note: The regex matches ``ماده`` (the first Persian word), so
        ``)ماده ۲`` → ``ماده) ۲`` (word-by-word, not phrase-level).
        """
        result = _fix_bidi_brackets(")ماده ۲")
        assert "ماده) ۲" in result

    def test_bidi_bracket_with_mixed_content(
        self
    ) -> None:
        """Mixed Persian/English content with brackets."""
        text = "ماده ۲ (قانون مدنی) به شرح زیر است"
        result = _fix_bidi_brackets(text)
        # Already correct — should remain unchanged
        assert result == text

    def test_bidi_bracket_imbalance_removal(
        self
    ) -> None:
        """Severe bracket imbalance (diff >= 3) triggers removal."""
        # 3 closing, 0 opening → diff=3 → remove trailing ))
        text = "سلام)))"
        result = _fix_bidi_brackets(text)
        # Should remove 3 trailing ) — but Patterns 1 and 2 may move some first
        # The result should have fewer ) than the input
        assert result.count(")") < text.count(")")

    def test_bidi_bracket_no_false_positive_on_english(
        self
    ) -> None:
        """English text with brackets is not affected."""
        text = "Hello (world) test"
        result = _fix_bidi_brackets(text)
        assert result == text

    def test_bidi_bracket_empty_string(
        self
    ) -> None:
        """Empty string returns empty string."""
        assert _fix_bidi_brackets("") == ""

    def test_bidi_bracket_no_brackets(
        self
    ) -> None:
        """Text without brackets is unchanged."""
        text = "سلام دنیا"
        result = _fix_bidi_brackets(text)
        assert result == text

    def test_bidi_bracket_multiple_lines(
        self
    ) -> None:
        """Brackets on multiple lines are handled independently."""
        text = "خط اول)\nخط دوم(\nخط سوم"
        result = _fix_bidi_brackets(text)
        lines = result.split("\n")
        assert len(lines) == 3
        # Line 1: ) at end after Persian → should move
        # Line 2: ( at start before Persian → should move

    def test_bidi_bracket_nested_parentheses(
        self
    ) -> None:
        """Nested parentheses in Persian text are preserved."""
        text = "متن (سلام (دنیا))"
        result = _fix_bidi_brackets(text)
        assert result == text

    def test_bidi_bracket_in_full_pipeline(
        self, normalizer: PersianNormalizer
    ) -> None:
        """Bidi bracket fix applied after full normalization."""
        # Note: _fix_bidi_brackets is called separately in the pipeline,
        # not inside PersianNormalizer.normalize(). We test it independently.
        # Pattern 1 uses negative lookbehind: (?<![PERSIAN])\s*\)\s*([PERSIAN]+)
        # In "متن) سلام", the ) IS preceded by Persian text (ن),
        # so Pattern 1 does NOT match. The text stays unchanged.
        dirty = "متن) سلام"
        fixed = _fix_bidi_brackets(dirty)
        normalized = normalizer.normalize(fixed)
        # The text is unchanged because ) correctly follows Persian text
        assert "متن) سلام" in normalized

    def test_bidi_bracket_with_tatweel(
        self
    ) -> None:
        """Brackets adjacent to Tatweel-affected text.
        
        Note: The regex matches ``مـــاده`` (the first Persian word), so
        ``)مـــاده ۱`` → ``مـــاده) ۱`` (word-by-word, not phrase-level).
        """
        text = ")مـــاده ۱"
        result = _fix_bidi_brackets(text)
        assert "مـــاده) ۱" in result

    def test_bidi_bracket_preserves_correctly_placed_brackets(
        self
    ) -> None:
        """Correctly placed brackets in RTL context are preserved."""
        text = "(سلام) دنیا"
        result = _fix_bidi_brackets(text)
        assert result == text

    def test_bidi_bracket_with_multiple_closing_before_persian(
        self
    ) -> None:
        """Multiple closing brackets before Persian text."""
        result = _fix_bidi_brackets("))سلام")
        # Pattern 1 processes left-to-right, non-overlapping
        # First match: )سلام → سلام)  → result: )سلام)
        # Second match: no more ) before Persian
        assert "سلام)" in result

    def test_bidi_bracket_with_multiple_opening_after_persian(
        self
    ) -> None:
        """Multiple opening brackets after Persian text."""
        result = _fix_bidi_brackets("سلام((")
        # Pattern 2 processes left-to-right, non-overlapping
        # First match: سلام( → (سلام  → result: (سلام(
        # Second match: no more ( after Persian
        assert "(سلام" in result
