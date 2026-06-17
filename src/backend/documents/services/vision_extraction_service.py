"""
Vision-Language Model Extraction Service for Persian legal PDFs.

Replaces the old EasyOCR + Tesseract + pdfplumber fallback chain with a
single, page-level VLM-based extraction path. Uses OpenRouter's OpenAI-compatible
API to call Qwen3 VL (or any compatible vision-language model).

Features:
- **Single-page extraction**: :meth:`extract_page` for individual pages.
- **Batch extraction**: :meth:`extract_pages_batch` groups multiple pages into
  a single VLM call using multi-image messages — ~4x faster than sequential
  single-page calls.
- **JPEG compression**: Uses JPEG instead of PNG for 5-10x smaller images,
  reducing token usage and API latency.
- **Post-extraction verification**: Automated checks for article number
  coherence, digit consistency, and content repetition.

Architecture
------------
1. PyMuPDF extracts text with RTL flags (primary, fast path).
2. If page-level quality check fails (garbled CMap), this service is called.
3. The problematic page(s) are rendered to JPEG images via ``fitz.Pixmap``
   (PyMuPDF's built-in renderer — no pdf2image/poppler needed).
4. Images are base64-encoded and sent to the VLM via OpenRouter.
   Multiple pages can be batched in a single call.
5. The returned text is verified for legal fidelity.
6. Unverified pages are flagged in document metadata for human review.

Usage::

    from documents.services.vision_extraction_service import VisionExtractionService

    service = VisionExtractionService()
    # Single page
    result = service.extract_page(pdf_document, page_num=5)
    # Batch pages (faster!)
    results = service.extract_pages_batch(pdf_document, [5, 6, 7, 8])
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import fitz  # PyMuPDF
from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    """Result of post-extraction verification checks.

    Attributes:
        verified: ``True`` if all checks passed.
        confidence: A float 0.0–1.0 representing overall confidence.
        flags: Human-readable list of issues found (empty if verified).
    """

    verified: bool = True
    confidence: float = 1.0
    flags: list[str] = field(default_factory=list)


@dataclass
class PageExtractionResult:
    """Result of extracting text from a single page via VLM.

    Attributes:
        page_num: 1-based page number.
        text: The extracted text (VLM output or fallback).
        source: The model name or ``"error"``.
        quality_score: Quality score of the output (0.0–1.0).
        verified: Whether post-extraction checks passed.
        verification_flags: List of issues found during verification.
    """

    page_num: int
    text: str
    source: str = "qwen3_vl"
    quality_score: float = 0.0
    verified: bool = True
    verification_flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Extraction prompts (Persian — strict, legal-domain focused)
# ---------------------------------------------------------------------------

# Prompt for single-page extraction
_VLM_EXTRACTION_PROMPT: str = """\
شما یک استخراج‌کننده‌ی دقیق متن از تصویر هستید.

قوانین سختگیرانه:
۱. متن را کلمه‌به‌کلمه و حرف‌به‌حرف استخراج کنید.
۲. اعداد، شماره‌ی مواد، تبصره‌ها، بندها و ارجاعات را دقیقاً حفظ کنید.
۳. سرصفحه‌ها، پاصفحه‌ها، مهرها و متن تکراری را حذف نکنید.
۴. ساختار پاراگراف‌بندی را حفظ کنید.
۵. اگر به بخشی اطمینان ندارید، علامت [?] بگذارید.
۶. فقط متن استخراج‌شده را برگردانید.
"""

# Prompt for batch (multi-page) extraction
_VLM_BATCH_PROMPT: str = """\
شما یک استخراج‌کننده‌ی دقیق متن هستید.

{count} تصویر از صفحات مختلف یک سند حقوقی به شما داده شده است.
برای هر صفحه متن را جداگانه استخراج کنید.

قوانین سختگیرانه:
۱. قبل از متن هر صفحه، عبارت [PAGE X] را قرار دهید.
   مثال: [PAGE 1]\nمتن صفحه اول\n\n[PAGE 2]\nمتن صفحه دوم
۲. متن را کلمه‌به‌کلمه و بدون تغییر استخراج کنید.
۳. اعداد و شماره مواد را دقیقاً حفظ کنید.
۴. فقط متن با [PAGE X] را برگردانید — هیچ توضیح اضافه‌ای ندهید.
"""


# ---------------------------------------------------------------------------
# Article number detection patterns
# ---------------------------------------------------------------------------

_ARTICLE_PATTERN: re.Pattern = re.compile(r"ماده\s*(\d+)")

# Regex to split batch VLM response into per-page sections
_PAGE_MARKER_RE: re.Pattern = re.compile(r"\[PAGE\s*(\d+)\]\s*\n?")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class VisionExtractionService:
    """Page-level VLM OCR for problematic Persian PDF pages.

    Uses OpenRouter's OpenAI-compatible API to call a vision-language model
    (default: ``qwen/qwen3-vl-235b-a22b-instruct``) for extracting text from
    PDF pages that PyMuPDF could not extract correctly due to broken /ToUnicode
    CMap tables.

    Supports both single-page and batched (multi-page) extraction for
    optimal performance.

    Attributes:
        model: The VLM model name on OpenRouter.
        dpi: Rendering DPI for page-to-image conversion (default: 150).
        max_retries: Max API retries on failure (default: 3).
        batch_size: Default number of pages per batch call (default: 4).
    """

    def __init__(
        self,
        model: str | None = None,
        dpi: int | None = None,
        max_retries: int | None = None,
        batch_size: int = 4,
    ) -> None:
        self.model: str = model or getattr(
            settings, "VISION_EXTRACTION_MODEL",
            "qwen/qwen3-vl-235b-a22b-instruct",
        )
        self.dpi: int = dpi or getattr(settings, "VISION_EXTRACTION_DPI", 150)
        self.max_retries: int = max_retries or getattr(
            settings, "VISION_EXTRACTION_MAX_RETRIES", 3,
        )
        self.batch_size: int = batch_size

        # Lazy-init the OpenAI client (OpenRouter-compatible)
        self._client: Any = None

    # ------------------------------------------------------------------
    # Public API — Single page
    # ------------------------------------------------------------------

    def extract_page(
        self, pdf_document: fitz.Document, page_num: int
    ) -> PageExtractionResult:
        """Extract text from a single page using the VLM.

        Renders the page to a JPEG image and sends it to the VLM.

        Args:
            pdf_document: An open PyMuPDF document.
            page_num: 0-based page index (as used by PyMuPDF).

        Returns:
            A :class:`PageExtractionResult` with the extracted text and
            verification metadata.
        """
        try:
            # Step 1: Render page to JPEG at configured DPI
            page = pdf_document.load_page(page_num)
            pix = page.get_pixmap(dpi=self.dpi)
            img_bytes: bytes = pix.tobytes("jpeg")  # JPEG for speed

            # Step 2: Base64-encode the image
            img_b64: str = base64.b64encode(img_bytes).decode("utf-8")
            data_uri: str = f"data:image/jpeg;base64,{img_b64}"

            # Step 3: Build content and call VLM
            content: list[dict[str, Any]] = [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": _VLM_EXTRACTION_PROMPT},
            ]
            text = self._call_vlm(content)

            # Step 4: Post-extraction verification
            verification = self._verify(text, page_num + 1)

            # Step 5: Compute quality score
            quality = self._compute_output_quality(text)

            logger.info(
                "VisionExtractionService: Page %d extracted (%d chars, "
                "verified=%s, confidence=%.2f)",
                page_num + 1,
                len(text),
                verification.verified,
                verification.confidence,
            )

            return PageExtractionResult(
                page_num=page_num + 1,
                text=text,
                source=self.model,
                quality_score=quality,
                verified=verification.verified,
                verification_flags=verification.flags,
            )

        except Exception as e:
            logger.exception(
                "VisionExtractionService: Failed to extract page %d: %s",
                page_num + 1,
                e,
            )
            return PageExtractionResult(
                page_num=page_num + 1,
                text="",
                source="error",
                quality_score=0.0,
                verified=False,
                verification_flags=[f"extraction_error: {e}"],
            )

    # ------------------------------------------------------------------
    # Public API — Batch extraction (performance optimization)
    # ------------------------------------------------------------------

    def extract_pages_batch(
        self,
        pdf_document: fitz.Document,
        page_indices: list[int],
        batch_size: int | None = None,
    ) -> dict[int, PageExtractionResult]:
        """Extract text from multiple pages in batched VLM calls.

        Groups pages into batches and sends each batch as a single
        multi-image VLM call. This is **~4x faster** than calling
        :meth:`extract_page` for each page individually.

        Args:
            pdf_document: An open PyMuPDF document.
            page_indices: List of 0-based page indices to extract.
            batch_size: Pages per batch (defaults to ``self.batch_size``).

        Returns:
            A dict mapping 1-based page numbers to
            :class:`PageExtractionResult` instances.
        """
        batch_size = batch_size or self.batch_size
        results: dict[int, PageExtractionResult] = {}

        for i in range(0, len(page_indices), batch_size):
            batch = page_indices[i:i + batch_size]
            batch_results = self._extract_batch(pdf_document, batch)
            results.update(batch_results)

        return results

    # ------------------------------------------------------------------
    # Internal — Single VLM API call
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Lazy-init the OpenAI-compatible client for OpenRouter."""
        if self._client is None:
            import openai  # noqa: PLC0415
            from httpx import Client, Timeout  # noqa: PLC0415

            http_client = Client(
                timeout=Timeout(
                    connect=30.0,
                    read=120.0,     # VL models can be slow
                    write=60.0,
                    pool=30.0,
                ),
            )

            self._client = openai.OpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url=settings.OPENROUTER_BASE_URL,
                http_client=http_client,
            )
        return self._client

    def _call_vlm(self, content: list[dict[str, Any]]) -> str:
        """Send content to the VLM and return the extracted text.

        The ``content`` parameter is a list of content parts (images + text)
        for the chat completion message. This supports both single-image
        and multi-image (batch) extraction.

        Implements retry with exponential backoff.

        Args:
            content: List of content parts, e.g.:
                ``[{"type": "image_url", ...}, {"type": "text", ...}]``

        Returns:
            The extracted text from the VLM.

        Raises:
            RuntimeError: If all retries fail.
        """
        client = self._get_client()

        messages = [
            {
                "role": "user",
                "content": content,
            },
        ]

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore[arg-type]
                    max_tokens=4096,
                    temperature=0.0,  # Deterministic output for legal text
                )

                result_text: str = response.choices[0].message.content or ""

                # Log token usage for cost monitoring
                if response.usage:
                    logger.info(
                        "VisionExtractionService: VLM call completed "
                        "(model=%s, attempt=%d/%d, prompt_tokens=%d, "
                        "completion_tokens=%d)",
                        self.model,
                        attempt,
                        self.max_retries,
                        response.usage.prompt_tokens or 0,
                        response.usage.completion_tokens or 0,
                    )

                return result_text

            except Exception as e:
                last_error = e
                logger.warning(
                    "VisionExtractionService: VLM call attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries:
                    import time  # noqa: PLC0415
                    time.sleep(2.0 ** attempt)  # Exponential backoff

        raise RuntimeError(
            f"VisionExtractionService: All {self.max_retries} retries failed. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Internal — Batch extraction
    # ------------------------------------------------------------------

    def _extract_batch(
        self,
        pdf_document: fitz.Document,
        batch: list[int],
    ) -> dict[int, PageExtractionResult]:
        """Extract text from a batch of pages in a single VLM call.

        Renders all pages in the batch to JPEG, builds a multi-image
        message, sends one API call, and parses the response.

        Args:
            pdf_document: An open PyMuPDF document.
            batch: List of 0-based page indices for this batch.

        Returns:
            Dict mapping 1-based page numbers to extraction results.
        """
        try:
            # Step 1: Render all pages in batch to JPEG images
            images: list[str] = []
            for idx in batch:
                page = pdf_document.load_page(idx)
                pix = page.get_pixmap(dpi=self.dpi)
                img_bytes: bytes = pix.tobytes("jpeg")
                img_b64: str = base64.b64encode(img_bytes).decode("utf-8")
                images.append(f"data:image/jpeg;base64,{img_b64}")

            # Step 2: Build multi-image content
            content: list[dict[str, Any]] = [
                {"type": "image_url", "image_url": {"url": img}}
                for img in images
            ]
            content.append({
                "type": "text",
                "text": _VLM_BATCH_PROMPT.format(count=len(batch)),
            })

            # Step 3: Single API call for all pages in batch
            response_text = self._call_vlm(content)

            # Step 4: Parse the response into per-page sections
            page_texts = self._parse_batch_response(response_text, batch)

            # Step 5: Build results for each page
            results: dict[int, PageExtractionResult] = {}
            for page_idx, text in zip(batch, page_texts):
                page_num = page_idx + 1
                verification = self._verify(text, page_num)

                logger.info(
                    "VisionExtractionService: Batch page %d extracted "
                    "(%d chars, verified=%s, confidence=%.2f)",
                    page_num,
                    len(text),
                    verification.verified,
                    verification.confidence,
                )

                results[page_num] = PageExtractionResult(
                    page_num=page_num,
                    text=text,
                    source=self.model,
                    quality_score=self._compute_output_quality(text),
                    verified=verification.verified,
                    verification_flags=verification.flags,
                )

            return results

        except Exception as e:
            logger.exception(
                "VisionExtractionService: Batch extraction failed for "
                "pages %s: %s",
                [p + 1 for p in batch],
                e,
            )
            # Return error results for all pages in the batch
            return {
                p + 1: PageExtractionResult(
                    page_num=p + 1,
                    text="",
                    source="error",
                    quality_score=0.0,
                    verified=False,
                    verification_flags=[f"batch_error: {e}"],
                )
                for p in batch
            }

    @staticmethod
    def _parse_batch_response(
        response: str,
        batch: list[int],
    ) -> list[str]:
        """Parse the VLM batch response into per-page text sections.

        The VLM is instructed to return text with ``[PAGE N]`` markers.
        This method splits the response by these markers and returns
        one text string per page in the batch.

        If the VLM doesn't include the expected markers (fallback), the
        response is split equally among the pages.

        Args:
            response: The raw VLM response text.
            batch: List of 0-based page indices for context.

        Returns:
            A list of text strings, one per page in the batch,
            in the same order as ``batch``.
        """
        if not response or not response.strip():
            return [""] * len(batch)

        # Try to split by [PAGE N] markers
        parts = _PAGE_MARKER_RE.split(response)
        # parts format: ["", "1", "text1", "2", "text2", ...]
        # Remove any leading empty string
        if parts and not parts[0].strip():
            parts = parts[1:]

        if len(parts) >= 2:
            # We have markers — extract text for each requested page
            page_map: dict[int, str] = {}
            for i in range(0, len(parts) - 1, 2):
                marker_num = int(parts[i])
                marker_text = parts[i + 1].strip()
                page_map[marker_num] = marker_text

            # Map batch pages to extracted text
            result: list[str] = []
            for idx in batch:
                page_num = idx + 1
                result.append(page_map.get(page_num, ""))
            return result

        # Fallback: no markers found — split equally
        if len(batch) == 1:
            return [response.strip()]

        # If we can't parse, return the full response for the first page
        # and empty for the rest (better than losing data)
        texts = [response.strip()] + [""] * (len(batch) - 1)
        logger.warning(
            "VisionExtractionService: Batch response missing [PAGE N] "
            "markers — using fallback split. Response preview: %s...",
            response[:100],
        )
        return texts

    # ------------------------------------------------------------------
    # Internal — Post-extraction verification
    # ------------------------------------------------------------------

    def _verify(self, text: str, page_num: int) -> VerificationResult:
        """Run automated quality checks on VLM output.

        Checks:
        1. **Empty/short output** — Suspicious if very little text.
        2. **Article number coherence** — Ascending sequence check.
        3. **Digit consistency** — Persian vs. Latin digit usage.
        4. **Excessive repetition** — Duplicated paragraph detection.
        5. **Persian character ratio** — Minimum Persian char presence.

        Args:
            text: The VLM output text.
            page_num: 1-based page number (for logging).

        Returns:
            A :class:`VerificationResult` with findings.
        """
        flags: list[str] = []
        text = text.strip()

        # 1. Empty/short output check
        if not text:
            return VerificationResult(
                verified=False,
                confidence=0.0,
                flags=["empty_output: VLM returned empty text"],
            )
        if len(text) < 10:
            return VerificationResult(
                verified=False,
                confidence=0.1,
                flags=[f"too_short: only {len(text)} characters"],
            )

        # 2. Persian character ratio check
        persian_count = sum(
            1 for c in text if 0x0600 <= ord(c) <= 0x06FF
        )
        persian_ratio = persian_count / max(len(text), 1)
        if persian_count > 0 and persian_ratio < 0.1:
            flags.append(
                f"low_persian_ratio: {persian_ratio:.2%} Persian chars"
            )

        # 3. Article number coherence check
        article_numbers = [
            int(m) for m in _ARTICLE_PATTERN.findall(text)
        ]
        if len(article_numbers) >= 2:
            for i in range(len(article_numbers) - 1):
                gap = article_numbers[i + 1] - article_numbers[i]
                if gap > 2:
                    flags.append(
                        f"possible_article_gap: ماده {article_numbers[i]} → "
                        f"ماده {article_numbers[i + 1]} (gap={gap})"
                    )
                elif gap < 0:
                    flags.append(
                        f"non_ascending_articles: "
                        f"ماده {article_numbers[i]} → "
                        f"ماده {article_numbers[i + 1]}"
                    )

        # 4. Digit consistency check
        has_persian_digits = bool(re.search(r"[۰-۹]", text))
        has_english_digits = bool(re.search(r"[0-9]", text))
        if has_english_digits and not has_persian_digits and persian_ratio > 0.2:
            flags.append(
                "digit_conversion: All digits are Latin (may have lost "
                "Persian digit forms)"
            )

        # 5. Excessive repetition check
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) >= 4:
            from collections import Counter  # noqa: PLC0415
            line_counts = Counter(lines)
            repeated = [l for l, c in line_counts.items() if c >= 3]
            if repeated:
                flags.append(
                    f"repeated_content: {len(repeated)} lines repeated 3+ times"
                )

        # Compute confidence score from flags
        confidence = 1.0 - (len(flags) * 0.15)
        confidence = max(0.1, min(1.0, confidence))

        return VerificationResult(
            verified=len(flags) == 0,
            confidence=confidence,
            flags=flags,
        )

    # ------------------------------------------------------------------
    # Internal — Output quality scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_output_quality(text: str) -> float:
        """Compute a simple quality score for VLM output.

        Based on:
        - Presence of Persian characters (weight 0.4)
        - Reasonable length (weight 0.3)
        - Variety of characters (weight 0.3)

        Args:
            text: The VLM output text.

        Returns:
            A float 0.0–1.0 representing quality.
        """
        if not text or not text.strip():
            return 0.0

        persian_count = sum(
            1 for c in text if 0x0600 <= ord(c) <= 0x06FF
        )
        persian_score = min(persian_count / 100, 1.0)

        length_score = min(len(text.strip()) / 500, 1.0)

        unique_chars = len(set(text))
        variety_score = min(unique_chars / 50, 1.0)

        return 0.4 * persian_score + 0.3 * length_score + 0.3 * variety_score

    # ------------------------------------------------------------------
    # Static helper — cross-page article sequence check
    # ------------------------------------------------------------------

    @staticmethod
    def check_article_sequence(
        pages_text: list[tuple[int, str]]
    ) -> list[str]:
        """Check that article numbers across pages form a logical sequence.

        Args:
            pages_text: List of ``(page_number_1based, text)`` tuples.

        Returns:
            A list of human-readable flag strings (empty if all clear).
        """
        flags: list[str] = []
        all_articles: list[tuple[int, int]] = []

        for page_num, text in pages_text:
            for match in _ARTICLE_PATTERN.finditer(text):
                all_articles.append((page_num, int(match.group(1))))

        if len(all_articles) < 3:
            return []

        for i in range(len(all_articles) - 1):
            curr_page, curr_art = all_articles[i]
            next_page, next_art = all_articles[i + 1]

            if next_art < curr_art:
                flags.append(
                    f"article_sequence_drop: ماده {curr_art} on page {curr_page} "
                    f"→ ماده {next_art} on page {next_page}"
                )

        return flags
