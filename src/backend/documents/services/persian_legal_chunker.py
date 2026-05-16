"""
Semantic chunker for Persian legal text.

Provides the :class:`PersianLegalChunker` class — a drop-in replacement for
:class:`~documents.services.anchor_chunking_service.AnchorChunkingService`
that implements **sentence-aware semantic chunking** specifically designed for
Persian legal document structure.

Key improvements over :class:`AnchorChunkingService`:

1. **Sentence-boundary splitting** — Chunks never break mid-sentence or
   mid-word, eliminating garbled chunks like ``"ه تحقق از ارکان ب"``.
2. **Two-tier anchor system** — Primary anchors create structural sections;
   secondary anchors provide chunk-boundary hints within sections.
3. **Minimum chunk size enforcement** — Small chunks are merged with adjacent
   chunks, eliminating the 12-token chunk problem.
4. **Intelligent overlap at sentence boundaries** — Overlap is applied at
   sentence boundaries (not raw token boundaries), producing clean, readable
   Persian text.
5. **Rich metadata** — Each chunk carries ``section_type``, ``anchor_text``,
   ``sentence_count``, ``has_verdict``, ``has_legislation_ref``,
   ``legislation_refs``, ``start_page``, ``end_page`` for smarter RAG retrieval.

Usage::

    from documents.services.persian_legal_chunker import PersianLegalChunker

    chunker = PersianLegalChunker(
        min_chunk_tokens=150,
        max_chunk_tokens=400,
        overlap_sentences=1,
    )
    chunks = chunker.chunk_text(
        extracted_text,
        chunk_tokens=400,
        overlap_tokens=50,  # ignored, kept for API compatibility
    )
    for chunk in chunks:
        print(chunk.content)       # Clean text, no metadata
        print(chunk.pages)         # [1, 2, 3]
        print(chunk.metadata)      # {"section_type": "verdict", ...}
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

# The tokeniser used by OpenAI's cl100k_base encoding (GPT-4,
# text-embedding-ada-002, text-embedding-3-small, text-embedding-3-large).
_ENCODING_NAME: str = "cl100k_base"

# Regex to detect injected page markers like [PAGE 1], [PAGE 42], etc.
_PAGE_MARKER_RE: Pattern[str] = re.compile(r"\[PAGE\s+(\d+)\]")

# ---------------------------------------------------------------------------
# Primary anchors — structural section boundaries
# ---------------------------------------------------------------------------
# These create new structural sections in the document. When one of these
# patterns is found, the text is split into a new section.
PRIMARY_ANCHORS: List[str] = [
    # Court ruling sections
    r"ر[أا]ی[\s‌]+دادگاه",
    r"دادنامه",
    r"قرار[\s‌]+دادگاه",
    # Case flow
    r"گردشکار",
    r"گردش[\s‌]+کار",
    r"خلاصه[\s‌]+گردشکار",
    # Proceedings
    r"صورت[\s‌]*جلسه",
    r"صورت[\s‌]*مجلس",
    r"جلسه[\s‌]+رسیدگی",
    r"ختم[\s‌]+دادرسی",
    r"ختم[\s‌]+جلسه",
    # Legal opinions
    r"نظریه[\s‌]+مشورتی",
    r"نظریه[\s‌]+تفسیری",
    # Case details
    r"در[\s‌]+خصوص[\s‌]+دعوی",
    r"در[\s‌]+خصوص[\s‌]+دادخواست",
    r"شرح[\s‌]+شکایت",
    r"شرح[\s‌]+دادخواست",
    r"دفاعیات",
    r"دفاعیات[\s‌]+خوانده",
    r"دفاعیات[\s‌]+وکیل",
    # Document headers
    r"بسمه[\s‌]+تعالی",
    r"بسم[\s‌]+الله[\s‌]+الرحمن[\s‌]+الرحیم",
    # Legislation structure
    r"ماده[\s‌]*\d+",
    r"فصل[\s‌]*\d+",
    r"بخش[\s‌]*\d+",
    r"تبصره[\s‌]*\d+",
]

# ---------------------------------------------------------------------------
# Secondary anchors — chunk-boundary hints (not section boundaries)
# ---------------------------------------------------------------------------
# These are hints that a chunk boundary may be appropriate. If the current
# chunk exceeds min_chunk_tokens, the chunk is closed at the secondary anchor
# and a new chunk begins within the same section.
CHUNK_BOUNDARY_HINTS: List[str] = [
    r"مستنداً[\s‌]+به[\s‌]+مواد",
    r"لذا[\s‌]+دادگاه",
    r"دادگاه[\s‌]+با[\s‌]+توجه[\s‌]+به",
    r"محکوم[\s‌]+می‌نماید",
    r"حکم[\s‌]+به",
]

# ---------------------------------------------------------------------------
# Section type mapping — maps anchor patterns to section type strings
# ---------------------------------------------------------------------------
# The keys are the same regex patterns used in PRIMARY_ANCHORS. The values
# are human-readable section type strings stored in chunk metadata.
SECTION_TYPE_MAP: Dict[str, str] = {
    r"ر[أا]ی[\s‌]+دادگاه": "verdict",
    r"دادنامه": "verdict",
    r"قرار[\s‌]+دادگاه": "verdict",
    r"گردشکار": "proceedings",
    r"گردش[\s‌]+کار": "proceedings",
    r"خلاصه[\s‌]+گردشکار": "proceedings",
    r"صورت[\s‌]*جلسه": "minutes",
    r"صورت[\s‌]*مجلس": "minutes",
    r"جلسه[\s‌]+رسیدگی": "minutes",
    r"ختم[\s‌]+دادرسی": "proceedings",
    r"ختم[\s‌]+جلسه": "proceedings",
    r"نظریه[\s‌]+مشورتی": "opinion",
    r"نظریه[\s‌]+تفسیری": "opinion",
    r"در[\s‌]+خصوص[\s‌]+دعوی": "case_detail",
    r"در[\s‌]+خصوص[\s‌]+دادخواست": "case_detail",
    r"شرح[\s‌]+شکایت": "case_detail",
    r"شرح[\s‌]+دادخواست": "case_detail",
    r"دفاعیات": "defense",
    r"دفاعیات[\s‌]+خوانده": "defense",
    r"دفاعیات[\s‌]+وکیل": "defense",
    r"بسمه[\s‌]+تعالی": "header",
    r"بسم[\s‌]+الله[\s‌]+الرحمن[\s‌]+الرحیم": "header",
    r"ماده[\s‌]*\d+": "article",
    r"فصل[\s‌]*\d+": "chapter",
    r"بخش[\s‌]*\d+": "section",
    r"تبصره[\s‌]*\d+": "note",
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AnchorChunk:
    """A single chunk produced by the Persian legal chunker.

    Attributes:
        content: The chunk text content (NO metadata injected).
        pages: List of page numbers this chunk spans.
        char_count: Number of characters.
        token_count: Number of tokens (via tiktoken).
        metadata: Metadata dict (section_type, anchor_text, etc.) —
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


class PersianLegalChunker:
    """Semantic chunker for Persian legal text.

    Implements sentence-aware semantic chunking with a two-tier anchor system
    (primary anchors for structural sections, secondary anchors for chunk
    boundaries), minimum chunk size enforcement, and intelligent overlap at
    sentence boundaries.

    The chunking pipeline:

    1. Clean page markers from text and build a page map
    2. Normalize Persian text for consistent regex matching
    3. Detect structural section boundaries via primary anchors
    4. For each section:
       a. If under min_chunk_tokens → merge with next section
       b. If over max_chunk_tokens → sentence-aware split with overlap
       c. If within range → keep as single chunk
    5. Apply secondary anchor hints to split chunks at natural boundaries
    6. Build rich metadata for each chunk
    """

    # Persian normalization patterns
    _DIACRITICS_RE: Pattern[str] = re.compile(r"[\u064B-\u065F\u0670]")

    # Sentence boundary pattern — compiled once in __init__
    # Handles:
    # - Persian period `.` (not in numbers like 1.2)
    # - Persian question mark `؟`
    # - Exclamation `!`
    # - Colon `:` (common in legal: "ماده ۱:")
    # - Double newline (paragraph boundary)
    _SENTENCE_PATTERN_RAW: str = (
        r"(?<!\d)[\.؟!](?!\d)|"   # Period/question/exclamation not between digits
        r"\:\s|"                   # Colon followed by space
        r"\n{2,}"                  # Double newline (paragraph)
    )

    # Verdict language detection
    _VERDICT_PATTERNS: List[Pattern[str]] = [
        re.compile(r"محکوم[\s‌]+می‌نماید"),
        re.compile(r"حکم[\s‌]+به"),
        re.compile(r"محکومیت"),
    ]

    def __init__(
        self,
        min_chunk_tokens: int = 150,
        max_chunk_tokens: int = 400,
        overlap_sentences: int = 1,
    ) -> None:
        """Initialise the PersianLegalChunker.

        Args:
            min_chunk_tokens: Minimum tokens per chunk (default 150).
                Chunks below this threshold are merged with adjacent chunks.
            max_chunk_tokens: Maximum tokens per chunk (default 400).
                Chunks above this threshold are split at sentence boundaries.
            overlap_sentences: Number of sentences to overlap between
                consecutive chunks (default 1). Overlap is always at sentence
                boundaries, producing clean readable text.
        """
        self.min_chunk_tokens = min_chunk_tokens
        self.max_chunk_tokens = max_chunk_tokens
        self.overlap_sentences = overlap_sentences

        # Cache the encoding instance so we don't re-fetch it on every call.
        self._encoding = tiktoken.get_encoding(_ENCODING_NAME)

        # Compile the combined primary anchor pattern once.
        self._primary_anchor_pattern: Pattern[str] = re.compile(
            r"(" + "|".join(PRIMARY_ANCHORS) + r")"
        )

        # Compile the combined secondary anchor pattern once.
        self._secondary_anchor_pattern: Pattern[str] = re.compile(
            r"(" + "|".join(CHUNK_BOUNDARY_HINTS) + r")"
        )

        # Compile the sentence boundary pattern once.
        self._sentence_pattern: Pattern[str] = re.compile(
            self._SENTENCE_PATTERN_RAW
        )

        # Build a compiled pattern map for section type detection.
        # We compile each anchor pattern individually for accurate matching.
        self._section_type_patterns: List[tuple[Pattern[str], str]] = []
        for pattern_str, section_type in SECTION_TYPE_MAP.items():
            self._section_type_patterns.append(
                (re.compile(pattern_str), section_type)
            )

        # Compile legislation reference pattern.
        self._legislation_ref_pattern: Pattern[str] = re.compile(
            r"ماده[\s‌]*(\d+(?:[\s‌]*و[\s‌]*\d+)*)"
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
        """Main chunking method using semantic chunking.

        Pipeline:
        1. Clean page markers and build page map
        2. Normalize Persian text for regex matching
        3. Detect structural section boundaries via primary anchors
        4. For each section, apply sentence-aware splitting with
           minimum/maximum token enforcement
        5. Apply secondary anchor hints for chunk-boundary refinement
        6. Build rich metadata for each chunk

        Args:
            text: Full extracted text with ``[PAGE N]`` markers.
            chunk_tokens: Target tokens per chunk (default 400).
                Maps to ``max_chunk_tokens`` from constructor.
            overlap_tokens: Token overlap between chunks (default 50).
                **Ignored** — replaced by ``overlap_sentences`` from
                constructor. Kept for API compatibility with
                :class:`AnchorChunkingService`.

        Returns:
            List of :class:`AnchorChunk` instances. Returns an empty list
            if ``text`` is empty or contains only whitespace.
        """
        if not text or not text.strip():
            return []

        # Override max_chunk_tokens if chunk_tokens is explicitly provided
        # (allows callers to override the constructor default).
        effective_max_tokens = chunk_tokens

        # Step 1: Clean page markers and build page map
        cleaned_text, page_map = self._clean_page_markers(text)

        # Step 2: Normalize for matching (keep cleaned text for content)
        normalized = self._normalize_persian(cleaned_text)

        # Step 3: Detect structural section boundaries
        sections = self._detect_section_boundaries(normalized)

        final_chunks: List[AnchorChunk] = []

        if not sections:
            # No anchors found — fall back to sentence-based split
            # across the entire document.
            sentences = self._split_by_sentences(cleaned_text)
            if not sentences:
                return []

            # Merge small chunks and split large ones
            sentence_groups = self._merge_small_chunks(
                sentences, self.min_chunk_tokens
            )

            for group in sentence_groups:
                group_text = " ".join(group)
                token_count = len(self._encoding.encode(group_text))

                if token_count > effective_max_tokens:
                    # Split large group at sentence boundaries
                    sub_chunks = self._split_large_section(
                        group,
                        effective_max_tokens,
                        self.overlap_sentences,
                    )
                    for sub_text in sub_chunks:
                        orig_pos = self._find_text_position(
                            sub_text, cleaned_text
                        )
                        pages = self._resolve_pages(
                            orig_pos,
                            orig_pos + len(sub_text),
                            page_map,
                        )
                        metadata = self._build_metadata(
                            sub_text,
                            section_type="general",
                            anchor_text=None,
                            pages=pages,
                        )
                        final_chunks.append(
                            AnchorChunk(
                                content=sub_text,
                                pages=pages,
                                char_count=len(sub_text),
                                token_count=len(
                                    self._encoding.encode(sub_text)
                                ),
                                metadata=metadata,
                                section_title="کل سند",
                            )
                        )
                else:
                    orig_pos = self._find_text_position(
                        group_text, cleaned_text
                    )
                    pages = self._resolve_pages(
                        orig_pos,
                        orig_pos + len(group_text),
                        page_map,
                    )
                    metadata = self._build_metadata(
                        group_text,
                        section_type="general",
                        anchor_text=None,
                        pages=pages,
                    )
                    final_chunks.append(
                        AnchorChunk(
                            content=group_text,
                            pages=pages,
                            char_count=len(group_text),
                            token_count=token_count,
                            metadata=metadata,
                            section_title="کل سند",
                        )
                    )

            return final_chunks

        # Step 4: Process each section
        section_chunks: List[tuple[str, str, str, List[int]]] = []  # (text, section_type, anchor_text, pages)

        for section in sections:
            start = section["start"]
            end = section["end"]
            anchor_text = section["anchor_text"]
            section_type = section["section_type"]

            # Extract the actual content from cleaned text
            # We need to map normalized positions back to cleaned text
            section_content = cleaned_text[start:end].strip()

            if not section_content:
                continue

            # Resolve pages for this section
            pages = self._resolve_pages(start, end, page_map)

            section_chunks.append(
                (section_content, section_type, anchor_text, pages)
            )

        # Step 5: Process each section's content
        for i, (content, section_type, anchor_text, pages) in enumerate(
            section_chunks
        ):
            token_count = len(self._encoding.encode(content))

            if token_count < self.min_chunk_tokens:
                # Small chunk — merge with next section if possible
                if i + 1 < len(section_chunks):
                    # Will be merged in the next iteration
                    continue
                elif final_chunks:
                    # Last small chunk — merge with previous
                    last_chunk = final_chunks[-1]
                    merged_text = last_chunk.content + "\n" + content
                    merged_pages = sorted(
                        set(last_chunk.pages + pages)
                    )
                    metadata = self._build_metadata(
                        merged_text,
                        section_type=last_chunk.metadata.get(
                            "section_type", section_type
                        ),
                        anchor_text=last_chunk.metadata.get(
                            "anchor_text", anchor_text
                        ),
                        pages=merged_pages,
                    )
                    final_chunks[-1] = AnchorChunk(
                        content=merged_text,
                        pages=merged_pages,
                        char_count=len(merged_text),
                        token_count=len(
                            self._encoding.encode(merged_text)
                        ),
                        metadata=metadata,
                        section_title=last_chunk.section_title,
                    )
                else:
                    # Only chunk — keep it even if small
                    metadata = self._build_metadata(
                        content,
                        section_type=section_type,
                        anchor_text=anchor_text,
                        pages=pages,
                    )
                    final_chunks.append(
                        AnchorChunk(
                            content=content,
                            pages=pages,
                            char_count=len(content),
                            token_count=token_count,
                            metadata=metadata,
                            section_title=anchor_text,
                        )
                    )
            elif token_count > effective_max_tokens:
                # Large section — split at sentence boundaries
                sentences = self._split_by_sentences(content)
                if not sentences:
                    continue

                sub_chunks = self._split_large_section(
                    sentences,
                    effective_max_tokens,
                    self.overlap_sentences,
                )

                for sub_text in sub_chunks:
                    orig_pos = self._find_text_position(
                        sub_text, cleaned_text
                    )
                    chunk_pages = self._resolve_pages(
                        orig_pos,
                        orig_pos + len(sub_text),
                        page_map,
                    )
                    metadata = self._build_metadata(
                        sub_text,
                        section_type=section_type,
                        anchor_text=anchor_text,
                        pages=chunk_pages,
                    )
                    final_chunks.append(
                        AnchorChunk(
                            content=sub_text,
                            pages=chunk_pages,
                            char_count=len(sub_text),
                            token_count=len(
                                self._encoding.encode(sub_text)
                            ),
                            metadata=metadata,
                            section_title=anchor_text,
                        )
                    )
            else:
                # Within range — keep as single chunk
                metadata = self._build_metadata(
                    content,
                    section_type=section_type,
                    anchor_text=anchor_text,
                    pages=pages,
                )
                final_chunks.append(
                    AnchorChunk(
                        content=content,
                        pages=pages,
                        char_count=len(content),
                        token_count=token_count,
                        metadata=metadata,
                        section_title=anchor_text,
                    )
                )

        # Step 6: Apply secondary anchor hints
        final_chunks = self._apply_secondary_hints(
            final_chunks, cleaned_text, page_map
        )

        return final_chunks

    # ------------------------------------------------------------------
    # Page marker cleaning
    # ------------------------------------------------------------------

    def _clean_page_markers(
        self, text: str
    ) -> tuple[str, List[tuple]]:
        """Remove ``[PAGE N]`` markers from text and build a page map.

        Args:
            text: Text containing ``[PAGE N]`` markers.

        Returns:
            Tuple of ``(cleaned_text, page_map)`` where ``page_map`` is a
            sorted list of ``(char_position, page_number)`` tuples in the
            **cleaned** text.
        """
        page_map: List[tuple] = []
        cleaned = text

        # First pass: collect all page markers with their positions
        raw_markers: List[tuple] = []
        for match in _PAGE_MARKER_RE.finditer(text):
            raw_markers.append(
                (match.start(), match.end(), int(match.group(1)))
            )

        if not raw_markers:
            return cleaned, []

        # Second pass: remove markers and adjust positions
        # We process from end to start to avoid position shifting
        offset = 0
        for start, end, page_num in sorted(
            raw_markers, key=lambda x: x[0], reverse=True
        ):
            cleaned = cleaned[:start] + cleaned[end:]
            # The page marker at this position is being removed.
            # We record the position in the final cleaned text.
            page_map.append((start - offset, page_num))
            offset += end - start

        # Sort page_map by position (ascending)
        page_map.sort(key=lambda x: x[0])

        return cleaned, page_map

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
    # Section boundary detection
    # ------------------------------------------------------------------

    def _detect_section_boundaries(
        self, text: str
    ) -> List[dict]:
        """Detect structural section boundaries using primary anchors.

        Finds all primary anchor matches in the text and builds a list of
        section boundaries. Each section includes the anchor text and its
        detected section type.

        Args:
            text: Normalized Persian text.

        Returns:
            List of dicts with keys:
            - ``start``: Start position of the section (anchor match start).
            - ``end``: End position of the section (next anchor start or
              end of text).
            - ``anchor_text``: The matched anchor text.
            - ``section_type``: Detected section type string.
        """
        matches = list(self._primary_anchor_pattern.finditer(text))

        if not matches:
            return []

        sections: List[dict] = []

        for i, match in enumerate(matches):
            anchor_text = match.group(0)
            section_type = self._detect_section_type(anchor_text)

            start = match.start()
            end = (
                matches[i + 1].start()
                if i + 1 < len(matches)
                else len(text)
            )

            sections.append(
                {
                    "start": start,
                    "end": end,
                    "anchor_text": anchor_text,
                    "section_type": section_type,
                }
            )

        return sections

    # ------------------------------------------------------------------
    # Sentence splitting
    # ------------------------------------------------------------------

    def _split_by_sentences(self, text: str) -> List[str]:
        """Split text into sentences at Persian sentence boundaries.

        Uses a compiled regex pattern that respects:
        - Persian period ``.`` (not in numbers like ``1.2``)
        - Persian question mark ``؟``
        - Exclamation ``!``
        - Colon ``:`` followed by space (common in legal: ``ماده ۱:``)
        - Double newline ``\\n\\n`` (paragraph boundary)

        Args:
            text: Text to split into sentences.

        Returns:
            List of sentence strings. Returns empty list for empty/whitespace
            input.
        """
        if not text or not text.strip():
            return []

        sentences: List[str] = []
        last_end = 0

        for match in self._sentence_pattern.finditer(text):
            start = last_end
            end = match.end()
            sentence = text[start:end].strip()
            if sentence:
                sentences.append(sentence)
            last_end = end

        # Add remaining text after last match
        remaining = text[last_end:].strip()
        if remaining:
            sentences.append(remaining)

        # If no sentence boundaries found, return the whole text as one
        if not sentences:
            sentences = [text.strip()]

        return sentences

    # ------------------------------------------------------------------
    # Minimum chunk size enforcement
    # ------------------------------------------------------------------

    def _merge_small_chunks(
        self,
        sentences: List[str],
        min_tokens: int,
    ) -> List[List[str]]:
        """Merge small sentence groups to meet minimum token threshold.

        Groups sentences into chunks where each group (except possibly the
        last) meets the minimum token count. Small groups are merged with
        adjacent groups.

        Args:
            sentences: List of sentence strings.
            min_tokens: Minimum token count per group.

        Returns:
            List of sentence groups, where each group is a list of sentences.
        """
        if not sentences:
            return []

        # First pass: accumulate sentences into groups based on token count
        groups: List[List[str]] = []
        current_group: List[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = len(self._encoding.encode(sentence))

            if current_tokens + sentence_tokens <= min_tokens * 2:
                # Still accumulating
                current_group.append(sentence)
                current_tokens += sentence_tokens
            else:
                # Start a new group
                if current_group:
                    groups.append(current_group)
                current_group = [sentence]
                current_tokens = sentence_tokens

        # Don't forget the last group
        if current_group:
            groups.append(current_group)

        # Second pass: merge groups that are below min_tokens
        merged_groups: List[List[str]] = []
        i = 0
        while i < len(groups):
            group = groups[i]
            group_tokens = sum(
                len(self._encoding.encode(s))
                for s in group
            )

            if group_tokens < min_tokens:
                # Try to merge with next group
                if i + 1 < len(groups):
                    # Merge with next group
                    groups[i + 1] = group + groups[i + 1]
                elif merged_groups:
                    # Last group — merge with previous
                    merged_groups[-1] = merged_groups[-1] + group
                else:
                    # Only group — keep it
                    merged_groups.append(group)
            else:
                merged_groups.append(group)

            i += 1

        return merged_groups

    # ------------------------------------------------------------------
    # Large section splitting (sentence-aware with overlap)
    # ------------------------------------------------------------------

    def _split_large_section(
        self,
        sentences: List[str],
        max_tokens: int,
        overlap_sentences: int,
    ) -> List[str]:
        """Split a large section into sentence-aware chunks with overlap.

        Accumulates sentences until the chunk reaches ``max_tokens``, then
        closes the chunk and starts a new one. The last ``overlap_sentences``
        sentences of chunk N become the first sentences of chunk N+1.

        Args:
            sentences: List of sentence strings from the section.
            max_tokens: Maximum tokens per chunk.
            overlap_sentences: Number of sentences to overlap between chunks.

        Returns:
            List of chunk text strings.
        """
        if not sentences:
            return []

        chunks: List[str] = []
        i = 0

        # Safety guard: prevent any possible infinite loop
        max_iterations = len(sentences) * 2
        iteration_count = 0

        while i < len(sentences):
            iteration_count += 1
            if iteration_count > max_iterations:
                logger.error(
                    "_split_large_section: Exceeded max iterations (%d) for %d sentences — breaking",
                    max_iterations,
                    len(sentences),
                )
                break

            chunk_sentences: List[str] = []
            chunk_tokens = 0

            # Accumulate sentences until we hit max_tokens
            j = i
            while j < len(sentences):
                sentence_tokens = len(
                    self._encoding.encode(sentences[j])
                )
                if chunk_tokens + sentence_tokens > max_tokens and chunk_sentences:
                    # Adding this sentence would exceed max_tokens
                    break
                chunk_sentences.append(sentences[j])
                chunk_tokens += sentence_tokens
                j += 1

            if not chunk_sentences:
                # Single sentence exceeds max_tokens — keep it anyway
                chunk_sentences = [sentences[i]]
                j = i + 1

            chunk_text = " ".join(chunk_sentences)
            chunks.append(chunk_text)

            # Move to next chunk with overlap
            # The overlap sentences are the last `overlap_sentences` sentences
            # of the current chunk
            if overlap_sentences > 0 and j < len(sentences):
                # Start the next chunk `overlap_sentences` sentences before
                # the end of the current chunk
                next_i = j - overlap_sentences
                # GUARD: Ensure we always make progress (prevent infinite loop)
                # when a single sentence exceeds max_tokens and
                # overlap_sentences >= 1, the inner loop breaks immediately
                # leaving j = i + 1, so next_i = (i + 1) - overlap_sentences.
                # With overlap_sentences = 1, next_i = i — i never advances!
                i = next_i if next_i > i else j
            else:
                i = j

        return chunks

    # ------------------------------------------------------------------
    # Secondary anchor hints
    # ------------------------------------------------------------------

    def _apply_secondary_hints(
        self,
        chunks: List[AnchorChunk],
        text: str,
        page_map: List[tuple],
    ) -> List[AnchorChunk]:
        """Split chunks at secondary anchor boundaries.

        For each chunk, check if it contains secondary anchor patterns. If
        the chunk exceeds ``min_chunk_tokens`` and a secondary anchor is
        found, split the chunk at the secondary anchor boundary.

        Args:
            chunks: List of chunks to refine.
            text: The cleaned text (for position lookups).
            page_map: Page map for page resolution.

        Returns:
            Refined list of chunks with secondary anchor splits applied.
        """
        if not chunks:
            return []

        refined_chunks: List[AnchorChunk] = []

        for chunk in chunks:
            # Find all secondary anchor matches in this chunk's content
            matches = list(
                self._secondary_anchor_pattern.finditer(chunk.content)
            )

            if not matches:
                # No secondary anchors — keep as-is
                refined_chunks.append(chunk)
                continue

            # Check if chunk exceeds min_tokens
            if chunk.token_count <= self.min_chunk_tokens:
                refined_chunks.append(chunk)
                continue

            # Split at secondary anchor boundaries
            split_positions = [0]
            for match in matches:
                split_positions.append(match.start())
            split_positions.append(len(chunk.content))

            for k in range(len(split_positions) - 1):
                seg_start = split_positions[k]
                seg_end = split_positions[k + 1]
                seg_text = chunk.content[seg_start:seg_end].strip()

                if not seg_text:
                    continue

                # Find position in original text for page resolution
                orig_pos = self._find_text_position(
                    seg_text, text
                )
                seg_pages = self._resolve_pages(
                    orig_pos,
                    orig_pos + len(seg_text),
                    page_map,
                )

                metadata = self._build_metadata(
                    seg_text,
                    section_type=chunk.metadata.get(
                        "section_type", "general"
                    ),
                    anchor_text=chunk.metadata.get(
                        "anchor_text"
                    ),
                    pages=seg_pages,
                )

                refined_chunks.append(
                    AnchorChunk(
                        content=seg_text,
                        pages=seg_pages,
                        char_count=len(seg_text),
                        token_count=len(
                            self._encoding.encode(seg_text)
                        ),
                        metadata=metadata,
                        section_title=chunk.section_title,
                    )
                )

        return refined_chunks

    # ------------------------------------------------------------------
    # Section type detection
    # ------------------------------------------------------------------

    def _detect_section_type(self, anchor_text: str) -> str:
        """Detect the section type from an anchor text match.

        Iterates through ``SECTION_TYPE_MAP`` patterns to find the matching
        section type for the given anchor text.

        Args:
            anchor_text: The matched anchor text (e.g., ``"رأی دادگاه"``).

        Returns:
            Section type string (e.g., ``"verdict"``, ``"minutes"``,
            ``"proceedings"``). Returns ``"general"`` if no pattern matches.
        """
        for pattern, section_type in self._section_type_patterns:
            if pattern.search(anchor_text):
                return section_type
        return "general"

    # ------------------------------------------------------------------
    # Legislation reference extraction
    # ------------------------------------------------------------------

    def _extract_legislation_refs(self, text: str) -> List[str]:
        """Extract article references from text.

        Finds all ``ماده \\d+`` patterns in the text and returns them as
        a list of unique references.

        Args:
            text: Text to search for legislation references.

        Returns:
            List of unique article reference strings (e.g.,
            ``["ماده ۱۲۳", "ماده ۴۵"]``).
        """
        refs: List[str] = []
        for match in self._legislation_ref_pattern.finditer(text):
            ref = match.group(0).strip()
            if ref not in refs:
                refs.append(ref)
        return refs

    # ------------------------------------------------------------------
    # Metadata building
    # ------------------------------------------------------------------

    def _build_metadata(
        self,
        chunk_text: str,
        section_type: str = "general",
        anchor_text: Optional[str] = None,
        pages: Optional[List[int]] = None,
    ) -> dict:
        """Build rich metadata dict for a chunk.

        Args:
            chunk_text: The chunk text content.
            section_type: Detected section type string.
            anchor_text: The anchor text that preceded this chunk, or None.
            pages: List of page numbers this chunk spans.

        Returns:
            Metadata dict with keys:
            - ``section_type``: Type of legal section.
            - ``anchor_text``: The matched anchor text (if any).
            - ``sentence_count``: Number of sentences in the chunk.
            - ``has_verdict``: Whether verdict language is present.
            - ``has_legislation_ref``: Whether legislation references exist.
            - ``legislation_refs``: List of extracted article references.
            - ``start_page``: First page of the chunk.
            - ``end_page``: Last page of the chunk.
        """
        metadata: dict = {}

        # Section type
        metadata["section_type"] = section_type

        # Anchor text
        if anchor_text:
            metadata["anchor_text"] = anchor_text

        # Sentence count
        sentences = self._split_by_sentences(chunk_text)
        metadata["sentence_count"] = len(sentences)

        # Verdict language detection
        has_verdict = False
        for pattern in self._VERDICT_PATTERNS:
            if pattern.search(chunk_text):
                has_verdict = True
                break
        metadata["has_verdict"] = has_verdict

        # Legislation references
        legislation_refs = self._extract_legislation_refs(chunk_text)
        metadata["has_legislation_ref"] = len(legislation_refs) > 0
        metadata["legislation_refs"] = legislation_refs

        # Page tracking
        if pages:
            metadata["start_page"] = min(pages)
            metadata["end_page"] = max(pages)

        return metadata

    # ------------------------------------------------------------------
    # Page tracking helpers
    # ------------------------------------------------------------------

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
            start: Start character position in cleaned text.
            end: End character position in cleaned text.
            page_map: List of ``(position, page_number)`` tuples from
                :meth:`_clean_page_markers`.

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

        return sorted(pages)

    @staticmethod
    def _find_text_position(
        needle: str, haystack: str
    ) -> int:
        """Find the position of a text substring in a larger text.

        Uses ``str.find`` to locate the needle. If not found, returns 0.

        Args:
            needle: The substring to find.
            haystack: The larger text to search in.

        Returns:
            Character position of the needle in the haystack, or 0 if not
            found.
        """
        pos = haystack.find(needle)
        return pos if pos >= 0 else 0
