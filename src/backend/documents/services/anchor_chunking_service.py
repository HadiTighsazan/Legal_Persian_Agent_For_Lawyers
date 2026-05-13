"""
Anchor-based chunking service for Persian legal text.

Provides the :class:`AnchorChunkingService` class that replaces both the old
:class:`~documents.services.chunking_service.ChunkingService` and
:class:`~documents.services.legal_structure_detector.LegalStructureDetector`
with a unified, page-aware anchor-based chunker.

Key design:

1. **Persian normalization** — Normalize Arabic/Persian variants, remove
   diacritics, unify Yeh/Kaf, collapse whitespace BEFORE regex matching.
2. **Metadata extraction** via regex — Extract case_number, date, plaintiff,
   defendant, branch from document text.
3. **Page-aware segments** — Each chunk tracks which pages it spans via
   ``pages: List[int]``, parsed from ``[PAGE N]`` markers.
4. **Text anchor segmentation** — Split text at anchor boundaries using
   ``re.finditer`` (not ``re.split``), preserving the anchor title.
5. **Token-based overlap splitting** — For segments longer than threshold,
   split by token count (via ``tiktoken``) with overlap, not character count.
6. **Clean metadata separation** — Metadata stored in ``metadata`` dict,
   NOT injected into ``content``, preventing embedding pollution.

Usage::

    from documents.services.anchor_chunking_service import AnchorChunkingService

    chunker = AnchorChunkingService()
    chunks = chunker.chunk_text(
        extracted_text,
        chunk_tokens=400,
        overlap_tokens=50,
    )
    for chunk in chunks:
        print(chunk.content)       # Clean text, no metadata
        print(chunk.pages)         # [1, 2, 3]
        print(chunk.metadata)      # {"case_number": "...", "section": "رأی دادگاه"}
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Pattern

# ---------------------------------------------------------------------------
# Tiktoken offline cache configuration
# ---------------------------------------------------------------------------
# Force tiktoken to use our local cache directory to prevent network timeouts.
# This MUST be set BEFORE importing tiktoken.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
cache_dir = os.path.join(BASE_DIR, "tiktoken_cache")
os.environ["TIKTOKEN_CACHE_DIR"] = cache_dir

import tiktoken

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The tokeniser used by OpenAI's ``cl100k_base`` encoding (GPT-4,
# text-embedding-ada-002, text-embedding-3-small, text-embedding-3-large).
_ENCODING_NAME: str = "cl100k_base"

# Regex to detect injected page markers like [PAGE 1], [PAGE 42], etc.
_PAGE_MARKER_RE: Pattern[str] = re.compile(r"\[PAGE\s+(\d+)\]")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AnchorChunk:
    """A single chunk produced by the anchor chunking service.

    Attributes:
        content: The chunk text content (NO metadata injected).
        pages: List of page numbers this chunk spans.
        char_count: Number of characters.
        token_count: Number of tokens (via tiktoken).
        metadata: Metadata dict (case_number, section, etc.) —
            SEPARATE from content to avoid embedding pollution.
        section_title: The anchor title that preceded this chunk
            (e.g., ``"رأی دادگاه"``, ``"گردشکار"``), or ``None`` for
            the introductory section.
    """

    content: str
    pages: List[int]
    char_count: int
    token_count: int
    metadata: dict = field(default_factory=dict)
    section_title: Optional[str] = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AnchorChunkingService:
    """Chunk Persian legal text using text anchors (لنگرهای متنی).

    This service replaces both :class:`ChunkingService` and
    :class:`LegalStructureDetector`. It uses regex-based text anchors for
    structural segmentation, with token-based overlap splitting for long
    segments.

    The chunking pipeline:

    1. Parse ``[PAGE N]`` markers for page tracking
    2. Normalize Persian text for consistent regex matching
    3. Extract metadata from original text (case_number, date, etc.)
    4. Find anchor positions using ``re.finditer``
    5. Split text at anchor boundaries, preserving page info
    6. For long segments (> chunk_tokens), apply token-based overlap split
    7. Attach page info and metadata to each chunk (metadata SEPARATE from content)
    """

    # Persian normalization patterns
    _DIACRITICS_RE: Pattern[str] = re.compile(r"[\u064B-\u065F\u0670]")

    # Metadata extraction patterns for Persian legal documents
    _METADATA_PATTERNS: Dict[str, Pattern[str]] = {
        "case_number": re.compile(
            r"کلاسه\s*(?:پرونده)?\s*:?\s*(\d{10,16})"
        ),
        "date": re.compile(
            r"تاریخ\s*:?\s*(\d{2,4}[/\-]\d{1,2}[/\-]\d{1,2})"
        ),
        "plaintiff": re.compile(r"خواهان\s*:?\s*([^\n]{2,100})"),
        "defendant": re.compile(r"خوانده\s*:?\s*([^\n]{2,100})"),
        "branch": re.compile(r"شعبه\s*(\d+)"),
    }

    # Text anchors for structural segmentation.
    # These are Persian legal document section markers that indicate
    # meaningful structural boundaries in court rulings, advisory opinions,
    # and legislation.
    _SPLIT_ANCHORS: List[str] = [
        r"رأی دادگاه",
        r"رای دادگاه",
        r"در خصوص دعوی",
        r"گردشکار",
        r"ختم دادرسی",
        r"نظریه مشورتی",
        r"بسمه تعالی",
        r"ماده\s*\d+",  # Keep article detection
        r"فصل\s*\d+",  # Keep chapter detection
    ]

    def __init__(self) -> None:
        # Cache the encoding instance so we don't re-fetch it on every call.
        self._encoding = tiktoken.get_encoding(_ENCODING_NAME)
        # Compile the combined anchor pattern once.
        self._anchor_pattern: Pattern[str] = re.compile(
            r"(" + "|".join(self._SPLIT_ANCHORS) + r")"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_text(
        self,
        text: str,
        chunk_tokens: int = 400,
        overlap_tokens: int = 50,
    ) -> List[AnchorChunk]:
        """Main chunking method using text anchors.

        Pipeline:
        1. Extract metadata AND remove metadata lines from text
        2. Parse page markers from cleaned text
        3. Normalize Persian text for regex matching
        4. Find anchor positions in normalized text
        5. Split text at anchor boundaries
        6. For long segments, apply token-based overlap split
        7. Attach page info and metadata to each chunk

        Args:
            text: Full extracted text with ``[PAGE N]`` markers.
            chunk_tokens: Target tokens per chunk (default 400).
                Embedding model context windows are token-based, so this
                ensures chunks fit within model limits. 400 tokens ≈
                200-250 Persian words.
            overlap_tokens: Token overlap between chunks (default 50).
                Provides context continuity across chunk boundaries.

        Returns:
            List of :class:`AnchorChunk` instances. Returns an empty list
            if ``text`` is empty or contains only whitespace.
        """
        if not text or not text.strip():
            return []

        # Step 1: Extract metadata AND remove metadata lines from text.
        # Metadata removal is critical — without it, metadata values
        # (case_number, date, etc.) appear in BOTH metadata dict AND
        # chunk content, polluting embeddings.
        metadata, cleaned_text = self._extract_metadata_and_clean(text)

        # Step 2: Parse page markers from CLEANED text.
        # Removing metadata lines shifts text positions, so the page_map
        # must be computed from the cleaned text, not the original.
        page_map = self._parse_page_markers(cleaned_text)

        # Step 3: Normalize for matching (keep cleaned text for content)
        normalized = self._normalize_persian(cleaned_text)

        # Step 4: Find anchor positions in normalized text
        matches = list(self._anchor_pattern.finditer(normalized))

        final_chunks: List[AnchorChunk] = []

        if not matches:
            # No anchors found — fall back to token-based overlap split
            # across the entire document.
            for chunk_text in self._token_overlap_split(
                cleaned_text, chunk_tokens, overlap_tokens
            ):
                # Find position in cleaned text for page resolution
                orig_pos = cleaned_text.find(chunk_text)
                if orig_pos == -1:
                    orig_pos = 0
                pages = self._resolve_pages(
                    orig_pos, orig_pos + len(chunk_text), page_map
                )
                final_chunks.append(
                    AnchorChunk(
                        content=chunk_text,
                        pages=pages,
                        char_count=len(chunk_text),
                        token_count=len(
                            self._encoding.encode(chunk_text)
                        ),
                        metadata=dict(metadata),
                        section_title="کل سند",
                    )
                )
            return final_chunks

        # Step 5: Split at anchor boundaries.
        # We work with the cleaned text but use normalized positions
        # to find anchors. Map anchor positions back to cleaned text.

        # Section before first anchor
        if matches[0].start() > 0:
            intro_end = matches[0].start()
            intro = cleaned_text[:intro_end].strip()
            # Skip page markers — they're not real content.
            # If only page markers remain, don't create an intro chunk.
            intro_without_markers = _PAGE_MARKER_RE.sub("", intro).strip()
            if intro_without_markers:
                pages = self._resolve_pages(0, intro_end, page_map)
                for ct in self._token_overlap_split(
                    intro, chunk_tokens, overlap_tokens
                ):
                    final_chunks.append(
                        AnchorChunk(
                            content=ct,
                            pages=pages,
                            char_count=len(ct),
                            token_count=len(
                                self._encoding.encode(ct)
                            ),
                            metadata=dict(metadata),
                            section_title="مقدمه",
                        )
                    )

        # Sections between anchors
        for i, match in enumerate(matches):
            section_title = match.group(0)
            start = match.end()
            end = (
                matches[i + 1].start()
                if i + 1 < len(matches)
                else len(cleaned_text)
            )
            content = cleaned_text[start:end].strip()

            if not content:
                continue

            pages = self._resolve_pages(start, end, page_map)

            # Check if segment exceeds token threshold
            token_count = len(self._encoding.encode(content))

            if token_count > chunk_tokens:
                for ct in self._token_overlap_split(
                    content, chunk_tokens, overlap_tokens
                ):
                    final_chunks.append(
                        AnchorChunk(
                            content=ct,
                            pages=pages,
                            char_count=len(ct),
                            token_count=len(
                                self._encoding.encode(ct)
                            ),
                            metadata=dict(metadata),
                            section_title=section_title,
                        )
                    )
            else:
                final_chunks.append(
                    AnchorChunk(
                        content=content,
                        pages=pages,
                        char_count=len(content),
                        token_count=token_count,
                        metadata=dict(metadata),
                        section_title=section_title,
                    )
                )

        return final_chunks

    # ------------------------------------------------------------------
    # Persian normalization
    # ------------------------------------------------------------------

    def _normalize_persian(self, text: str) -> str:
        """Normalize Persian text for consistent regex matching.

        Critical for legal documents where Arabic/Persian variants
        (ي vs ی, ك vs ک, أ/إ/آ vs ا) cause regex failures.

        Normalization steps:
        1. Remove Arabic diacritics (Fatha, Kasra, Damma, etc.)
        2. Unify Arabic Yeh (ي) → Persian Yeh (ی)
        3. Unify Arabic Kaf (ك) → Persian Kaf (ک)
        4. Unify Alef variants (أ, إ, آ) → plain Alef (ا)
        5. Collapse multiple whitespace into single space

        Args:
            text: Raw Persian text.

        Returns:
            Normalized text suitable for regex matching.
        """
        text = self._DIACRITICS_RE.sub("", text)
        text = text.replace("ي", "ی").replace("ك", "ک")
        text = re.sub(r"[أإآ]", "ا", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # ------------------------------------------------------------------
    # Metadata extraction & removal
    # ------------------------------------------------------------------

    def _extract_metadata(self, text: str) -> dict:
        """Extract metadata from document text using regex patterns.

        Searches the document text for common Persian legal document
        metadata fields. Missing fields are omitted from the result dict.

        Returns:
            Dict with keys like ``case_number``, ``date``, ``plaintiff``,
            ``defendant``, ``branch``. Only present keys are included.
        """
        metadata, _ = self._extract_metadata_and_clean(text)
        return metadata

    def _extract_metadata_and_clean(self, text: str) -> tuple[dict, str]:
        """Extract metadata AND remove metadata lines from text.

        Uses ``str.splitlines`` to check each line independently against
        all metadata patterns. This is simpler and more robust than regex
        composition with ``re.MULTILINE``, avoiding greedy matching issues.

        After extraction, metadata lines are removed from the text so that
        metadata values do NOT appear in chunk content (preventing embedding
        pollution). The ``page_map`` must be recomputed from the returned
        cleaned text since positions have shifted.

        Args:
            text: Raw document text with potential metadata lines.

        Returns:
            Tuple of ``(metadata_dict, cleaned_text_without_metadata_lines)``.
        """
        metadata: dict = {}
        cleaned_lines: list[str] = []

        for line in text.splitlines(keepends=True):
            matched = False
            for key, pattern in self._METADATA_PATTERNS.items():
                match = pattern.search(line)
                if match:
                    metadata[key] = match.group(1).strip()
                    matched = True
                    break  # A line can match at most one metadata pattern
            if not matched:
                cleaned_lines.append(line)

        cleaned = "".join(cleaned_lines).strip()
        # Clean up resulting double newlines
        cleaned = re.sub(r"\n\s*\n", "\n", cleaned)
        return metadata, cleaned

    # ------------------------------------------------------------------
    # Page tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_page_markers(text: str) -> List[tuple]:
        """Parse ``[PAGE N]`` markers and return sorted position list.

        Args:
            text: Text containing ``[PAGE N]`` markers.

        Returns:
            Sorted list of ``(char_position, page_number)`` tuples.
        """
        page_map: List[tuple] = []
        for match in _PAGE_MARKER_RE.finditer(text):
            page_map.append((match.start(), int(match.group(1))))
        return sorted(page_map)

    @staticmethod
    def _resolve_pages(
        start: int, end: int, page_map: List[tuple]
    ) -> List[int]:
        """Determine which pages a text range spans.

        Always includes the ``active_page`` (the page containing the start
        position), even when no page marker falls within the range. This
        handles ranges that start *after* a page marker but before the next
        one — without this, the containing page would be omitted.

        Args:
            start: Start character position in original text.
            end: End character position in original text.
            page_map: List of ``(position, page_number)`` tuples from
                :meth:`_parse_page_markers`.

        Returns:
            Sorted list of unique page numbers this range spans.
        """
        pages: set = set()
        active_page = 1

        for pos, page_num in page_map:
            if pos <= start:
                active_page = page_num
            if start <= pos < end:
                pages.add(page_num)

        # Always add active_page — this handles ranges that start
        # after a page marker but before the next one, ensuring the
        # containing page is always included.
        pages.add(active_page)

        # Also check if end position crosses a page boundary
        for pos, page_num in page_map:
            if start < pos < end:
                pages.add(page_num)

        return sorted(pages)

    # ------------------------------------------------------------------
    # Token-based overlap splitting
    # ------------------------------------------------------------------

    def _token_overlap_split(
        self,
        text: str,
        chunk_tokens: int = 400,
        overlap_tokens: int = 50,
    ) -> List[str]:
        """Split text into overlapping token-based chunks.

        Uses ``tiktoken`` for accurate token counting, which is critical
        because embedding model context windows are token-based. This is
        superior to character-based or word-based splitting.

        Args:
            text: Text to split.
            chunk_tokens: Target tokens per chunk (default 400).
            overlap_tokens: Token overlap between chunks (default 50).

        Returns:
            List of text chunks.
        """
        tokens = self._encoding.encode(text)
        chunks: List[str] = []
        i = 0

        while i < len(tokens):
            chunk_tokens_list = tokens[i : i + chunk_tokens]
            if not chunk_tokens_list:
                break
            chunk_text = self._encoding.decode(chunk_tokens_list)
            chunks.append(chunk_text)
            i += chunk_tokens - overlap_tokens

        return chunks
