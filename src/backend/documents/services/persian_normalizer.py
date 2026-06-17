"""
Persian text normalization service for document processing.

Provides the :class:`PersianNormalizer` class that applies a multi-stage
normalization pipeline to Persian (Farsi) text extracted from PDFs.

**⚠️ Limitation:** This normalizer handles character-level issues (Tatweel,
Arabic/Persian variants, half-spaces, control characters) but **CANNOT fix
structural RTL reversal** caused by PyMuPDF (e.g., «قانون» → «نوناق»).
RTL reversal must be prevented at the extraction layer using PyMuPDF RTL flags
or the VLM fallback pipeline.

Processing order (CRITICAL):
1. :meth:`_nfkc_normalize` — NFKC normalization (converts Arabic Presentation
   Forms to standard Unicode codepoints)
2. :meth:`fix_ligature_reversals` — post-NFKC correction for common ``لا``
   reversal errors
3. :meth:`strip_tatweel` — remove Kashida characters
4. :meth:`clean_control_chars` — remove PDF artifacts
5. :meth:`normalize_arabic_chars` — character normalization (custom, no hazm)
6. :meth:`fix_half_spaces` — ZWNJ fixes via custom regex
7. :meth:`repair_broken_dates` — fix dates split across lines
8. Final cleanup pass

.. note::

   The ``hazm`` library dependency has been removed. All normalization is
   now implemented with pure Python (``unicodedata`` + ``re`` + character
   translation tables).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tatweel / Kashida character (U+0640) — decorative elongation in Arabic script
_TATWEEL_CHAR: str = "\u0640"
_TATWEEL_RE: re.Pattern = re.compile(_TATWEEL_CHAR)

# Zero-width non-joiner (U+200C)
_ZWNJ_CHAR: str = "\u200c"

# Persian/Arabic digit → English digit translation table for FTS normalization.
# Arabic-Indic digits (U+0660–U+0669): ٠١٢٣٤٥٦٧٨٩
# Persian/Extended Arabic-Indic digits (U+06F0–U+06F9): ۰۱۲۳۴۵۶۷۸۹
# Both map to their English equivalents (0–9).
_PERSIAN_DIGITS: dict[int, int] = {
    # Arabic-Indic digits (U+0660–U+0669)
    0x0660: ord("0"),
    0x0661: ord("1"),
    0x0662: ord("2"),
    0x0663: ord("3"),
    0x0664: ord("4"),
    0x0665: ord("5"),
    0x0666: ord("6"),
    0x0667: ord("7"),
    0x0668: ord("8"),
    0x0669: ord("9"),
    # Persian/Extended Arabic-Indic digits (U+06F0–U+06F9)
    0x06F0: ord("0"),
    0x06F1: ord("1"),
    0x06F2: ord("2"),
    0x06F3: ord("3"),
    0x06F4: ord("4"),
    0x06F5: ord("5"),
    0x06F6: ord("6"),
    0x06F7: ord("7"),
    0x06F8: ord("8"),
    0x06F9: ord("9"),
}

# Arabic → Persian character translation table.
# PDFs often encode Persian text using Arabic glyph variants, which causes
# search failures (e.g., Ctrl+F can't find "جایز" if the PDF uses Arabic Yeh).
# These mappings ensure consistent Persian character representation.
#
# This replaces what hazm's Normalizer did for character normalization.
# Extended to cover all common Arabic→Persian substitutions.
_ARABIC_TO_PERSIAN: dict[int, int] = {
    0x064A: 0x06CC,  # Arabic Yeh (ي) → Persian Yeh (ی)
    0x0643: 0x06A9,  # Arabic Kaf (ك) → Persian Kaf (ک)
    0x0626: 0x06CC,  # Arabic Yeh with hamza above (ئ) → Persian Yeh (ی)
    0x0624: 0x0648,  # Arabic Waw with hamza above (ؤ) → Waw (و)
    0x0622: 0x0627,  # Arabic Alef with madd above (آ) → Alef (ا)
    0x0625: 0x0627,  # Arabic Alef with hamza below (إ) → Alef (ا)
    0x0623: 0x0627,  # Arabic Alef with hamza above (أ) → Alef (ا)
    0x06C0: 0x0647,  # Arabic Heh with yeh above (ۀ) → Heh (ه)
    0x06C2: 0x0647,  # Arabic Heh goal with hamza above (ۂ) → Heh (ه)
    0x0629: 0x0647,  # Arabic Teh marbuta (ة) → Heh (ه)
}

# Arabic diacritics (tashkeel) to remove — replaces hazm's remove_diacritics
_ARABIC_DIACRITICS: str = (
    "\u0610\u0611\u0612\u0613\u0614\u0615\u0616\u0617\u0618\u0619\u061A"
    "\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0653\u0654\u0655"
    "\u0656\u0657\u0658\u0659\u065A\u065B\u065C\u065D\u065E\u065F"
    "\u0670"
    "\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DC\u06DD\u06DE\u06DF"
    "\u06E0\u06E1\u06E2\u06E3\u06E4\u06E5\u06E6\u06E7\u06E8\u06E9"
    "\u06EA\u06EB\u06EC\u06ED"
)
_ARABIC_DIACRITICS_RE: re.Pattern = re.compile(f"[{_ARABIC_DIACRITICS}]")

# Common Persian words that should contain a ZWNJ (half-space)
# These patterns replace what hazm's built-in half-space rules did.
_PERSIAN_HALF_SPACE_WORDS: list[tuple[str, str]] = [
    # می + verb prefix (می‌روم, می‌کنم, etc.)
    (r"\bمی\s+(\w)", rf"می{_ZWNJ_CHAR}\1"),
    (r"\bنمی\s+(\w)", rf"نمی{_ZWNJ_CHAR}\1"),
    # خواهم / خواهی / خواهد etc. (خواهم‌رفت, etc.)
    (r"\bخواه\s+(\w)", rf"خواه{_ZWNJ_CHAR}\1"),
    # verb + اش / ات / ام suffixes (گفتم, کتابش, etc.)
    (r"(\w)\s+اش\b", rf"\1{_ZWNJ_CHAR}اش"),
    (r"(\w)\s+ات\b", rf"\1{_ZWNJ_CHAR}ات"),
    (r"(\w)\s+ام\b", rf"\1{_ZWNJ_CHAR}ام"),
    # Common compound prepositions (به‌عنوان, به‌جز, etc.)
    (r"\bبه\s+(\w)", rf"به{_ZWNJ_CHAR}\1"),
    # Common compounds with هم (هم‌کاری, هم‌فکری, etc.)
    (r"\bهم\s+(\w)", rf"هم{_ZWNJ_CHAR}\1"),
    # Common compounds with غیر (غیر‌قانونی, غیر‌مستقیم, etc.)
    (r"\bغیر\s+(\w)", rf"غیر{_ZWNJ_CHAR}\1"),
    # Common compounds with میان (میان‌بند, میان‌مدت, etc.)
    (r"\bمیان\s+(\w)", rf"میان{_ZWNJ_CHAR}\1"),
    # Common compounds with پیش (پیش‌بینی, پیش‌فرض, etc.)
    (r"\bپیش\s+(\w)", rf"پیش{_ZWNJ_CHAR}\1"),
    # Common compounds with پس (پس‌انداز, پس‌فرست, etc.)
    (r"\bپس\s+(\w)", rf"پس{_ZWNJ_CHAR}\1"),
    # Common compounds with علی (علی‌الخصوص, علی‌رغم, etc.)
    (r"\bعلی\s+(\w)", rf"علی{_ZWNJ_CHAR}\1"),
    # Common compounds with بین (بین‌المللی, etc.)
    (r"\bبین\s+(\w)", rf"بین{_ZWNJ_CHAR}\1"),
]

# ---------------------------------------------------------------------------
# Ligature-reversal fixes (tactical post-NFKC correction)
# ---------------------------------------------------------------------------
_LIGATURE_FIXES: dict[str, str] = {
    "وکالی": "وکلای",
    "دالیل": "دلایل",
    "سالم": "سلام",
    "عالوه": "علاوه",
    "مثالم": "مثال",
    "اعالم": "اعلام",
    "اقالم": "اقلام",
    "قبال": "قبل",
    "حاالت": "حالت",
    "معامالت": "معاملات",
    "مطالبات": "مطالبات",
    "اصالح": "اصلاح",
    "تفاصیل": "تفصیل",
    "مقاالت": "مقالات",
    "رساالت": "رسالات",
    "مسیول": "مسئول",
    "هیأت": "هیئت",
    "اطلاعت": "اطلاعات",
    "علالخصوص": "علی‌الخصوص",
}

# ---------------------------------------------------------------------------
# Broken date repair regex
# ---------------------------------------------------------------------------
_DATE_BROKEN_RE: re.Pattern = re.compile(
    r'(\d{2,4})\s*/\s*\n\s*(\d{1,2})\s*/\s*(\d{1,2})'            # English digits with /
    r'|(\d{2,4})\s*-\s*\n\s*(\d{1,2})\s*-\s*(\d{1,2})'            # English digits with -
    r'|([۰-۹]{2,4})\s*/\s*\n\s*([۰-۹]{1,2})\s*/\s*([۰-۹]{1,2})'   # Persian digits with /
    r'|([۰-۹]{2,4})\s*-\s*\n\s*([۰-۹]{1,2})\s*-\s*([۰-۹]{1,2})'   # Persian digits with -
)

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PersianNormalizer:
    """Multi-stage normalizer for Persian (Farsi) text extracted from PDFs.

    The normalizer applies a fixed pipeline of transformations designed to
    clean garbled Persian text that commonly results from PDF extraction.

    .. note::

       This class no longer depends on ``hazm``. All character normalization,
       diacritic removal, and half-space fixing is implemented with pure
       Python.

    Usage::

        normalizer = PersianNormalizer()
        clean_text = normalizer.normalize(dirty_text)
    """

    def __init__(self) -> None:
        # No hazm dependency needed — all normalization is implemented
        # via character translation tables, regex, and unicodedata.
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(self, text: Optional[str]) -> str:
        """Full normalization pipeline for Persian legal text.

        Applies all normalization stages in the correct order:

        0. :meth:`_nfkc_normalize` — NFKC normalization
        1. :meth:`fix_ligature_reversals` — post-NFKC correction
        2. :meth:`strip_tatweel` — remove Kashida characters
        3. :meth:`clean_control_chars` — remove PDF artifacts
        4. :meth:`normalize_arabic_chars` — character normalization
        5. :meth:`fix_half_spaces` — ZWNJ fixes via custom regex
        6. :meth:`repair_broken_dates` — fix dates split across lines
        7. Final cleanup — collapse excessive whitespace

        Args:
            text: The raw extracted text.

        Returns:
            The normalized text, or an empty string if ``text`` is ``None``
            or empty.
        """
        if not text:
            return ""

        original_length = len(text)

        # Stage 0: NFKC normalization — converts Arabic Presentation Forms-B
        text = self._nfkc_normalize(text)

        # Stage 1: Fix ligature reversals
        text = self.fix_ligature_reversals(text)

        # Stage 2: Strip Tatweel/Kashida
        text = self.strip_tatweel(text)

        # Stage 3: Remove PDF-induced control characters
        text = self.clean_control_chars(text)

        # Stage 4: Normalize Arabic/Persian character variants
        text = self.normalize_arabic_chars(text)

        # Stage 5: Fix half-space (ZWNJ) issues
        text = self.fix_half_spaces(text)

        # Stage 6: Repair broken dates
        text = self.repair_broken_dates(text)

        # Stage 7: Final cleanup
        text = self._final_cleanup(text)

        logger.debug(
            "PersianNormalizer: %d chars → %d chars (%.1f%% reduction)",
            original_length,
            len(text),
            (1 - len(text) / max(original_length, 1)) * 100,
        )

        return text

    def fix_ligature_reversals(self, text: str) -> str:
        """Fix common ligature-reversal errors after NFKC normalization.

        Args:
            text: NFKC-normalized text with potential ligature reversals.

        Returns:
            Text with known ligature-reversal patterns corrected.
        """
        for garbled, correct in _LIGATURE_FIXES.items():
            text = text.replace(garbled, correct)
        return text

    def repair_broken_dates(self, text: str) -> str:
        """Repair dates that were split across lines during PDF extraction.

        Args:
            text: Text with potentially broken dates.

        Returns:
            Text with broken dates repaired.
        """
        def _rejoin(match: re.Match) -> str:
            # Groups 1-3: English digits with /
            if match.group(1) and match.group(2) and match.group(3):
                return f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
            # Groups 4-6: English digits with -
            if match.group(4) and match.group(5) and match.group(6):
                return f"{match.group(4)}-{match.group(5)}-{match.group(6)}"
            # Groups 7-9: Persian digits with /
            if match.group(7) and match.group(8) and match.group(9):
                return f"{match.group(7)}/{match.group(8)}/{match.group(9)}"
            # Groups 10-12: Persian digits with -
            if match.group(10) and match.group(11) and match.group(12):
                return f"{match.group(10)}-{match.group(11)}-{match.group(12)}"
            return match.group(0)

        return _DATE_BROKEN_RE.sub(_rejoin, text)

    def strip_tatweel(self, text: str) -> str:
        """Remove all Tatweel/Kashida characters (U+0640) from text.

        Args:
            text: Input text possibly containing Tatweel characters.

        Returns:
            Text with all Tatweel characters removed.
        """
        return _TATWEEL_RE.sub("", text)

    def normalize_arabic_chars(self, text: str) -> str:
        """Normalize Arabic/Persian character variants (no hazm dependency).

        Converts Arabic character forms to their Persian equivalents:

        - Arabic ``ي`` (U+064A) → Persian ``ی`` (U+06CC)
        - Arabic ``ك`` (U+0643) → Persian ``ک`` (U+06A9)
        - Arabic ``ة`` (U+0629) / ``ۀ`` (U+06C0) → ``ه`` (U+0647)
        - Arabic ``إ`` / ``أ`` (U+0625 / U+0623) → ``ا`` (U+0627)
        - Arabic ``ؤ`` (U+0624) → ``و`` (U+0648)
        - Arabic ``ئ`` (U+0626) → ``ی`` (U+06CC)
        - Arabic diacritics (tashkeel) are removed

        This replaces the previous hazm-based implementation.

        Args:
            text: Input text with potential Arabic character variants.

        Returns:
            Text with characters normalized to Persian forms.
        """
        # Step 1: Translate Arabic characters to Persian equivalents
        text = text.translate(_ARABIC_TO_PERSIAN)

        # Step 2: Remove Arabic diacritics (tashkeel)
        # This replaces hazm's remove_diacritics=True option
        text = _ARABIC_DIACRITICS_RE.sub("", text)

        return text

    def fix_half_spaces(self, text: str) -> str:
        """Fix half-space (ZWNJ) issues common in Persian text.

        Persian uses the zero-width non-joiner (ZWNJ, U+200C) to create
        half-spaces between compound words. PDF extraction often replaces
        ZWNJ with regular spaces or removes it entirely.

        This method applies custom regex patterns for common Persian
        compound words — replaces the previous hazm-based approach.

        Args:
            text: Input text with potentially broken half-spaces.

        Returns:
            Text with corrected half-spaces (ZWNJ).
        """
        for pattern, replacement in _PERSIAN_HALF_SPACE_WORDS:
            text = re.sub(pattern, replacement, text)
        return text

    def clean_control_chars(self, text: str) -> str:
        """Remove PDF-induced control characters and stray glyphs.

        Args:
            text: Input text potentially containing control characters.

        Returns:
            Text with control characters removed.
        """
        # Remove C0 control chars except \t (0x09), \n (0x0A), \r (0x0D)
        text = re.sub(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F]", "", text)

        # Remove C1 control characters
        text = re.sub(r"[\u0080-\u009F]", "", text)

        # Remove Unicode formatting characters
        text = re.sub(
            r"[\u200B-\u200F\u2028-\u202F\u2060-\u2064\uFEFF\uFFFC\u00AD]",
            "",
            text,
        )

        return text

    # ------------------------------------------------------------------
    # FTS (Full-Text Search) normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_for_fts(text: str) -> str:
        """Normalize Persian text specifically for PostgreSQL Full-Text Search.

        Applies:
        0. NFKC normalization (converts Arabic Presentation Forms-B)
        1. Arabic → Persian character normalization
        2. Digit normalization (Persian/Arabic → English)
        3. ZWNJ → space

        Args:
            text: The text to normalize for FTS.

        Returns:
            Text normalized for FTS indexing.
        """
        if not text:
            return ""

        # Step 0: NFKC normalization
        text = unicodedata.normalize("NFKC", text)

        # Step 1: Convert Arabic glyph variants to Persian equivalents
        text = text.translate(_ARABIC_TO_PERSIAN)

        # Step 2: Convert Persian/Arabic digits to English digits
        text = text.translate(_PERSIAN_DIGITS)

        # Step 3: Replace ZWNJ with space for proper FTS tokenization
        text = text.replace(_ZWNJ_CHAR, " ")

        return text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _nfkc_normalize(text: str) -> str:
        """Apply NFKC normalization to convert Arabic Presentation Forms."""
        return unicodedata.normalize("NFKC", text)

    @staticmethod
    def _final_cleanup(text: str) -> str:
        """Collapse excessive whitespace and trim."""
        # Collapse excessive newlines (keep max 2 for paragraph separation)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Collapse excessive spaces
        text = re.sub(r" {3,}", " ", text)
        # Strip leading/trailing whitespace
        text = text.strip()
        return text
