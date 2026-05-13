"""
OCR service for extracting text from scanned PDFs.

Provides the :class:`OcrService` class that uses EasyOCR as the primary OCR
engine for Persian text, with Tesseract as a fallback when EasyOCR produces
low-confidence or low-content results.

Key design decisions:

1. **EasyOCR over PaddleOCR** — EasyOCR has significantly better Persian/Farsi
   accuracy than PaddleOCR. PaddleOCR's ``fa`` model is undertrained; EasyOCR's
   Persian model is production-grade for legal documents.

2. **Tesseract as fallback** — If EasyOCR produces low-confidence results
   (< 50 chars total), fall back to Tesseract with optimized config
   (``--psm 6 --oem 3``).

3. **OpenCV preprocessing** — Before OCR, apply contrast enhancement (CLAHE)
   and deskew (correct page tilt) to improve OCR accuracy.

4. **Layout-aware assembly** — Use bbox coordinates to detect multi-column
   layouts, group text lines into paragraphs using adaptive thresholds
   (median line height × 1.5), and insert proper newlines.

5. **Confidence filtering** — Skip OCR results with confidence < 0.5 to
   prevent noise pollution in the vector store.

6. **Page tracking** — Insert ``[PAGE N]`` markers for downstream chunking
   to track which pages each chunk spans.

Usage::

    from documents.services.ocr_service import OcrService

    ocr = OcrService()
    flat_text, segments = ocr.extract_text(pdf_bytes)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TextSegment:
    """A single text segment with page and position metadata.

    Attributes:
        text: The extracted text content.
        page: The page number (1-based).
        bbox: Bounding box ``(x1, y1, x2, y2)`` in pixel coordinates,
            or ``None`` if not available.
        confidence: OCR confidence score (0.0–1.0).
    """

    text: str
    page: int
    bbox: Optional[Tuple[float, float, float, float]] = None
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OcrService:
    """OCR service using EasyOCR with Tesseract fallback and layout-aware assembly.

    The service is designed for Persian legal documents, with specific
    optimizations for Arabic-script text extraction, multi-column layouts,
    and page tracking.

    Attributes:
        confidence_threshold: Minimum confidence score (0.0–1.0) to keep
            an OCR result. Results below this threshold are discarded.
        min_chars_for_easyocr: Minimum total characters from EasyOCR to
            consider the result acceptable. Below this, Tesseract fallback
            is triggered.
        contrast_enabled: Whether to apply CLAHE contrast enhancement
            during preprocessing.
        deskew_enabled: Whether to apply deskew correction during
            preprocessing.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.5,
        min_chars_for_easyocr: int = 50,
        contrast_enabled: bool = True,
        deskew_enabled: bool = True,
    ) -> None:
        self._easyocr_reader = None
        self._tesseract_available = self._check_tesseract()
        self.confidence_threshold = confidence_threshold
        self.min_chars_for_easyocr = min_chars_for_easyocr
        self.contrast_enabled = contrast_enabled
        self.deskew_enabled = deskew_enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_text(
        self, pdf_content: bytes
    ) -> Tuple[str, List[TextSegment]]:
        """Extract text from a scanned PDF with layout awareness.

        Pipeline:
        1. Convert PDF pages to images via ``pdf2image``
        2. For each page: preprocess (contrast + deskew) → EasyOCR →
           confidence filter → Tesseract fallback if low content
        3. Layout-aware assembly (column detection, paragraph grouping)
        4. Insert ``[PAGE N]`` markers for downstream chunking

        Args:
            pdf_content: Raw PDF file bytes.

        Returns:
            A tuple of ``(flat_text_with_page_markers, list_of_text_segments)``.
        """
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(pdf_content)

        all_segments: List[TextSegment] = []
        page_texts: List[str] = []

        for i, img in enumerate(images):
            page_num = i + 1

            # OpenCV preprocessing
            img_cv = self._preprocess(img)

            # Try EasyOCR first
            segments = self._extract_with_easyocr(img_cv, page_num)

            # Fallback to Tesseract if EasyOCR produced little content
            total_chars = sum(len(s.text) for s in segments)
            if total_chars < self.min_chars_for_easyocr and self._tesseract_available:
                logger.info(
                    "EasyOCR produced only %d chars for page %d — "
                    "falling back to Tesseract",
                    total_chars,
                    page_num,
                )
                segments = self._extract_with_tesseract(img_cv, page_num)

            # Layout-aware assembly
            page_text = self._assemble_layout(segments)
            page_texts.append(f"[PAGE {page_num}]\n{page_text}")
            all_segments.extend(segments)

        return "\n".join(page_texts), all_segments

    # ------------------------------------------------------------------
    # OpenCV preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, img):
        """Apply contrast enhancement and deskew to improve OCR accuracy.

        Pipeline:
        1. Convert PIL image to OpenCV format (RGB → BGR)
        2. Convert to grayscale
        3. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
           for contrast enhancement
        4. Detect and correct page tilt (deskew)

        Args:
            img: PIL Image instance.

        Returns:
            Preprocessed OpenCV image (grayscale).
        """
        import cv2
        import numpy as np

        # Convert PIL to cv2
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        # Grayscale
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # CLAHE contrast enhancement
        if self.contrast_enabled:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)

        # Deskew
        if self.deskew_enabled:
            gray = self._deskew(gray)

        return gray

    @staticmethod
    def _deskew(img):
        """Correct page tilt using OpenCV's minAreaRect.

        Detects the dominant text angle and rotates the image to correct it.
        Only rotates if the angle is significant (> 0.5 degrees).

        Args:
            img: Grayscale OpenCV image.

        Returns:
            Deskewed image.
        """
        import cv2
        import numpy as np

        coords = np.column_stack(np.where(img > 0))
        if len(coords) == 0:
            return img

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) > 0.5:  # Only rotate if significant
            h, w = img.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            img = cv2.warpAffine(
                img,
                M,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )

        return img

    # ------------------------------------------------------------------
    # OCR extraction
    # ------------------------------------------------------------------

    def _get_easyocr_reader(self):
        """Lazy-init EasyOCR reader to avoid loading model on import.

        The EasyOCR model is large (~1.5GB in memory). Lazy initialization
        ensures the model is only loaded when actually needed (i.e., when
        a scanned PDF is detected).

        Returns:
            An EasyOCR ``Reader`` instance configured for Persian (``fa``).
        """
        if self._easyocr_reader is None:
            import easyocr

            self._easyocr_reader = easyocr.Reader(
                ["fa"],  # Persian
                gpu=False,  # CPU-only for cost efficiency
            )
        return self._easyocr_reader

    @staticmethod
    def _check_tesseract() -> bool:
        """Check if Tesseract OCR is available on the system.

        Returns:
            ``True`` if Tesseract is installed and accessible.
        """
        try:
            import pytesseract  # noqa: F401

            pytesseract.get_tesseract_version()
            return True
        except Exception:
            logger.warning("Tesseract OCR is not available — skipping fallback")
            return False

    def _extract_with_easyocr(
        self, img, page_num: int
    ) -> List[TextSegment]:
        """Extract text using EasyOCR with confidence filtering.

        Args:
            img: Preprocessed OpenCV image (grayscale).
            page_num: The page number (1-based).

        Returns:
            List of :class:`TextSegment` instances with confidence > threshold.
        """
        reader = self._get_easyocr_reader()
        results = reader.readtext(img)

        segments: List[TextSegment] = []
        for bbox, text, confidence in results:
            if confidence < self.confidence_threshold:
                continue
            if not text.strip():
                continue

            # bbox format: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
            x1 = min(p[0] for p in bbox)
            y1 = min(p[1] for p in bbox)
            x2 = max(p[0] for p in bbox)
            y2 = max(p[1] for p in bbox)

            segments.append(
                TextSegment(
                    text=text.strip(),
                    page=page_num,
                    bbox=(x1, y1, x2, y2),
                    confidence=confidence,
                )
            )

        return segments

    def _extract_with_tesseract(
        self, img, page_num: int
    ) -> List[TextSegment]:
        """Fallback extraction using Tesseract with Persian language pack.

        Uses ``--psm 6`` (assume uniform block of text) and ``--oem 3``
        (default LSTM engine) for optimal Persian text recognition.

        Args:
            img: Preprocessed OpenCV image (grayscale).
            page_num: The page number (1-based).

        Returns:
            List of :class:`TextSegment` instances.
        """
        import pytesseract

        # Get detailed OCR data with bounding boxes
        data = pytesseract.image_to_data(
            img,
            lang="fas",
            config="--psm 6 --oem 3",  # Assume uniform block + LSTM
            output_type=pytesseract.Output.DICT,
        )

        segments: List[TextSegment] = []
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])
            if not text or conf < 50:
                continue

            x, y, w, h = (
                data["left"][i],
                data["top"][i],
                data["width"][i],
                data["height"][i],
            )
            segments.append(
                TextSegment(
                    text=text,
                    page=page_num,
                    bbox=(x, y, x + w, y + h),
                    confidence=conf / 100.0,
                )
            )

        return segments

    # ------------------------------------------------------------------
    # Layout-aware assembly
    # ------------------------------------------------------------------

    def _assemble_layout(self, segments: List[TextSegment]) -> str:
        """Layout-aware text assembly with column detection.

        Strategy:
        1. Detect multi-column layout by clustering x-positions
        2. For each column, group lines into paragraphs using adaptive
           thresholds (median line height × 1.5)
        3. Insert proper newlines between paragraphs

        Column detection is conservative: only splits into columns if the
        x-position span exceeds 40% of the page width. This avoids false
        positives for single-column documents with wide margins.

        Args:
            segments: List of :class:`TextSegment` instances, sorted by
                y-position (top to bottom).

        Returns:
            Assembled text with paragraph breaks.
        """
        if not segments:
            return ""

        # Sort by y-position (top to bottom)
        segments.sort(key=lambda s: (s.bbox[1] if s.bbox else 0))

        # Detect columns by clustering x-positions
        x_centers = [
            (s.bbox[0] + s.bbox[2]) / 2 for s in segments if s.bbox
        ]

        if not x_centers:
            return " ".join(s.text for s in segments)

        # Simple column detection: if x-positions span > 60% of page width
        x_min = min(x_centers)
        x_max = max(x_centers)
        x_span = x_max - x_min

        # Get page width from bboxes
        all_x2 = [s.bbox[2] for s in segments if s.bbox]
        page_width = max(all_x2) if all_x2 else x_max + 100

        if x_span > page_width * 0.4:
            # Multi-column detected
            mid_x = page_width / 2
            left_col = [
                s for s in segments if s.bbox and s.bbox[2] < mid_x
            ]
            right_col = [
                s for s in segments if s.bbox and s.bbox[0] > mid_x
            ]

            left_text = self._lines_to_paragraphs(left_col)
            right_text = self._lines_to_paragraphs(right_col)

            if left_text and right_text:
                return (
                    f"{left_text}\n\n--- ستون دوم ---\n\n{right_text}"
                )
            elif left_text:
                return left_text
            else:
                return right_text
        else:
            # Single column
            return self._lines_to_paragraphs(segments)

    def _lines_to_paragraphs(
        self, segments: List[TextSegment]
    ) -> str:
        """Group text lines into paragraphs with adaptive gap threshold.

        Uses the median line height × 1.5 as the gap threshold for
        paragraph breaks. This adapts to different font sizes across
        documents, unlike a fixed pixel threshold.

        Args:
            segments: List of :class:`TextSegment` instances, sorted by
                y-position.

        Returns:
            Text with paragraphs separated by double newlines.
        """
        if not segments:
            return ""

        # Calculate adaptive threshold (median line height × 1.5)
        heights = [
            (s.bbox[3] - s.bbox[1]) if s.bbox else 10
            for s in segments
        ]
        median_height = sorted(heights)[len(heights) // 2]
        gap_threshold = median_height * 1.5

        paragraphs: List[List[str]] = []
        current_para: List[str] = []
        prev_y: Optional[float] = None

        for seg in segments:
            current_y = seg.bbox[1] if seg.bbox else 0

            if (
                prev_y is not None
                and (current_y - prev_y) > gap_threshold
            ):
                if current_para:
                    paragraphs.append(current_para)
                    current_para = []

            current_para.append(seg.text)
            prev_y = current_y

        if current_para:
            paragraphs.append(current_para)

        return "\n\n".join(" ".join(p) for p in paragraphs)
