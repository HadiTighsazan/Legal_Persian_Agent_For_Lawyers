"""
Legal structure detector for Persian legal documents.

Provides the :class:`LegalStructureDetector` class that identifies structural
elements in Persian legal texts — articles (مواد), notes (تبصره), clauses
(بند), and chapters (فصل) — using flexible regex patterns that handle:

- Tatweel/Kashida characters (stripped before matching)
- Mixed Persian/Arabic/English numerals
- Zero-width non-joiners (ZWNJ) and irregular spacing
- Various formatting conventions in Iranian judiciary PDFs

Processing pipeline (CRITICAL):
1. :meth:`_strip_tatweel` — remove Kashida first
2. :meth:`_normalize_legal_whitespace` — normalize spacing/ZWNJ
3. Run regex patterns on cleaned text
4. Map detected positions back to original text for accurate chunk boundaries
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Regex patterns
# ---------------------------------------------------------------------------

# Persian numerals: ۰۱۲۳۴۵۶۷۸۹
_PERSIAN_NUM = r"[۰۱۲۳۴۵۶۷۸۹]"
# Arabic numerals: ٠١٢٣٤٥٦٧٨٩
_ARABIC_NUM = r"[٠١٢٣٤٥٦٧٨٩]"
# English numerals: 0123456789
_ENGLISH_NUM = r"[0-9]"
# Any numeral system
_ANY_NUM = f"(?:{_PERSIAN_NUM}|{_ARABIC_NUM}|{_ENGLISH_NUM})+"

# Persian alphabetic clause markers (الف, ب, پ, ت, etc.)
_PERSIAN_ALPHA = r"[آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی]"

# ماده (Article) — handles: ماده ۱, ماده1, ماده‌۱, ماده١
# After Tatweel stripping, this matches ماده followed by optional space and any numeral
_ARTICLE_PATTERN = re.compile(rf"ماده\s*{_ANY_NUM}", re.UNICODE)

# تبصره (Note) — handles: تبصره, تبصره ۱, تبصره1
# تبصره can appear without a number (attached to the preceding article)
_NOTE_PATTERN = re.compile(rf"تبصره\s*{_ANY_NUM}?", re.UNICODE)

# بند (Clause) — handles: ۱-, ۱ -, 1-, الف-, ب-
# Clauses can be numeric or alphabetic, followed by a dash or ZWNJ
_CLAUSE_PATTERN = re.compile(
    rf"(?:{_ANY_NUM}|{_PERSIAN_ALPHA})\s*[\-\u200c]",
    re.UNICODE,
)

# فصل (Chapter) — handles: فصل ۱, فصل اول, فصل1
# Chapters can use numerals or Persian ordinal words
_PERSIAN_ORDINALS = r"[اولدومسومچهارمپنجمششمهفتمهشتمنهمدهم]"
_CHAPTER_PATTERN = re.compile(
    rf"فصل\s*(?:{_ANY_NUM}|{_PERSIAN_ORDINALS})",
    re.UNICODE,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LegalSegment:
    """Represents a single structural segment detected in a legal document.

    Attributes:
        segment_type: One of ``'chapter'``, ``'article'``, ``'note'``,
            ``'clause'``, or ``'text'`` (plain text with no structure).
        segment_number: The parsed number/identifier of the segment
            (e.g., ``'۱'``, ``'2'``, ``'الف'``), or ``None`` for plain text.
        content: The text content of this segment.
        metadata: Arbitrary key/value pairs (e.g., ``parent_article`` for
            notes/clauses).
        start_pos: Character position (0-based) in the **original** text
            where this segment begins.
        end_pos: Character position (0-based) in the **original** text
            where this segment ends.
    """

    segment_type: str
    segment_number: Optional[str]
    content: str
    metadata: dict = field(default_factory=dict)
    start_pos: int = 0
    end_pos: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LegalStructureDetector:
    """Detects structural elements in Persian legal documents.

    The detector uses flexible regex patterns to identify:

    - **فصل (Chapter)** — top-level groupings (e.g., ``فصل ۱``, ``فصل اول``)
    - **ماده (Article)** — numbered sections (e.g., ``ماده ۱``, ``ماده ۲``)
    - **تبصره (Note)** — sub-articles attached to a ماده
    - **بند (Clause)** — sub-points within a ماده or تبصره

    Usage::

        detector = LegalStructureDetector()
        segments = detector.detect_structure(extracted_text)
        for segment in segments:
            print(f"{segment.segment_type}: {segment.segment_number}")
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_structure(self, text: str) -> list[LegalSegment]:
        """Detect legal document structure in the given text.

        The detection pipeline:

        1. Strip Tatweel/Kashida characters
        2. Normalize legal whitespace (ZWNJ → space, collapse spaces)
        3. Find all structural markers (فصل, ماده, تبصره, بند)
        4. Build segments by splitting text at marker boundaries
        5. Attach metadata (parent article for notes/clauses)

        Args:
            text: The extracted (and ideally normalized) text from a
                Persian legal document.

        Returns:
            A list of :class:`LegalSegment` instances ordered by their
            position in the text. If no legal structure is detected,
            returns a single ``'text'`` segment with the full content.
        """
        if not text or not text.strip():
            return []

        # Stage 1: Strip Tatweel for clean regex matching
        cleaned = self._strip_tatweel(text)

        # Stage 2: Normalize whitespace for consistent matching
        cleaned = self._normalize_legal_whitespace(cleaned)

        # Stage 3: Find all structural markers with their positions
        markers = self._find_all_markers(cleaned)

        # Stage 4: If no structure detected, return as plain text
        if not markers:
            return [
                LegalSegment(
                    segment_type="text",
                    segment_number=None,
                    content=text.strip(),
                    start_pos=0,
                    end_pos=len(text),
                )
            ]

        # Stage 5: Build segments by splitting at marker boundaries
        segments = self._build_segments(text, cleaned, markers)

        # Stage 6: Attach metadata (parent article for notes/clauses)
        segments = self._attach_metadata(segments)

        return segments

    def has_legal_structure(self, text: str) -> bool:
        """Quick check if the text contains Persian legal structure markers.

        This is a lightweight check that does not build the full segment
        tree. Useful for deciding whether to use legal chunking or fall
        back to standard chunking.

        Args:
            text: The extracted text to check.

        Returns:
            ``True`` if at least one ماده or فصل marker is found.
        """
        if not text:
            return False
        cleaned = self._strip_tatweel(text)
        cleaned = self._normalize_legal_whitespace(cleaned)
        return bool(_ARTICLE_PATTERN.search(cleaned)) or bool(
            _CHAPTER_PATTERN.search(cleaned)
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_tatweel(text: str) -> str:
        """Remove all Tatweel/Kashida characters (U+0640) from text.

        This MUST be called before any regex matching to ensure patterns
        like ``ماده`` match even when the PDF uses ``مـــاده``.
        """
        return text.replace("\u0640", "")

    @staticmethod
    def _normalize_legal_whitespace(text: str) -> str:
        """Normalize whitespace for consistent regex matching.

        - Replace ZWNJ + optional spaces with a single space
        - Collapse multiple spaces into one
        - Strip leading/trailing whitespace

        This ensures patterns like ``ماده ۱`` match even when the PDF
        uses ``ماده‌۱`` (with ZWNJ instead of space).
        """
        # Replace ZWNJ (with optional surrounding spaces) with a single space
        text = re.sub(r"\s*\u200c\s*", " ", text)
        # Collapse multiple spaces
        text = re.sub(r" {2,}", " ", text)
        return text.strip()

    def _find_all_markers(
        self, cleaned: str
    ) -> list[tuple[int, str, Optional[str]]]:
        """Find all structural markers in the cleaned text.

        Returns a list of ``(position, marker_type, marker_number)`` tuples
        sorted by position. Marker types are ``'chapter'``, ``'article'``,
        ``'note'``, or ``'clause'``.

        Args:
            cleaned: Tatweel-stripped, whitespace-normalized text.

        Returns:
            Sorted list of marker tuples.
        """
        markers: list[tuple[int, str, Optional[str]]] = []

        # Find all فصل (Chapter) markers
        for match in _CHAPTER_PATTERN.finditer(cleaned):
            number = self._extract_number(match.group(), "فصل")
            markers.append((match.start(), "chapter", number))

        # Find all ماده (Article) markers
        for match in _ARTICLE_PATTERN.finditer(cleaned):
            number = self._extract_number(match.group(), "ماده")
            markers.append((match.start(), "article", number))

        # Find all تبصره (Note) markers
        for match in _NOTE_PATTERN.finditer(cleaned):
            number = self._extract_number(match.group(), "تبصره")
            markers.append((match.start(), "note", number))

        # Find all بند (Clause) markers
        for match in _CLAUSE_PATTERN.finditer(cleaned):
            number = self._extract_clause_number(match.group())
            markers.append((match.start(), "clause", number))

        # Sort by position
        markers.sort(key=lambda m: m[0])

        return markers

    @staticmethod
    def _extract_number(matched_text: str, prefix: str) -> Optional[str]:
        """Extract the numeric portion after a structural keyword.

        Handles mixed Persian/Arabic/English numerals.

        Args:
            matched_text: The full regex match (e.g., ``ماده ۱``).
            prefix: The keyword prefix (e.g., ``ماده``).

        Returns:
            The extracted number string, or ``None`` if no number found.
        """
        # Remove the prefix and strip whitespace
        rest = matched_text[len(prefix) :].strip()
        if not rest:
            return None
        # Return the numeric portion (any numeral system)
        num_match = re.search(rf"{_ANY_NUM}", rest)
        return num_match.group() if num_match else None

    @staticmethod
    def _extract_clause_number(matched_text: str) -> Optional[str]:
        """Extract the clause number/letter from a بند marker.

        Args:
            matched_text: The full regex match (e.g., ``۱-``, ``الف-``).

        Returns:
            The extracted number or letter, or ``None``.
        """
        # Remove trailing dash/ZWNJ and whitespace
        rest = matched_text.rstrip("-\u200c ").strip()
        return rest if rest else None

    def _build_segments(
        self,
        original_text: str,
        cleaned_text: str,
        markers: list[tuple[int, str, Optional[str]]],
    ) -> list[LegalSegment]:
        """Build :class:`LegalSegment` instances from detected markers.

        Splits the text at marker boundaries. Each segment's content is
        taken from the **original** text (not the cleaned version) to
        preserve original character positions.

        Args:
            original_text: The original (uncleaned) text.
            cleaned_text: The Tatweel-stripped, whitespace-normalized text.
            markers: Sorted list of ``(position, type, number)`` tuples.

        Returns:
            List of :class:`LegalSegment` instances.
        """
        segments: list[LegalSegment] = []
        prev_end = 0

        for i, (pos, seg_type, seg_number) in enumerate(markers):
            # If there's text before this marker, add it as a text segment
            if pos > prev_end:
                text_before = original_text[prev_end:pos].strip()
                if text_before:
                    segments.append(
                        LegalSegment(
                            segment_type="text",
                            segment_number=None,
                            content=text_before,
                            start_pos=prev_end,
                            end_pos=pos,
                        )
                    )

            # Determine the end of this segment (next marker or end of text)
            if i + 1 < len(markers):
                next_pos = markers[i + 1][0]
            else:
                next_pos = len(original_text)

            # Extract content from original text
            content = original_text[pos:next_pos].strip()

            segments.append(
                LegalSegment(
                    segment_type=seg_type,
                    segment_number=seg_number,
                    content=content,
                    start_pos=pos,
                    end_pos=next_pos,
                )
            )

            prev_end = next_pos

        # If there's trailing text after the last marker
        if prev_end < len(original_text):
            trailing = original_text[prev_end:].strip()
            if trailing:
                segments.append(
                    LegalSegment(
                        segment_type="text",
                        segment_number=None,
                        content=trailing,
                        start_pos=prev_end,
                        end_pos=len(original_text),
                    )
                )

        return segments

    @staticmethod
    def _attach_metadata(
        segments: list[LegalSegment],
    ) -> list[LegalSegment]:
        """Attach parent article metadata to notes and clauses.

        For each note (تبصره) and clause (بند), sets the ``parent_article``
        metadata key to the number of the most recently seen article.

        Args:
            segments: List of segments (modified in-place).

        Returns:
            The same list with metadata attached.
        """
        current_article: Optional[str] = None
        current_chapter: Optional[str] = None

        for segment in segments:
            if segment.segment_type == "chapter":
                current_chapter = segment.segment_number
                segment.metadata["chapter"] = current_chapter

            elif segment.segment_type == "article":
                current_article = segment.segment_number
                segment.metadata["article_number"] = current_article
                if current_chapter:
                    segment.metadata["chapter"] = current_chapter

            elif segment.segment_type == "note":
                segment.metadata["parent_article"] = current_article
                if current_chapter:
                    segment.metadata["chapter"] = current_chapter

            elif segment.segment_type == "clause":
                segment.metadata["parent_article"] = current_article
                if current_chapter:
                    segment.metadata["chapter"] = current_chapter

        return segments
