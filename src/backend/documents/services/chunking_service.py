"""
Chunking service for document text processing.

Provides the ``ChunkingService`` class that splits extracted document text
into semantically meaningful chunks with page tracking, sentence-boundary
detection, overlap support, and token counting via ``tiktoken``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Pattern

# ---------------------------------------------------------------------------
# Tiktoken offline cache configuration
# ---------------------------------------------------------------------------
# Force tiktoken to use our local cache directory to prevent network timeouts.
# This MUST be set BEFORE importing tiktoken.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
cache_dir = os.path.join(BASE_DIR, "tiktoken_cache")
os.environ["TIKTOKEN_CACHE_DIR"] = cache_dir

import tiktoken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex to detect injected page markers like [PAGE 1], [PAGE 42], etc.
_PAGE_MARKER_RE: Pattern[str] = re.compile(r"\[PAGE\s+(\d+)\]")

# Sentence-ending characters that signal a natural break point.
_SENTENCE_ENDINGS: set[str] = {".", "!", "?"}

# The tokeniser used by OpenAI's ``cl100k_base`` encoding (GPT-4, text-embedding-ada-002, etc.).
_ENCODING_NAME: str = "cl100k_base"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ChunkResult:
    """Represents a single text chunk produced by the chunking service.

    Attributes:
        content: The cleaned chunk text (page markers stripped).
        page_start: The first page number that contributed to this chunk.
        page_end: The last page number that contributed to this chunk.
        char_count: The number of characters in the cleaned content.
        token_count: The number of tokens in the cleaned content (via tiktoken).
        metadata: Arbitrary key/value pairs attached to the chunk.
    """

    content: str
    page_start: int
    page_end: int
    char_count: int
    token_count: int
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ChunkingService:
    """Splits extracted document text into overlapping chunks.

    The service is designed to work with text that contains injected page
    markers (e.g. ``[PAGE 1]``, ``[PAGE 2]``) left behind by the extraction
    layer. These markers are used to track which pages a chunk spans and are
    stripped from the final ``content`` so they do not pollute embeddings.
    """

    def __init__(self) -> None:
        # Cache the encoding instance so we don't re-fetch it on every call.
        self._encoding = tiktoken.get_encoding(_ENCODING_NAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_text(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> List[ChunkResult]:
        """Split ``text`` into a list of overlapping chunks.

        The algorithm works as follows:

        1. Strip all ``[PAGE N]`` markers from the text to obtain a clean
           version for chunking, while building a position map that translates
           clean-text positions back to original-text positions (for page
           resolution).
        2. From the current ``cursor`` (in clean-text coordinates), define a
           window of ``chunk_size`` characters.
        3. Within that window, find the best split point (sentence boundary,
           space, or hard split at window end).
        4. Extract the chunk, record page range / token counts.
        5. Advance the cursor to ``split_at - overlap``, with guards to
           ensure forward progress.

        Args:
            text: The full extracted document text, possibly containing
                ``[PAGE N]`` markers.
            chunk_size: The target size (in characters) for each chunk.
            overlap: The number of characters of overlap between consecutive
                chunks.

        Returns:
            A list of :class:`ChunkResult` instances, one per chunk.
        """
        if not text:
            return []

        # ------------------------------------------------------------------
        # Phase 1: Strip page markers and build a clean-text → original-text
        # position mapping so we can resolve page numbers later.
        # ------------------------------------------------------------------
        # clean_to_original[i] = original-text position corresponding to
        # clean-text position i.
        clean_to_original: list[int] = []

        # Walk through the original text, skipping [PAGE N] markers.
        orig_pos: int = 0
        text_len: int = len(text)
        while orig_pos < text_len:
            ch: str = text[orig_pos]
            # Check if this position is the start of a [PAGE N] marker.
            if ch == "[" and text[orig_pos:].startswith("[PAGE"):
                end_bracket: int = text.find("]", orig_pos)
                if end_bracket != -1:
                    # Skip the entire marker — do NOT add to clean text.
                    orig_pos = end_bracket + 1
                    continue
            # Regular character: include in clean text and record mapping.
            clean_to_original.append(orig_pos)
            orig_pos += 1

        # Build the clean text by extracting all mapped characters.
        clean_text: str = "".join(text[pos] for pos in clean_to_original)
        clean_len: int = len(clean_text)

        # Build the page map on the *original* text (positions in original coords).
        page_map: list[tuple[int, int]] = self._build_page_map(text)

        # ------------------------------------------------------------------
        # Phase 2: Chunk the clean text.
        # ------------------------------------------------------------------
        chunks: List[ChunkResult] = []
        cursor: int = 0

        while cursor < clean_len:
            window_end: int = min(cursor + chunk_size, clean_len)

            # Find the best split point in clean-text coordinates.
            split_at: int = self._find_split_point(clean_text, cursor, window_end)

            # Extract the chunk content (already clean — no markers).
            chunk_content: str = clean_text[cursor:split_at].strip()
            if not chunk_content:
                # Avoid adding empty chunks; advance and continue.
                cursor = split_at + 1
                continue

            # Map clean-text positions back to original-text positions for
            # page resolution.
            orig_start: int = clean_to_original[cursor] if cursor < clean_len else len(text)
            orig_end: int = (
                clean_to_original[split_at - 1] + 1
                if split_at > 0 and split_at - 1 < clean_len
                else len(text)
            )

            page_start, page_end = self._resolve_page_range(
                orig_start, orig_end, page_map
            )

            char_count: int = len(chunk_content)
            token_count: int = len(self._encoding.encode(chunk_content))

            chunks.append(
                ChunkResult(
                    content=chunk_content,
                    page_start=page_start,
                    page_end=page_end,
                    char_count=char_count,
                    token_count=token_count,
                )
            )

            # --- Advance the cursor with overlap ---
            if split_at >= clean_len:
                break

            # The next chunk starts ``overlap`` characters *before* the
            # current split point, so that consecutive chunks share content.
            next_cursor: int = split_at - overlap

            # Guard: the cursor must always advance past the current split
            # point when the overlap would cause it to stall or regress.
            # This prevents generating many tiny overlapping chunks when
            # the split point is very close to the cursor (e.g. a short
            # sentence at the start of the text).
            if next_cursor <= cursor:
                next_cursor = split_at

            cursor = next_cursor

        return chunks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_page_map(text: str) -> list[tuple[int, int]]:
        """Scan ``text`` for ``[PAGE N]`` markers and return a list of
        ``(position, page_number)`` tuples sorted by position.

        The map is used by :meth:`_resolve_page_range` to efficiently
        determine which page(s) a character range spans.
        """
        page_map: list[tuple[int, int]] = []
        for match in _PAGE_MARKER_RE.finditer(text):
            page_num: int = int(match.group(1))
            page_map.append((match.start(), page_num))
        return page_map

    @staticmethod
    def _resolve_page_range(
        start: int,
        end: int,
        page_map: list[tuple[int, int]],
    ) -> tuple[int, int]:
        """Return ``(page_start, page_end)`` for the character range
        ``[start, end)`` based on the pre-built ``page_map``.

        Determines the active page at any position by finding the most
        recent page marker that appears *before or at* that position.
        Text appearing before the first marker defaults to page 1.
        """
        def _page_at(pos: int) -> int:
            """Return the page number active at character position ``pos``."""
            active_page: int = 1  # Default: text before any marker is page 1.
            for marker_pos, page_num in page_map:
                if marker_pos <= pos:
                    active_page = page_num
                else:
                    break
            return active_page

        page_start: int = _page_at(start)
        page_end: int = _page_at(end - 1) if end > start else page_start
        return (page_start, page_end)

    @staticmethod
    def _find_split_point(text: str, start: int, window_end: int) -> int:
        """Determine the best character position to split at within the
        window ``[start, window_end)``.

        Priority order:
        1. The last sentence-ending character (``.``, ``!``, ``?``) followed
           by a space or newline.
        2. The last space character.
        3. A hard split at ``window_end`` (no suitable boundary found).
        """
        # --- Priority 1: sentence boundary ---
        # Scan backwards from window_end to find a sentence-ending char
        # that is followed by whitespace or is at the end of the window.
        for pos in range(window_end - 1, start - 1, -1):
            ch: str = text[pos]
            if ch in _SENTENCE_ENDINGS:
                # Check that the next character (if any) is whitespace.
                if pos + 1 >= window_end or text[pos + 1] in (" ", "\n", "\r", "\t"):
                    return pos + 1  # Include the sentence-ending char.

        # --- Priority 2: last space ---
        for pos in range(window_end - 1, start - 1, -1):
            if text[pos] == " ":
                return pos + 1  # Split after the space.

        # --- Priority 3: hard split ---
        return window_end
