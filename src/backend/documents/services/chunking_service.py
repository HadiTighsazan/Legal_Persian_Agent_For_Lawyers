"""
Chunking service for document text processing.

Provides the :class:`ChunkingService` class that splits extracted document text
into semantically meaningful chunks. Supports two strategies:

1. **Legal structural chunking** — For Persian legal documents, detects
   articles (مواد), notes (تبصره), clauses (بند), and chapters (فصل), then
   chunks by structural boundaries with clause-boundary-aware overlap.
2. **Sentence-boundary chunking** — Fallback for non-legal documents, using
   sentence-ending characters with character-based overlap.

Both strategies support page tracking via ``[PAGE N]`` markers and token
counting via ``tiktoken``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Pattern

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
# Includes Persian/Arabic punctuation:
# - ؟ (U+061F) — Persian/Arabic question mark
# - ، (U+060C) — Persian/Arabic comma
# - ؛ (U+061B) — Persian/Arabic semicolon
_SENTENCE_ENDINGS: set[str] = {".", "!", "?", "؟", "،", "؛"}

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
        legal_type: The type of legal segment (``'article'``, ``'note'``,
            ``'clause'``, ``'text'``), or ``None`` for non-legal chunks.
        legal_number: The parsed number/identifier of the legal segment
            (e.g., ``'۱'``, ``'2'``), or ``None``.
        parent_article: For notes/clauses, the parent article number.
    """

    content: str
    page_start: int
    page_end: int
    char_count: int
    token_count: int
    metadata: dict = field(default_factory=dict)
    legal_type: Optional[str] = None
    legal_number: Optional[str] = None
    parent_article: Optional[str] = None


@dataclass
class ClauseBoundary:
    """Represents a single clause (بند) within an article.

    Attributes:
        clause_number: The clause identifier (e.g., ``'۱'``, ``'الف'``).
        start_pos: Character position in the article content.
        end_pos: Character position (exclusive) in the article content.
        content: The text content of this clause.
    """

    clause_number: str
    start_pos: int
    end_pos: int
    content: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ChunkingService:
    """Splits extracted document text into overlapping chunks.

    Supports two chunking strategies:

    1. **Legal structural chunking** — Activated when the text contains Persian
       legal structure markers (ماده, فصل). Chunks are created at article
       (ماده) boundaries, with long articles split at clause (بند) boundaries
       using clause-boundary-aware overlap.

    2. **Sentence-boundary chunking** — Fallback for non-legal documents.
       Splits at sentence endings (``.``, ``!``, ``?``) with character-based
       overlap.

    The service works with text that contains injected page markers
    (e.g. ``[PAGE 1]``, ``[PAGE 2]``) left behind by the extraction layer.
    These markers are used to track which pages a chunk spans and are
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
        legal_chunking_enabled: bool = True,
        legal_max_chunk_size: int = 2000,
        legal_overlap_clauses: int = 1,
    ) -> List[ChunkResult]:
        """Split ``text`` into a list of overlapping chunks.

        The algorithm automatically detects whether the text contains Persian
        legal structure. If it does, and ``legal_chunking_enabled`` is ``True``,
        legal structural chunking is used. Otherwise, sentence-boundary
        chunking is used as a fallback.

        Args:
            text: The full extracted document text, possibly containing
                ``[PAGE N]`` markers.
            chunk_size: The target size (in characters) for each chunk
                (sentence-boundary mode only).
            overlap: The number of characters of overlap between consecutive
                chunks (sentence-boundary mode only).
            legal_chunking_enabled: Whether to attempt legal structural
                chunking for Persian legal documents.
            legal_max_chunk_size: Maximum characters per legal chunk
                (for splitting long articles).
            legal_overlap_clauses: Number of clauses to overlap when
                splitting long articles at clause boundaries.

        Returns:
            A list of :class:`ChunkResult` instances, one per chunk.
        """
        if not text:
            return []

        # ------------------------------------------------------------------
        # Phase 1: Strip page markers and build position mapping
        # ------------------------------------------------------------------
        clean_to_original, clean_text, page_map = self._prepare_text(text)
        clean_len = len(clean_text)

        if clean_len == 0:
            return []

        # ------------------------------------------------------------------
        # Phase 2: Decide chunking strategy
        # ------------------------------------------------------------------
        if legal_chunking_enabled and self._has_legal_structure(clean_text):
            return self._chunk_legal(
                text=text,
                clean_text=clean_text,
                clean_to_original=clean_to_original,
                page_map=page_map,
                max_chunk_size=legal_max_chunk_size,
                overlap_clauses=legal_overlap_clauses,
            )
        else:
            return self._chunk_sentence(
                text=text,
                clean_text=clean_text,
                clean_to_original=clean_to_original,
                page_map=page_map,
                chunk_size=chunk_size,
                overlap=overlap,
            )

    # ------------------------------------------------------------------
    # Legal structural chunking
    # ------------------------------------------------------------------

    def _chunk_legal(
        self,
        text: str,
        clean_text: str,
        clean_to_original: list[int],
        page_map: list[tuple[int, int]],
        max_chunk_size: int,
        overlap_clauses: int,
    ) -> List[ChunkResult]:
        """Chunk text using Persian legal structure boundaries.

        Strategy:
        1. Detect legal structure (articles, notes, clauses, chapters)
        2. Group segments by article boundaries
        3. For each article:
           a. If it fits within max_chunk_size, keep as single chunk
           b. If too long, split at clause boundaries with clause-aware overlap
        4. Attach legal metadata (article number, chapter, parent article)

        Args:
            text: Original text with page markers.
            clean_text: Text with page markers stripped.
            clean_to_original: Position mapping from clean to original text.
            page_map: Page marker positions in original text.
            max_chunk_size: Maximum characters per legal chunk.
            overlap_clauses: Number of clauses to overlap when splitting.

        Returns:
            List of :class:`ChunkResult` instances.
        """
        from documents.services.legal_structure_detector import (
            LegalStructureDetector,
        )

        detector = LegalStructureDetector()
        segments = detector.detect_structure(clean_text)

        if not segments:
            return []

        chunks: List[ChunkResult] = []

        # Group segments into articles (including their notes and clauses)
        article_groups = self._group_article_segments(segments)

        for article_segments in article_groups:
            # Combine all segments in this group into one content block
            article_content = "\n".join(
                s.content for s in article_segments if s.content
            )

            if not article_content.strip():
                continue

            # Get metadata from the article segment
            article_seg = next(
                (s for s in article_segments if s.segment_type == "article"),
                None,
            )
            article_number = (
                article_seg.segment_number if article_seg else None
            )
            chapter = article_seg.metadata.get("chapter") if article_seg else None

            # Check if this article fits within max_chunk_size
            if len(article_content) <= max_chunk_size:
                # Single chunk for this article
                chunk = self._make_chunk(
                    content=article_content,
                    text=text,
                    clean_to_original=clean_to_original,
                    page_map=page_map,
                    legal_type="article",
                    legal_number=article_number,
                    parent_article=None,
                    metadata={"chapter": chapter} if chapter else {},
                )
                if chunk:
                    chunks.append(chunk)
            else:
                # Split at clause boundaries with clause-aware overlap
                clause_chunks = self._split_long_article(
                    article_content=article_content,
                    article_number=article_number,
                    chapter=chapter,
                    max_chunk_size=max_chunk_size,
                    overlap_clauses=overlap_clauses,
                    text=text,
                    clean_to_original=clean_to_original,
                    page_map=page_map,
                )
                chunks.extend(clause_chunks)

        return chunks

    @staticmethod
    def _group_article_segments(
        segments: list,
    ) -> list[list]:
        """Group legal segments into article-based groups.

        Each group starts with an article (ماده) and includes all subsequent
        notes (تبصره) and clauses (بند) until the next article or chapter.

        Args:
            segments: List of :class:`LegalSegment` instances.

        Returns:
            List of segment groups, each group being a list of segments.
        """
        groups: list[list] = []
        current_group: list = []
        pending_chapter: list = []  # Chapter segments waiting for an article

        for segment in segments:
            if segment.segment_type == "chapter":
                # Don't create a separate group for chapters.
                # Hold the chapter segment to merge into the next article group.
                if current_group:
                    # If we have a current group (e.g., text before chapter),
                    # finalize it first
                    groups.append(current_group)
                    current_group = []
                pending_chapter = [segment]
            elif segment.segment_type == "article":
                # Start a new article group, prepending any pending chapter
                if current_group:
                    groups.append(current_group)
                current_group = list(pending_chapter) + [segment]
                pending_chapter = []
            else:
                # Note, clause, or text — attach to current group
                if current_group:
                    current_group.append(segment)
                elif pending_chapter:
                    # Attach to pending chapter (text between chapter and article)
                    pending_chapter.append(segment)
                else:
                    # Orphan segment (text before first article)
                    current_group = [segment]

        # Flush any remaining pending chapter as its own group
        if pending_chapter:
            groups.append(pending_chapter)

        # Don't forget the last group
        if current_group:
            groups.append(current_group)

        return groups

    def _split_long_article(
        self,
        article_content: str,
        article_number: Optional[str],
        chapter: Optional[str],
        max_chunk_size: int,
        overlap_clauses: int,
        text: str,
        clean_to_original: list[int],
        page_map: list[tuple[int, int]],
    ) -> List[ChunkResult]:
        """Split a long article at clause boundaries with clause-aware overlap.

        Instead of character-based overlap (which can break mid-clause),
        we overlap entire clauses. The next chunk starts ``overlap_clauses``
        clauses BEFORE the current chunk's end.

        Example with ``overlap_clauses=1``::

            Chunk 1: [بند ۱][بند ۲][بند ۳]
            Chunk 2: [بند ۳][بند ۴][بند ۵]
                          ^^^^^^^
                          بند ۳ is the overlap — fully preserved, not truncated

        Args:
            article_content: The full text content of the article.
            article_number: The article number (e.g., ``'۱'``).
            chapter: The chapter name/number, if any.
            max_chunk_size: Maximum characters per chunk.
            overlap_clauses: Number of clauses to overlap.
            text: Original text with page markers.
            clean_to_original: Position mapping.
            page_map: Page marker positions.

        Returns:
            List of :class:`ChunkResult` instances.
        """
        # Parse clauses within the article content
        clauses = self._parse_clauses(article_content)

        # If no clauses found, fall back to character-based split
        if not clauses:
            return self._split_by_chars(
                content=article_content,
                legal_type="article",
                legal_number=article_number,
                parent_article=None,
                metadata={"chapter": chapter} if chapter else {},
                max_chunk_size=max_chunk_size,
                text=text,
                clean_to_original=clean_to_original,
                page_map=page_map,
            )

        chunks: List[ChunkResult] = []
        i = 0

        while i < len(clauses):
            chunk_clauses: list[ClauseBoundary] = []
            current_size = 0

            # Build chunk forward
            while i < len(clauses):
                clause = clauses[i]
                clause_len = len(clause.content)

                # If adding this clause would exceed max_chunk_size and we
                # already have content, stop (don't create empty chunks)
                if current_size + clause_len > max_chunk_size and chunk_clauses:
                    break

                chunk_clauses.append(clause)
                current_size += clause_len
                i += 1

            # Build chunk content from clauses
            chunk_content = "\n".join(c.content for c in chunk_clauses)

            chunk = self._make_chunk(
                content=chunk_content,
                text=text,
                clean_to_original=clean_to_original,
                page_map=page_map,
                legal_type="article",
                legal_number=article_number,
                parent_article=None,
                metadata={"chapter": chapter} if chapter else {},
            )
            if chunk:
                chunks.append(chunk)

            # Apply clause-aware overlap: rewind by overlap_clauses clauses
            # so the next chunk starts with the last N clauses of the current chunk
            if i < len(clauses) and overlap_clauses > 0:
                i = max(0, i - overlap_clauses)

        return chunks

    @staticmethod
    def _parse_clauses(content: str) -> list[ClauseBoundary]:
        """Parse clause (بند) boundaries within article content.

        Uses the same flexible regex patterns as :class:`LegalStructureDetector`
        to identify clause markers (numeric: ``۱-``, alphabetic: ``الف-``).

        Args:
            content: The article text content.

        Returns:
            List of :class:`ClauseBoundary` instances, or empty list if
            no clauses found.
        """
        from documents.services.legal_structure_detector import (
            _CLAUSE_PATTERN,
        )

        clauses: list[ClauseBoundary] = []
        matches = list(_CLAUSE_PATTERN.finditer(content))

        if not matches:
            return clauses

        for i, match in enumerate(matches):
            clause_text = match.group().rstrip("-\u200c ").strip()
            start = match.start()

            # End is the start of the next clause, or end of content
            if i + 1 < len(matches):
                end = matches[i + 1].start()
            else:
                end = len(content)

            clause_content = content[start:end].strip()
            if clause_content:
                clauses.append(
                    ClauseBoundary(
                        clause_number=clause_text,
                        start_pos=start,
                        end_pos=end,
                        content=clause_content,
                    )
                )

        return clauses

    def _split_by_chars(
        self,
        content: str,
        legal_type: Optional[str],
        legal_number: Optional[str],
        parent_article: Optional[str],
        metadata: dict,
        max_chunk_size: int,
        text: str,
        clean_to_original: list[int],
        page_map: list[tuple[int, int]],
    ) -> List[ChunkResult]:
        """Fallback: split content by character size (no clause boundaries).

        Used when a long article has no detectable clause structure.

        Args:
            content: The text content to split.
            legal_type: Legal segment type.
            legal_number: Legal segment number.
            parent_article: Parent article number.
            metadata: Additional metadata.
            max_chunk_size: Maximum characters per chunk.
            text: Original text with page markers.
            clean_to_original: Position mapping.
            page_map: Page marker positions.

        Returns:
            List of :class:`ChunkResult` instances.
        """
        chunks: List[ChunkResult] = []
        start = 0
        content_len = len(content)

        while start < content_len:
            end = min(start + max_chunk_size, content_len)
            chunk_content = content[start:end].strip()

            if chunk_content:
                chunk = self._make_chunk(
                    content=chunk_content,
                    text=text,
                    clean_to_original=clean_to_original,
                    page_map=page_map,
                    legal_type=legal_type,
                    legal_number=legal_number,
                    parent_article=parent_article,
                    metadata=metadata,
                )
                if chunk:
                    chunks.append(chunk)

            start = end

        return chunks

    # ------------------------------------------------------------------
    # Sentence-boundary chunking (fallback)
    # ------------------------------------------------------------------

    def _chunk_sentence(
        self,
        text: str,
        clean_text: str,
        clean_to_original: list[int],
        page_map: list[tuple[int, int]],
        chunk_size: int,
        overlap: int,
    ) -> List[ChunkResult]:
        """Chunk text using sentence-boundary detection.

        This is the original chunking algorithm, preserved as a fallback
        for non-legal documents.

        Args:
            text: Original text with page markers.
            clean_text: Text with page markers stripped.
            clean_to_original: Position mapping.
            page_map: Page marker positions.
            chunk_size: Target chunk size in characters.
            overlap: Character overlap between chunks.

        Returns:
            List of :class:`ChunkResult` instances.
        """
        clean_len = len(clean_text)
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

            chunk = self._make_chunk(
                content=chunk_content,
                text=text,
                clean_to_original=clean_to_original,
                page_map=page_map,
            )
            if chunk:
                chunks.append(chunk)

            # --- Advance the cursor with overlap ---
            if split_at >= clean_len:
                break

            next_cursor: int = split_at - overlap

            # Guard: the cursor must always advance past the current split
            # point when the overlap would cause it to stall or regress.
            if next_cursor <= cursor:
                next_cursor = split_at

            cursor = next_cursor

        return chunks

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _make_chunk(
        self,
        content: str,
        text: str,
        clean_to_original: list[int],
        page_map: list[tuple[int, int]],
        legal_type: Optional[str] = None,
        legal_number: Optional[str] = None,
        parent_article: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[ChunkResult]:
        """Create a :class:`ChunkResult` with page range and token count.

        Args:
            content: The cleaned chunk content.
            text: The original text (with page markers).
            clean_to_original: Position mapping.
            page_map: Page marker positions.
            legal_type: Optional legal segment type.
            legal_number: Optional legal segment number.
            parent_article: Optional parent article number.
            metadata: Optional additional metadata.

        Returns:
            A :class:`ChunkResult` instance, or ``None`` if content is empty.
        """
        if not content or not content.strip():
            return None

        # Find the position of this content in the clean text
        # We need to locate it in the original text for page resolution.
        # Since we don't have the exact clean-text position here, we use
        # a heuristic: find the content in the original text.
        orig_start = text.find(content)
        if orig_start == -1:
            # Fallback: use position 0
            orig_start = 0
        orig_end = orig_start + len(content)

        page_start, page_end = self._resolve_page_range(
            orig_start, orig_end, page_map
        )

        char_count = len(content)
        token_count = len(self._encoding.encode(content))

        chunk_metadata = dict(metadata or {})
        if legal_type:
            chunk_metadata["legal_type"] = legal_type
        if legal_number:
            chunk_metadata["legal_number"] = legal_number
        if parent_article:
            chunk_metadata["parent_article"] = parent_article

        return ChunkResult(
            content=content,
            page_start=page_start,
            page_end=page_end,
            char_count=char_count,
            token_count=token_count,
            metadata=chunk_metadata,
            legal_type=legal_type,
            legal_number=legal_number,
            parent_article=parent_article,
        )

    def _prepare_text(
        self, text: str
    ) -> tuple[list[int], str, list[tuple[int, int]]]:
        """Strip page markers and build position mapping.

        Returns:
            A tuple of ``(clean_to_original, clean_text, page_map)``.
        """
        clean_to_original: list[int] = []
        orig_pos: int = 0
        text_len: int = len(text)

        while orig_pos < text_len:
            ch: str = text[orig_pos]
            if ch == "[" and text[orig_pos:].startswith("[PAGE"):
                end_bracket: int = text.find("]", orig_pos)
                if end_bracket != -1:
                    orig_pos = end_bracket + 1
                    continue
            clean_to_original.append(orig_pos)
            orig_pos += 1

        clean_text: str = "".join(text[pos] for pos in clean_to_original)
        page_map: list[tuple[int, int]] = self._build_page_map(text)

        return clean_to_original, clean_text, page_map

    @staticmethod
    def _has_legal_structure(text: str) -> bool:
        """Quick check if text contains Persian legal structure markers.

        Uses :class:`LegalStructureDetector.has_legal_structure` for the
        actual detection logic.

        Args:
            text: The cleaned text to check.

        Returns:
            ``True`` if legal structure markers are found.
        """
        from documents.services.legal_structure_detector import (
            LegalStructureDetector,
        )

        detector = LegalStructureDetector()
        return detector.has_legal_structure(text)

    # ------------------------------------------------------------------
    # Original helpers (preserved from the original implementation)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_page_map(text: str) -> list[tuple[int, int]]:
        """Scan ``text`` for ``[PAGE N]`` markers and return a list of
        ``(position, page_number)`` tuples sorted by position.
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
        """
        def _page_at(pos: int) -> int:
            active_page: int = 1
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
        1. Persian sentence endings (``؟``, ``،``, ``؛``) followed by
           space or newline.
        2. Standard sentence endings (``.``, ``!``, ``?``) followed by
           space or newline.
        3. Double newline (paragraph break).
        4. The last space character.
        5. A hard split at ``window_end`` (no suitable boundary found).
        """
        # --- Priority 1: Persian sentence boundary ---
        for pos in range(window_end - 1, start - 1, -1):
            ch: str = text[pos]
            if ch in ("؟", "،", "؛"):
                if pos + 1 >= window_end or text[pos + 1] in (" ", "\n", "\r", "\t"):
                    return pos + 1

        # --- Priority 2: standard sentence boundary ---
        for pos in range(window_end - 1, start - 1, -1):
            ch: str = text[pos]
            if ch in _SENTENCE_ENDINGS:
                if pos + 1 >= window_end or text[pos + 1] in (" ", "\n", "\r", "\t"):
                    return pos + 1

        # --- Priority 3: double newline (paragraph break) ---
        for pos in range(window_end - 1, start - 1, -1):
            if text[pos] == "\n" and pos > 0 and text[pos - 1] == "\n":
                return pos + 1

        # --- Priority 4: last space ---
        for pos in range(window_end - 1, start - 1, -1):
            if text[pos] == " ":
                return pos + 1

        # --- Priority 5: hard split ---
        return window_end
