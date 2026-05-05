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
1. :meth:`strip_tatweel` — MUST be first, before any regex
2. :meth:`clean_control_chars` — remove PDF artifacts
3. :meth:`normalize_arabic_chars` — character normalization
4. :meth:`fix_half_spaces` — ZWNJ fixes via hazm + custom regex
5. Final cleanup pass
"""

from __future__ import annotations

import logging
import re
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

        1. :meth:`strip_tatweel` — remove Kashida characters
        2. :meth:`clean_control_chars` — remove PDF artifacts
        3. :meth:`normalize_arabic_chars` — character normalization via Hazm
        4. :meth:`fix_half_spaces` — ZWNJ fixes via Hazm + custom regex
        5. Final cleanup — collapse excessive whitespace

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

        # Stage 1: Strip Tatweel/Kashida (MUST be first)
        text = self.strip_tatweel(text)

        # Stage 2: Remove PDF-induced control characters
        text = self.clean_control_chars(text)

        # Stage 3: Normalize Arabic/Persian character variants via Hazm
        text = self.normalize_arabic_chars(text)

        # Stage 4: Fix half-space (ZWNJ) issues
        text = self.fix_half_spaces(text)

        # Stage 5: Final cleanup — collapse excessive whitespace
        text = self._final_cleanup(text)

        logger.debug(
            "PersianNormalizer: %d chars → %d chars (%.1f%% reduction)",
            original_length,
            len(text),
            (1 - len(text) / max(original_length, 1)) * 100,
        )

        return text

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
    # Internal helpers
    # ------------------------------------------------------------------

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
