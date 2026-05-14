"""
Persian text normalization service for document processing.

Provides the :class:`PersianNormalizer` class that applies a multi-stage
normalization pipeline to Persian (Farsi) text extracted from PDFs.

**⚠️ Limitation:** This normalizer handles character-level issues (Tatweel,
Arabic/Persian variants, half-spaces, control characters) but **CANNOT fix
structural RTL reversal** caused by PyMuPDF (e.g., «قانون» → «نوناق»).
RTL reversal must be prevented at the extraction layer using PyMuPDF RTL flags
or fallback extractors (pdfplumber, Tesseract OCR).

Processing order (CRITICAL):
1. :meth:`_nfkc_normalize` — NFKC normalization (converts Arabic Presentation
   Forms to standard Unicode codepoints)
2. :meth:`fix_ligature_reversals` — post-NFKC correction for common ``لا``
   reversal errors
3. :meth:`strip_tatweel` — remove Kashida characters
4. :meth:`clean_control_chars` — remove PDF artifacts
5. :meth:`normalize_arabic_chars` — character normalization
6. :meth:`fix_half_spaces` — ZWNJ fixes via hazm + custom regex
7. :meth:`repair_broken_dates` — fix dates split across lines
   (applied after Hazm to avoid Hazm adding spaces around ``/``)
8. Final cleanup pass
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from hazm import Normalizer as HazmNormalizer

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

# Arabic → Persian character translation table for FTS normalization.
# PDFs often encode Persian text using Arabic glyph variants, which causes
# search failures (e.g., Ctrl+F can't find "جایز" if the PDF uses Arabic Yeh).
# These mappings ensure consistent Persian character representation.
# Arabic Yeh (U+064A) → Persian Yeh (U+06CC)
# Arabic Kaf (U+0643) → Persian Kaf (U+06A9)
_ARABIC_TO_PERSIAN: dict[int, int] = {
    0x064A: 0x06CC,  # Arabic Yeh (ي) → Persian Yeh (ی)
    0x0643: 0x06A9,  # Arabic Kaf (ك) → Persian Kaf (ک)
}

# Common Persian words that should contain a ZWNJ (half-space)
# These are words where hazm might miss the half-space fix
_PERSIAN_HALF_SPACE_WORDS: list[tuple[str, str]] = [
    # می‌ + verb prefix
    (r"\bمی\s+(\w)", rf"می{_ZWNJ_CHAR}\1"),
    (r"\bنمی\s+(\w)", rf"نمی{_ZWNJ_CHAR}\1"),
    # خواهم / خواهی / خواهد etc.
    (r"\bخواه\s+(\w)", rf"خواه{_ZWNJ_CHAR}\1"),
    # verb + اش / ات / ام suffixes
    (r"(\w)\s+اش\b", rf"\1{_ZWNJ_CHAR}اش"),
    (r"(\w)\s+ات\b", rf"\1{_ZWNJ_CHAR}ات"),
    (r"(\w)\s+ام\b", rf"\1{_ZWNJ_CHAR}ام"),
    # Common compound prepositions
    (r"\bبه\s+(\w)", rf"به{_ZWNJ_CHAR}\1"),
]

# ---------------------------------------------------------------------------
# Ligature-reversal fixes (tactical post-NFKC correction)
# ---------------------------------------------------------------------------
# After NFKC normalization, some common Persian words still appear garbled
# due to ligature-reversal errors introduced during PDF extraction. This
# dictionary maps known garbled patterns to their correct forms.
#
# **Limitation:** This is a tactical fix — it handles known patterns but
# does not scale to unseen errors. See Phase 8 for the strategic approach.
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
# Persian dates often split across lines during PDF extraction (e.g.,
# "1376/\n01/15"). This regex handles:
# - 4-digit Persian dates: 1376/\n01/15
# - 2-digit dates: 76/\n01/15
# - Dash-separated: 1376-\n01-15
# - Persian digits: ۱۳۷۶/\n۰۱/۱۵
# - Gregorian dates: 2025/\n05/14
#
# The regex allows optional whitespace around separators because Hazm
# normalization may add spaces around punctuation before this stage runs
# in the pipeline. Each date component (day, month) is captured separately
# to allow whitespace between them.
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

    Usage::

        normalizer = PersianNormalizer()
        clean_text = normalizer.normalize(dirty_text)
    """

    def __init__(self) -> None:
        # Hazm normalizer for Persian character normalization.
        # We configure it to:
        # - Normalize Arabic characters to Persian equivalents
        # - Fix half-spaces (ZWNJ) using Hazm's built-in rules
        # - Not affect English/non-Persian text
        self._hazm = HazmNormalizer(
            persian_numbers=False,  # Keep English/Arabic numbers as-is
            remove_diacritics=True,  # Remove Arabic diacritics (tashkeel)
            remove_specials_chars=False,  # Keep special chars like &, @
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(self, text: Optional[str]) -> str:
        """Full normalization pipeline for Persian legal text.

        Applies all normalization stages in the correct order:

        0. :meth:`_nfkc_normalize` — NFKC normalization (converts Arabic
           Presentation Forms to standard Unicode codepoints)
        1. :meth:`fix_ligature_reversals` — post-NFKC correction for common
           ``لا`` reversal errors
        2. :meth:`strip_tatweel` — remove Kashida characters
        3. :meth:`clean_control_chars` — remove PDF artifacts
        4. :meth:`normalize_arabic_chars` — character normalization via Hazm
        5. :meth:`fix_half_spaces` — ZWNJ fixes via Hazm + custom regex
        6. :meth:`repair_broken_dates` — fix dates split across lines
           (applied after Hazm to avoid Hazm adding spaces around ``/``)
        7. Final cleanup — collapse excessive whitespace

        Args:
            text: The raw extracted text, possibly containing Persian
                characters with Tatweel, broken ZWNJ, or control chars.

        Returns:
            The normalized text, or an empty string if ``text`` is ``None``
            or empty.
        """
        if not text:
            return ""

        original_length = len(text)

        # Stage 0: NFKC normalization — converts Arabic Presentation Forms-B
        # (positional glyph variants from PDFs, U+FE70–U+FEFF) to standard
        # Unicode codepoints.  MUST be before Tatweel stripping because NFKC
        # may affect how certain characters are represented.
        text = self._nfkc_normalize(text)

        # Stage 1: Fix ligature reversals — post-NFKC correction for common
        # ``لا`` reversal errors (e.g., "وکالی" → "وکلای").
        # Applied here because NFKC may decompose ligatures, and we want to
        # catch reversal patterns before further processing.
        text = self.fix_ligature_reversals(text)

        # Stage 2: Strip Tatweel/Kashida (MUST be before regex matching)
        text = self.strip_tatweel(text)

        # Stage 3: Remove PDF-induced control characters
        text = self.clean_control_chars(text)

        # Stage 4: Normalize Arabic/Persian character variants via Hazm
        text = self.normalize_arabic_chars(text)

        # Stage 5: Fix half-space (ZWNJ) issues
        text = self.fix_half_spaces(text)

        # Stage 6: Repair broken dates — fix dates split across lines
        # (e.g., "1376/\n01/15" → "1376/01/15").
        # Applied after Hazm because Hazm adds spaces around ``/`` which
        # would break the repaired date.
        text = self.repair_broken_dates(text)

        # Stage 7: Final cleanup — collapse excessive whitespace
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

        PDF extraction of Persian text often produces garbled words where
        the ``لا`` (Lam-Alef) ligature is reversed or mis-encoded. This
        method applies a dictionary of known garbled → correct mappings.

        This is a **tactical fix** — it handles known patterns but does not
        scale to unseen errors.

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

        Persian dates like ``1376/01/15`` often break across lines in PDF
        extraction, becoming ``1376/\n01/15``. This method uses a
        comprehensive regex to detect and fix such breaks.

        Handles:
        - 4-digit Persian dates: ``1376/\n01/15``
        - 2-digit dates: ``76/\n01/15``
        - Dash-separated: ``1376-\n01-15``
        - Persian digits: ``۱۳۷۶/\n۰۱/۱۵``
        - Gregorian dates: ``2025/\n05/14``

        Args:
            text: Text with potentially broken dates.

        Returns:
            Text with broken dates repaired.
        """
        def _rejoin(match: re.Match) -> str:
            # Groups 1-3: English digits with / (year/month/day)
            if match.group(1) and match.group(2) and match.group(3):
                return f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
            # Groups 4-6: English digits with - (year-month-day)
            if match.group(4) and match.group(5) and match.group(6):
                return f"{match.group(4)}-{match.group(5)}-{match.group(6)}"
            # Groups 7-9: Persian digits with / (year/month/day)
            if match.group(7) and match.group(8) and match.group(9):
                return f"{match.group(7)}/{match.group(8)}/{match.group(9)}"
            # Groups 10-12: Persian digits with - (year-month-day)
            if match.group(10) and match.group(11) and match.group(12):
                return f"{match.group(10)}-{match.group(11)}-{match.group(12)}"
            return match.group(0)  # fallback (shouldn't happen)

        return _DATE_BROKEN_RE.sub(_rejoin, text)

    def strip_tatweel(self, text: str) -> str:
        """Remove all Tatweel/Kashida characters (U+0640) from text.

        Tatweel (also called Kashida) is a decorative elongation character
        used in Arabic script for justification. It appears frequently in
        Persian legal PDFs (e.g., ``مـــاده`` instead of ``ماده``) and breaks
        regex patterns.

        This method **MUST** be called before any regex matching or other
        normalization steps.

        Args:
            text: Input text possibly containing Tatweel characters.

        Returns:
            Text with all Tatweel characters removed.
        """
        return _TATWEEL_RE.sub("", text)

    def normalize_arabic_chars(self, text: str) -> str:
        """Normalize Arabic/Persian character variants using Hazm.

        Converts Arabic character forms to their Persian equivalents:

        - Arabic ``ي`` (U+064A) → Persian ``ی`` (U+06CC)
        - Arabic ``ك`` (U+0643) → Persian ``ک`` (U+06A9)
        - Arabic ``ة`` (U+0629) → ``ه`` (U+0647)
        - Arabic ``إ`` / ``أ`` (U+0625 / U+0623) → ``ا`` (U+0627)
        - Arabic ``ؤ`` (U+0648) → ``و`` (U+0648)
        - Arabic ``ئ`` (U+0626) → ``ی`` (U+06CC)
        - Various Arabic diacritics are removed

        Args:
            text: Input text with potential Arabic character variants.

        Returns:
            Text with characters normalized to Persian forms.
        """
        return self._hazm.normalize(text)

    def fix_half_spaces(self, text: str) -> str:
        """Fix half-space (ZWNJ) issues common in Persian text.

        Persian uses the zero-width non-joiner (ZWNJ, U+200C) to create
        half-spaces between compound words (e.g., ``می‌شود``, ``نمی‌تواند``).
        PDF extraction often replaces ZWNJ with regular spaces or removes it
        entirely.

        This method:
        1. Applies Hazm's built-in half-space normalization
        2. Applies custom regex patterns for common Persian compound words
           that Hazm might miss

        Args:
            text: Input text with potentially broken half-spaces.

        Returns:
            Text with corrected half-spaces (ZWNJ).
        """
        # Step 1: Let Hazm handle its built-in half-space rules
        text = self._hazm.normalize(text)

        # Step 2: Custom regex patterns for common Persian compounds
        for pattern, replacement in _PERSIAN_HALF_SPACE_WORDS:
            text = re.sub(pattern, replacement, text)

        return text

    def clean_control_chars(self, text: str) -> str:
        """Remove PDF-induced control characters and stray glyphs.

        PDF extraction can introduce various control characters, invisible
        glyphs, and Unicode formatting characters that interfere with text
        processing. This method removes:

        - C0 control characters (U+0000–U+001F) except tab, newline, carriage return
        - C1 control characters (U+0080–U+009F)
        - Unicode formatting characters (U+200B–U+200F, U+2028–U+202F, U+2060–U+2064)
        - Soft hyphens (U+00AD)
        - Object replacement characters (U+FFFC)
        - Byte order marks (U+FEFF)

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

        PostgreSQL's ``tsvector``/``tsquery`` with the ``simple`` configuration
        tokenizes on whitespace and punctuation, then lowercases. Persian/Arabic
        digits and ZWNJ characters are **not** handled by the ``simple`` config,
        which means:

        - ``"ماده ۲۲"`` (with Persian digit) will NOT match ``"ماده 22"``
          (with English digit) in FTS.
        - ``"می‌شود"`` (with ZWNJ half-space) may tokenize as one token
          ``"می‌شود"`` instead of two tokens ``"می"`` and ``"شود"``.

        This method applies five transformations:

        0. **NFKC normalization** (first): Converts Arabic Presentation Forms-B
           (U+FE70–U+FEFF) — positional glyph variants commonly produced by PDF
           extractors — to their standard Unicode codepoints. Also decomposes
           ligatures like ``لا`` (U+FEFB) into ``لا`` (U+0644 U+0627). This is
           critical because PDFs often store Persian text using presentation
           forms that look identical on screen but have different byte sequences,
           causing both Ctrl+F and FTS to fail.

        1. **Arabic → Persian character normalization**: Converts Arabic glyph
           variants commonly found in PDFs to their Persian equivalents:
           - Arabic Yeh (``ي`` U+064A) → Persian Yeh (``ی`` U+06CC)
           - Arabic Kaf (``ك`` U+0643) → Persian Kaf (``ک`` U+06A9)
           This ensures that text like ``"جائز"`` (with Arabic Yeh) is stored
           as ``"جایز"`` (with Persian Yeh), making it searchable via Ctrl+F
           and FTS.

        2. **Digit normalization**: Converts Arabic-Indic digits (U+0660–U+0669)
           and Persian/Extended Arabic-Indic digits (U+06F0–U+06F9) to their
           English equivalents (0–9). This ensures that a search for ``"ماده 22"``
           matches chunks containing ``"ماده ۲۲"``.

        3. **ZWNJ → space**: Replaces zero-width non-joiners (U+200C) with
           regular ASCII spaces. This ensures that compound Persian words like
           ``"می‌شود"`` are tokenized as two separate tokens (``"می"`` and
           ``"شود"``) by PostgreSQL's FTS parser.

        .. caution::

           This method is **only** for indexing/querying. Do **not** use it
           for display or general text normalization — it destroys the original
           Persian digit representation and half-space formatting.

        Args:
            text: The text to normalize for FTS (typically chunk content or a
                search query).

        Returns:
            Text with Arabic Presentation Forms normalized to standard Unicode,
            Arabic chars converted to Persian, Persian/Arabic digits converted
            to English digits, and ZWNJ characters replaced with spaces.
        """
        if not text:
            return ""

        # Step 0: NFKC normalization — converts Arabic Presentation Forms-B
        # (positional glyph variants used by PDFs, U+FE70–U+FEFF) to standard
        # Unicode codepoints. Also decomposes ligatures like "لا" (U+FEFB)
        # into "لا" (U+0644 U+0627).
        #
        # Why NFKC and not NFC or NFKD?
        # - NFC (Canonical Composition) does NOT handle presentation forms.
        # - NFKD (Compatibility Decomposition) decomposes them but leaves
        #   multi-codepoint sequences, which can cause issues.
        # - NFKC (Compatibility Composition) decomposes then recomposes,
        #   giving standard single-codepoint forms.
        text = unicodedata.normalize("NFKC", text)

        # Step 1: Convert Arabic glyph variants to Persian equivalents
        # (Yeh U+064A → ی U+06CC, Kaf U+0643 → ک U+06A9)
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
        """Apply NFKC normalization to convert Arabic Presentation Forms.

        PDF extractors (PyMuPDF, pdfplumber) often preserve **positional
        glyph variants** of Arabic/Persian letters (Arabic Presentation
        Forms-B, U+FE70–U+FEFF) instead of converting them to standard
        Unicode codepoints.  These presentation forms look identical on
        screen but have different byte sequences, causing both Ctrl+F and
        PostgreSQL FTS to fail.

        NFKC normalization (Compatibility Composition) handles this by:

        1. **Decomposing** compatibility characters into standard equivalents
        2. **Recomposing** them into the standard NFC form

        For example:
        - ``ل`` (U+FEDF — Lam initial form) → ``ل`` (U+0644 — standard Lam)
        - ``لا`` (U+FEFB — Lam-Alef ligature) → ``لا`` (U+0644 U+0627)
        - ``ا`` (U+FE8D — Alef isolated form) → ``ا`` (U+0627 — standard Alef)

        Args:
            text: Input text potentially containing Arabic Presentation Forms.

        Returns:
            Text with all characters normalized to standard Unicode codepoints.
        """
        return unicodedata.normalize("NFKC", text)

    @staticmethod
    def _final_cleanup(text: str) -> str:
        """Collapse excessive whitespace and trim.

        Performs final cleanup:
        - Collapse 3+ consecutive newlines into 2
        - Collapse 3+ consecutive spaces into 1
        - Strip leading/trailing whitespace

        Args:
            text: Partially normalized text.

        Returns:
            Cleaned text with normalized whitespace.
        """
        # Collapse excessive newlines (keep max 2 for paragraph separation)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Collapse excessive spaces
        text = re.sub(r" {3,}", " ", text)
        # Strip leading/trailing whitespace
        text = text.strip()
        return text
