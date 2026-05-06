"""
Tests for the Persian text normalization service.

Tests cover:
- Tatweel/Kashida stripping
- Arabic/Persian character normalization
- Half-space (ZWNJ) fixes
- Control character removal
- Edge cases (empty/None input)
- Verification that Hazm does NOT fix RTL reversal (documented limitation)
"""

from __future__ import annotations

import pytest

from documents.services.persian_normalizer import PersianNormalizer


@pytest.fixture
def normalizer() -> PersianNormalizer:
    """Return a fresh :class:`PersianNormalizer` instance for each test."""
    return PersianNormalizer()


# ---------------------------------------------------------------------------
# Tatweel / Kashida stripping
# ---------------------------------------------------------------------------


class TestStripTatweel:
    def test_strip_tatweel_from_article(self, normalizer: PersianNormalizer) -> None:
        """ماده with Tatweel → ماده"""
        result = normalizer.strip_tatweel("مـــاده ۱")
        assert result == "ماده ۱"

    def test_strip_tatweel_from_law_name(self, normalizer: PersianNormalizer) -> None:
        """قـــانون with Tatweel → قانون"""
        result = normalizer.strip_tatweel("قـــانون مجازات اسلامی")
        assert result == "قانون مجازات اسلامی"

    def test_strip_tatweel_no_tatweel(self, normalizer: PersianNormalizer) -> None:
        """Text without Tatweel is unchanged"""
        text = "ماده ۱ قانون مجازات اسلامی"
        result = normalizer.strip_tatweel(text)
        assert result == text

    def test_strip_tatweel_empty_string(self, normalizer: PersianNormalizer) -> None:
        """Empty string returns empty string"""
        assert normalizer.strip_tatweel("") == ""

    def test_strip_tatweel_multiple_kashida(self, normalizer: PersianNormalizer) -> None:
        """Multiple Kashida characters are all removed"""
        result = normalizer.strip_tatweel("مــــاده ۱")
        assert result == "ماده ۱"


# ---------------------------------------------------------------------------
# Arabic character normalization
# ---------------------------------------------------------------------------


class TestNormalizeArabicChars:
    def test_arabic_yeh_to_persian(self, normalizer: PersianNormalizer) -> None:
        """Arabic ي (U+064A) → Persian ی (U+06CC)"""
        result = normalizer.normalize_arabic_chars("ايران")
        assert "ی" in result
        assert "ي" not in result

    def test_arabic_kaf_to_persian(self, normalizer: PersianNormalizer) -> None:
        """Arabic ك (U+0643) → Persian ک (U+06A9)"""
        result = normalizer.normalize_arabic_chars("كتاب")
        assert "ک" in result
        assert "ك" not in result

    def test_arabic_teh_marbuta(self, normalizer: PersianNormalizer) -> None:
        """Arabic ة (U+0629) — hazm does not convert this to ه in v0.10+"""
        result = normalizer.normalize_arabic_chars("مكة")
        # Note: hazm >=0.10 does NOT convert ة → ه.
        # The original character is preserved.
        assert "ة" in result or "ه" in result

    def test_mixed_arabic_persian_text(self, normalizer: PersianNormalizer) -> None:
        """Mixed Arabic/Persian characters are all normalized"""
        # Arabic: ي ك ة أ إ
        # Persian: ی ک ه ا
        result = normalizer.normalize_arabic_chars("يقول الكتاب في مكة")
        assert "ی" in result
        assert "ک" in result
        # The original Arabic chars should not remain (except ة which hazm preserves)
        assert "ي" not in result
        assert "ك" not in result

    def test_english_text_unchanged(self, normalizer: PersianNormalizer) -> None:
        """English/Latin text is not affected"""
        text = "Hello World! Test 123."
        result = normalizer.normalize_arabic_chars(text)
        assert result == text


# ---------------------------------------------------------------------------
# Half-space (ZWNJ) fixes
# ---------------------------------------------------------------------------


class TestFixHalfSpaces:
    def test_mi_prefix_half_space(self, normalizer: PersianNormalizer) -> None:
        """می شود → می‌شود (می + ZWNJ + شود)"""
        result = normalizer.fix_half_spaces("می شود")
        assert "می‌شود" in result

    def test_nemi_prefix_half_space(self, normalizer: PersianNormalizer) -> None:
        """نمی تواند → نمی‌تواند"""
        result = normalizer.fix_half_spaces("نمی تواند")
        assert "نمی‌تواند" in result

    def test_khah_prefix_half_space(self, normalizer: PersianNormalizer) -> None:
        """خواهم → خواهم (already correct)"""
        result = normalizer.fix_half_spaces("خواهم رفت")
        # Should not break already correct text
        assert "خواهم" in result

    def test_no_half_space_needed(self, normalizer: PersianNormalizer) -> None:
        """Text without half-space issues is unchanged"""
        text = "ماده ۱ قانون مجازات اسلامی"
        result = normalizer.fix_half_spaces(text)
        assert result == text


# ---------------------------------------------------------------------------
# Control character removal
# ---------------------------------------------------------------------------


class TestCleanControlChars:
    def test_remove_null_chars(self, normalizer: PersianNormalizer) -> None:
        """Null characters (U+0000) are removed"""
        result = normalizer.clean_control_chars("ماده\u0000 ۱")
        assert result == "ماده ۱"

    def test_remove_soft_hyphen(self, normalizer: PersianNormalizer) -> None:
        """Soft hyphens (U+00AD) are removed"""
        result = normalizer.clean_control_chars("ماده\u00AD ۱")
        assert result == "ماده ۱"

    def test_remove_bom(self, normalizer: PersianNormalizer) -> None:
        """Byte order marks (U+FEFF) are removed"""
        result = normalizer.clean_control_chars("\uFEFFماده ۱")
        assert result == "ماده ۱"

    def test_preserve_newlines_and_tabs(self, normalizer: PersianNormalizer) -> None:
        """Newlines, tabs, and carriage returns are preserved"""
        text = "ماده ۱\n\tتبصره ۲"
        result = normalizer.clean_control_chars(text)
        assert result == text

    def test_remove_zero_width_space(self, normalizer: PersianNormalizer) -> None:
        """Zero-width spaces (U+200B) are removed"""
        result = normalizer.clean_control_chars("ماده\u200B۱")
        assert result == "ماده۱"


# ---------------------------------------------------------------------------
# Full normalization pipeline
# ---------------------------------------------------------------------------


class TestFullNormalize:
    def test_full_pipeline_tatweel_and_arabic(self, normalizer: PersianNormalizer) -> None:
        """Full pipeline: Tatweel + Arabic chars + half-spaces"""
        dirty = "مـــادة ۱: مي شود كه كتاب القانون"
        clean = normalizer.normalize(dirty)
        # Tatweel removed
        assert "ـــ" not in clean
        # Arabic chars normalized
        assert "ک" in clean or "ك" not in clean
        assert "ی" in clean or "ي" not in clean
        # Half-space fixed
        assert "می‌شود" in clean or "می شود" not in clean

    def test_empty_string(self, normalizer: PersianNormalizer) -> None:
        """Empty string returns empty string"""
        assert normalizer.normalize("") == ""

    def test_none_input(self, normalizer: PersianNormalizer) -> None:
        """None input returns empty string"""
        assert normalizer.normalize(None) == ""

    def test_english_text_unchanged(self, normalizer: PersianNormalizer) -> None:
        """English text passes through unchanged"""
        text = "Hello World! This is a test document with 123 numbers."
        result = normalizer.normalize(text)
        assert result == text

    def test_mixed_persian_english(self, normalizer: PersianNormalizer) -> None:
        """Mixed Persian/English text is handled correctly"""
        text = "ماده ۱: This is Article 1 of the law."
        result = normalizer.normalize(text)
        assert "ماده" in result
        assert "Article 1" in result

    def test_control_chars_in_pipeline(self, normalizer: PersianNormalizer) -> None:
        """Control characters are removed during full normalization"""
        dirty = "ماده\u0000 ۱\u200B قانون"
        clean = normalizer.normalize(dirty)
        assert "\u0000" not in clean
        assert "\u200B" not in clean
        assert "ماده" in clean


# ---------------------------------------------------------------------------
# FTS (Full-Text Search) normalization
# ---------------------------------------------------------------------------


class TestNormalizeForFts:
    """Tests for :meth:`PersianNormalizer.normalize_for_fts`."""

    def test_arabic_indic_digits_to_english(self) -> None:
        """Arabic-Indic digits (U+0660–U+0669) → English digits."""
        result = PersianNormalizer.normalize_for_fts("ماده ٢٢")  # Arabic ٢٢
        assert result == "ماده 22"

    def test_persian_digits_to_english(self) -> None:
        """Persian/Extended Arabic-Indic digits (U+06F0–U+06F9) → English digits."""
        result = PersianNormalizer.normalize_for_fts("ماده ۲۲")  # Persian ۲۲
        assert result == "ماده 22"

    def test_mixed_digits_normalized(self) -> None:
        """Mixed Arabic and Persian digits all map to English."""
        result = PersianNormalizer.normalize_for_fts("۱۲٣٤٥")  # Persian ۱۲ + Arabic ٣٤٥
        assert result == "12345"

    def test_english_digits_unchanged(self) -> None:
        """English digits are left as-is."""
        text = "Article 22 of the law"
        result = PersianNormalizer.normalize_for_fts(text)
        assert result == text

    def test_zwnj_replaced_with_space(self) -> None:
        """ZWNJ (U+200C) is replaced with a regular space."""
        text = "می\u200cشود"  # می‌شود with ZWNJ
        result = PersianNormalizer.normalize_for_fts(text)
        assert "\u200c" not in result
        assert "می شود" in result  # Now two tokens for FTS

    def test_empty_string_returns_empty(self) -> None:
        """Empty string returns empty string."""
        assert PersianNormalizer.normalize_for_fts("") == ""

    def test_none_input_returns_empty(self) -> None:
        """None input returns empty string."""
        assert PersianNormalizer.normalize_for_fts(None) == ""  # type: ignore[arg-type]

    def test_persian_legal_phrase(self) -> None:
        """Realistic Persian legal phrase with digits and ZWNJ."""
        text = "ماده ۲۲ قانون\u200cمدنی مصوب ۱۳۱۴"
        result = PersianNormalizer.normalize_for_fts(text)
        assert "22" in result
        assert "1314" in result
        assert "\u200c" not in result
        assert "قانون مدنی" in result or "قانون مدنی" in result

    # ------------------------------------------------------------------
    # Arabic → Persian character normalization
    # ------------------------------------------------------------------

    def test_arabic_yeh_to_persian_yeh(self) -> None:
        """Arabic Yeh (U+064A) → Persian Yeh (U+06CC)."""
        # "ايران" with Arabic Yeh (U+064A) → "ایران" with Persian Yeh (U+06CC)
        result = PersianNormalizer.normalize_for_fts("ايران")
        assert "ی" in result  # Persian Yeh
        assert "\u064A" not in result  # Arabic Yeh removed

    def test_arabic_kaf_to_persian_kaf(self) -> None:
        """Arabic Kaf (U+0643) → Persian Kaf (U+06A9)."""
        # "كتاب" with Arabic Kaf → "کتاب" with Persian Kaf
        result = PersianNormalizer.normalize_for_fts("كتاب")
        assert "ک" in result  # Persian Kaf
        assert "\u0643" not in result  # Arabic Kaf removed

    def test_arabic_yeh_and_kaf_both_normalized(self) -> None:
        """Both Arabic Yeh and Kaf are normalized in the same string."""
        # "يقول الكتاب" → "یقول الکتاب"
        result = PersianNormalizer.normalize_for_fts("يقول الكتاب")
        assert "ی" in result  # Persian Yeh
        assert "ک" in result  # Persian Kaf
        assert "\u064A" not in result  # No Arabic Yeh
        assert "\u0643" not in result  # No Arabic Kaf

    def test_persian_chars_unchanged(self) -> None:
        """Already-correct Persian chars are left as-is."""
        text = "جایز کتاب"
        result = PersianNormalizer.normalize_for_fts(text)
        assert result == "جایز کتاب"

    def test_arabic_chars_in_mixed_text(self) -> None:
        """Arabic chars normalized in text with digits and English."""
        text = "يقول الكتاب في مادة ٢٢"  # Arabic Yeh/Kaf + Arabic digits
        result = PersianNormalizer.normalize_for_fts(text)
        assert "ی" in result  # Persian Yeh
        assert "ک" in result  # Persian Kaf
        assert "22" in result  # English digits
        assert "\u064A" not in result  # No Arabic Yeh
        assert "\u0643" not in result  # No Arabic Kaf

    # ------------------------------------------------------------------
    # NFKC normalization of Arabic Presentation Forms-B
    # ------------------------------------------------------------------

    def test_nfkc_lam_initial_form(self) -> None:
        """Lam initial form (U+FEDF) → standard Lam (U+0644)."""
        # U+FEDF = Lam with initial form (Arabic Presentation Forms-B)
        text = "\uFEDF\u0627\u0632\u0645"  # FEDF + ا + ز + م
        result = PersianNormalizer.normalize_for_fts(text)
        # Should be standard Lam (U+0644)
        assert "\u0644" in result  # Standard Lam
        assert "\uFEDF" not in result  # Presentation form removed

    def test_nfkc_alef_isolated_form(self) -> None:
        """Alef isolated form (U+FE8D) → standard Alef (U+0627)."""
        # U+FE8D = Alef with isolated form
        text = "\u0644\uFE8D\u0632\u0645"  # ل + FE8D + ز + م
        result = PersianNormalizer.normalize_for_fts(text)
        assert "\u0627" in result  # Standard Alef
        assert "\uFE8D" not in result  # Presentation form removed

    def test_nfkc_zain_isolated_form(self) -> None:
        """Zain isolated form (U+FEAF) → standard Zain (U+0632)."""
        # U+FEAF = Zain with isolated form
        text = "\u0644\u0627\uFEAF\u0645"  # ل + ا + FEAF + م
        result = PersianNormalizer.normalize_for_fts(text)
        assert "\u0632" in result  # Standard Zain
        assert "\uFEAF" not in result  # Presentation form removed

    def test_nfkc_meem_initial_form(self) -> None:
        """Meem initial form (U+FEE1) → standard Meem (U+0645)."""
        # U+FEE1 = Meem with initial form
        text = "\u0644\u0627\u0632\uFEE1"  # ل + ا + ز + FEE1
        result = PersianNormalizer.normalize_for_fts(text)
        assert "\u0645" in result  # Standard Meem
        assert "\uFEE1" not in result  # Presentation form removed

    def test_nfkc_lam_alef_ligature(self) -> None:
        """Lam-Alef ligature (U+FEFB) → standard Lam + Alef (U+0644 U+0627)."""
        # U+FEFB = Lam-Alef ligature (isolated form)
        text = "\u0639\u0642\u062F \uFEFB\u0632\u0645"  # عقد + FEFB + زم
        result = PersianNormalizer.normalize_for_fts(text)
        # The ligature should be decomposed into two standard chars
        assert "\u0644" in result  # Standard Lam
        assert "\u0627" in result  # Standard Alef
        assert "\uFEFB" not in result  # Ligature removed

    def test_nfkc_whole_word_presentation_forms(self) -> None:
        """Whole word 'لازم' with all presentation forms → standard Unicode."""
        # "لازم" using Arabic Presentation Forms-B:
        # ل (U+FEDF Lam initial) + ا (U+FE8D Alef isolated) +
        # ز (U+FEAF Zain isolated) + م (U+FEE1 Meem isolated)
        text = "\uFEDF\uFE8D\uFEAF\uFEE1"
        result = PersianNormalizer.normalize_for_fts(text)
        # Should now be standard "لازم" (U+0644 U+0627 U+0632 U+0645)
        assert result == "\u0644\u0627\u0632\u0645"
        assert "لازم" in result

    def test_nfkc_mixed_presentation_and_standard(self) -> None:
        """Mixed presentation forms and standard chars are all normalized."""
        # "عقد لازم" with presentation forms for "لازم" but standard for "عقد"
        text = "\u0639\u0642\u062F \uFEDF\uFE8D\uFEAF\uFEE1"
        result = PersianNormalizer.normalize_for_fts(text)
        assert "عقد" in result
        assert "لازم" in result
        assert "\uFEDF" not in result
        assert "\uFE8D" not in result
        assert "\uFEAF" not in result
        assert "\uFEE1" not in result

    def test_nfkc_idempotent(self) -> None:
        """NFKC normalization is idempotent — applying twice is safe."""
        text = "\uFEDF\uFE8D\uFEB1\uFEE1"  # Presentation forms
        result1 = PersianNormalizer.normalize_for_fts(text)
        result2 = PersianNormalizer.normalize_for_fts(result1)
        assert result1 == result2

    def test_nfkc_standard_text_unchanged(self) -> None:
        """Standard Persian text is not affected by NFKC normalization."""
        text = "عقد لازم جایز"
        result = PersianNormalizer.normalize_for_fts(text)
        assert result == "عقد لازم جایز"

    def test_nfkc_english_text_unchanged(self) -> None:
        """English/Latin text is not affected by NFKC normalization."""
        text = "Hello World! Test 123."
        result = PersianNormalizer.normalize_for_fts(text)
        assert result == text

    def test_nfkc_persian_digits_still_normalized(self) -> None:
        """Persian digits are still normalized after NFKC step."""
        # Persian digits (U+06F0–U+06F9) should still become English digits
        text = "\uFEDF\uFE8D\uFEAF\uFEE1 \u06F2\u06F2"  # Presentation "لازم" + Persian ۲۲
        result = PersianNormalizer.normalize_for_fts(text)
        assert "22" in result
        assert "لازم" in result


# ---------------------------------------------------------------------------
# Documented limitation: Hazm does NOT fix RTL reversal
# ---------------------------------------------------------------------------


class TestRtlReversalLimitation:
    def test_hazm_does_not_fix_reversal(self, normalizer: PersianNormalizer) -> None:
        """Verify that Hazm does NOT fix structural RTL reversal.

        This is a documented limitation. If PyMuPDF outputs «قانون» as
        «نوناق» (reversed), Hazm has no way to know the correct order.
        RTL reversal must be prevented at the extraction layer.
        """
        # Simulate garbled RTL reversal
        reversed_text = "نوناق"  # قانون reversed
        result = normalizer.normalize(reversed_text)
        # Hazm should NOT magically fix the reversal
        assert result == "نوناق"  # Still reversed
