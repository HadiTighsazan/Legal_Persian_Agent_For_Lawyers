"""
Safe non-text section filtering for Persian legal document chunking.

Filters out chunks that are detected as structural artifacts (table of contents,
headers, footers, page numbers, etc.) rather than actual legal content.

Architecture
------------
- :class:`BaseDetector` — Abstract base class for non-text content detectors.
- :class:`TableOfContentsDetector` — Detects table-of-contents sections using
  conservative heuristics (high precision, low recall).
- :class:`NonTextChunkFilter` — Orchestrator that runs all registered detectors
  and removes chunks flagged by any detector.

Design Principles
-----------------
1. **Conservative (Safe) Approach** — High precision over recall. Only skip
   chunks we are very confident are non-text. False negatives (keeping a non-text
   chunk) are acceptable; false positives (removing a real content chunk) are not.
2. **Low False Positive Rate** — Detection is strict enough that legitimate
   Persian legal text (e.g., an article containing the word "فهرست" in its body)
   is never accidentally filtered.
3. **Extensible** — New non-text detectors can be added by subclassing
   :class:`BaseDetector` and implementing :meth:`BaseDetector.is_non_text`.
4. **Minimal Performance Impact** — Detection runs once per chunk, not per
   character. Uses simple string operations and regex.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Persian/Arabic digit range for detecting page numbers at line endings
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ENGLISH_DIGITS = "0123456789"
ALL_DIGITS = PERSIAN_DIGITS + ARABIC_DIGITS + ENGLISH_DIGITS

# TOC title patterns (checked in the first N characters of a chunk)
TOC_TITLE_PATTERNS: List[re.Pattern] = [
    re.compile(r"فهرست\s+مطالب"),       # فهرست مطالب
    re.compile(r"فهرست\s+مندرجات"),     # فهرست مندرجات
    re.compile(r"فهرست\s+اجمالی"),      # فهرست اجمالی
    re.compile(r"فهرست\s+تفصیلی"),      # فهرست تفصیلی
    re.compile(r"Table\s+of\s+Contents", re.IGNORECASE),
]

# Pattern for dotted/solid separator lines (e.g., "......" or "…")
DOTTED_LINE_PATTERN: re.Pattern = re.compile(r"[\.…]{3,}")

# Maximum characters to scan for the explicit title check
TITLE_SCAN_CHARS = 300

# Minimum number of structural lines required to trigger detection
MIN_STRUCTURAL_LINES = 3

# Minimum ratio of structural lines to total lines
MIN_STRUCTURAL_RATIO = 0.4


# ---------------------------------------------------------------------------
# Base Detector
# ---------------------------------------------------------------------------


class BaseDetector(ABC):
    """Abstract base class for non-text content detectors.

    Subclasses must implement :meth:`is_non_text`, returning ``True`` when
    the chunk is confidently identified as non-text content that should be
    skipped during chunk persistence.
    """

    @abstractmethod
    def is_non_text(self, chunk_text: str) -> bool:
        """Return ``True`` if *chunk_text* is non-text content (should be skipped).

        Must be conservative — return ``False`` when uncertain.
        """
        ...


# ---------------------------------------------------------------------------
# Table of Contents Detector
# ---------------------------------------------------------------------------


class TableOfContentsDetector(BaseDetector):
    """Detects table-of-contents sections in Persian legal documents.

    Detection Criteria (Conservative)
    ----------------------------------
    1. **Explicit Title Check** (first 300 chars):
       - ``فهرست مطالب``, ``فهرست مندرجات``, ``Table of Contents``, etc.
       - If absent → return ``False`` (not a TOC).

    2. **Structural Line Check**:
       - Lines ending with digits (page numbers).
       - Lines containing dotted patterns (``...`` or ``…``).
       - At least **3 structural lines** required.

    3. **Ratio Check**:
       - Structural lines / total lines > **0.4** (40%).
       - This is the key conservative threshold.

    Why this is safe (low FP)
    -------------------------
    - Requires an explicit title — a random article containing dotted text
      won't match.
    - Requires ≥3 structural lines — a single line with a number won't trigger.
    - Requires >40% ratio — even if title matches, most content must be
      structural.
    - Persian legal articles rarely have >40% of lines ending in digits or
      containing dots.
    """

    def __init__(
        self,
        title_scan_chars: int = TITLE_SCAN_CHARS,
        min_structural_lines: int = MIN_STRUCTURAL_LINES,
        min_structural_ratio: float = MIN_STRUCTURAL_RATIO,
    ) -> None:
        self.title_scan_chars = title_scan_chars
        self.min_structural_lines = min_structural_lines
        self.min_structural_ratio = min_structural_ratio

    def is_non_text(self, chunk_text: str) -> bool:
        """Return ``True`` if *chunk_text* is a table of contents."""
        if not chunk_text or not chunk_text.strip():
            return False

        # Step 1: Explicit title check (first N chars)
        head = chunk_text[: self.title_scan_chars]
        if not self._has_toc_title(head):
            return False

        # Step 2 & 3: Structural line analysis
        lines = chunk_text.splitlines()
        total_lines = len(lines)
        if total_lines == 0:
            return False

        structural_lines = sum(
            1 for line in lines if self._is_structural_line(line)
        )

        if structural_lines < self.min_structural_lines:
            return False

        ratio = structural_lines / total_lines
        return ratio >= self.min_structural_ratio

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_toc_title(text: str) -> bool:
        """Check if *text* contains a known TOC title pattern."""
        for pattern in TOC_TITLE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    @staticmethod
    def _is_structural_line(line: str) -> bool:
        """Return ``True`` if *line* looks like a TOC structural line.

        A structural line is one that:
        - Ends with a digit (page number), OR
        - Contains a dotted/ellipsis separator pattern.
        """
        stripped = line.strip()
        if not stripped:
            return False

        # Check for dotted separator pattern
        if DOTTED_LINE_PATTERN.search(stripped):
            return True

        # Check if line ends with a digit (page number)
        if stripped[-1] in ALL_DIGITS:
            return True

        return False


# ---------------------------------------------------------------------------
# Non-Text Chunk Filter (Orchestrator)
# ---------------------------------------------------------------------------


class NonTextChunkFilter:
    """Filters out non-text chunks from chunking results.

    Uses a chain of :class:`BaseDetector` strategies. A chunk is removed if
    **any** detector marks it as non-text.

    Usage::

        filter_ = NonTextChunkFilter()
        clean_chunks = filter_.filter_chunks(chunk_results)
    """

    def __init__(
        self, detectors: Optional[List[BaseDetector]] = None
    ) -> None:
        self.detectors = detectors or [TableOfContentsDetector()]

    def filter_chunks(
        self, chunks: List["ChunkResult"]
    ) -> List["ChunkResult"]:
        """Remove chunks detected as non-text content.

        Args:
            chunks: List of ``ChunkResult`` objects from
                :class:`~documents.services.chunking_service.ChunkingService`.

        Returns:
            Filtered list with non-text chunks removed.
        """
        return [
            chunk for chunk in chunks if not self._is_non_text(chunk.content)
        ]

    def _is_non_text(self, text: str) -> bool:
        """Return ``True`` if *text* is detected as non-text by any detector."""
        for detector in self.detectors:
            if detector.is_non_text(text):
                return True
        return False
