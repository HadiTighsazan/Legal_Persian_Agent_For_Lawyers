"""
Tests for the OCR service.

Tests cover:
- TextSegment dataclass creation and defaults
- OcrService initialization (lazy reader, tesseract check)
- OpenCV preprocessing (contrast, deskew)
- EasyOCR extraction with confidence filtering (mocked)
- Tesseract fallback when EasyOCR produces low content (mocked)
- Layout assembly (single column, multi-column, empty)
- Page marker injection
- Empty/invalid input handling
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from documents.services.ocr_service import OcrService, TextSegment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ocr_service() -> OcrService:
    """Return a fresh :class:`OcrService` instance for each test."""
    return OcrService()


# ---------------------------------------------------------------------------
# TextSegment dataclass tests
# ---------------------------------------------------------------------------


class TestTextSegment:
    """Tests for the :class:`TextSegment` dataclass."""

    def test_minimal_creation(self) -> None:
        """Create a TextSegment with only required fields."""
        seg = TextSegment(text="Hello", page=1)
        assert seg.text == "Hello"
        assert seg.page == 1
        assert seg.bbox is None
        assert seg.confidence == 0.0

    def test_full_creation(self) -> None:
        """Create a TextSegment with all fields."""
        seg = TextSegment(
            text="متن فارسی",
            page=2,
            bbox=(10.0, 20.0, 100.0, 50.0),
            confidence=0.95,
        )
        assert seg.text == "متن فارسی"
        assert seg.page == 2
        assert seg.bbox == (10.0, 20.0, 100.0, 50.0)
        assert seg.confidence == 0.95


# ---------------------------------------------------------------------------
# OcrService initialization tests
# ---------------------------------------------------------------------------


class TestOcrServiceInit:
    """Tests for :class:`OcrService` initialization."""

    def test_default_params(self, ocr_service: OcrService) -> None:
        """Default parameters are set correctly."""
        assert ocr_service.confidence_threshold == 0.5
        assert ocr_service.min_chars_for_easyocr == 50
        assert ocr_service.contrast_enabled is True
        assert ocr_service.deskew_enabled is True
        assert ocr_service._easyocr_reader is None  # Lazy init

    def test_custom_params(self) -> None:
        """Custom parameters are applied."""
        service = OcrService(
            confidence_threshold=0.7,
            min_chars_for_easyocr=100,
            contrast_enabled=False,
            deskew_enabled=False,
        )
        assert service.confidence_threshold == 0.7
        assert service.min_chars_for_easyocr == 100
        assert service.contrast_enabled is False
        assert service.deskew_enabled is False

    def test_lazy_reader_not_loaded(self, ocr_service: OcrService) -> None:
        """EasyOCR reader is not loaded on init (lazy)."""
        assert ocr_service._easyocr_reader is None


# ---------------------------------------------------------------------------
# Layout assembly tests
# ---------------------------------------------------------------------------


class TestLayoutAssembly:
    """Tests for layout-aware text assembly."""

    def test_empty_segments(self, ocr_service: OcrService) -> None:
        """Empty segments → empty string."""
        result = ocr_service._assemble_layout([])
        assert result == ""

    def test_single_column(self, ocr_service: OcrService) -> None:
        """Single column text is assembled correctly."""
        segments = [
            TextSegment(
                text="این خط اول است.",
                page=1,
                bbox=(50.0, 100.0, 500.0, 120.0),
                confidence=0.95,
            ),
            TextSegment(
                text="این خط دوم است.",
                page=1,
                bbox=(50.0, 130.0, 500.0, 150.0),
                confidence=0.90,
            ),
        ]
        result = ocr_service._assemble_layout(segments)
        assert "این خط اول است." in result
        assert "این خط دوم است." in result

    def test_paragraph_grouping(self, ocr_service: OcrService) -> None:
        """Lines with large vertical gaps are grouped into paragraphs."""
        segments = [
            TextSegment(
                text="پاراگراف اول - خط اول.",
                page=1,
                bbox=(50.0, 100.0, 500.0, 120.0),
                confidence=0.95,
            ),
            TextSegment(
                text="پاراگراف اول - خط دوم.",
                page=1,
                bbox=(50.0, 125.0, 500.0, 145.0),
                confidence=0.90,
            ),
            # Large gap → new paragraph
            TextSegment(
                text="پاراگراف دوم - خط اول.",
                page=1,
                bbox=(50.0, 300.0, 500.0, 320.0),
                confidence=0.85,
            ),
        ]
        result = ocr_service._assemble_layout(segments)
        # Should have two paragraphs separated by double newline
        assert "\n\n" in result

    def test_no_bbox_fallback(self, ocr_service: OcrService) -> None:
        """Segments without bbox are joined with spaces."""
        segments = [
            TextSegment(text="کلمه", page=1),
            TextSegment(text="دوم", page=1),
            TextSegment(text="سوم", page=1),
        ]
        result = ocr_service._assemble_layout(segments)
        assert result == "کلمه دوم سوم"


# ---------------------------------------------------------------------------
# Preprocessing tests
# ---------------------------------------------------------------------------


class TestPreprocessing:
    """Tests for OpenCV preprocessing."""

    def test_preprocess_returns_grayscale(self, ocr_service: OcrService) -> None:
        """Preprocessing returns a grayscale image (2D array)."""
        from PIL import Image

        # Create a simple test image
        img = Image.new("RGB", (100, 100), color="white")
        result = ocr_service._preprocess(img)
        # Should be a 2D numpy array (grayscale)
        assert hasattr(result, "shape")
        assert len(result.shape) == 2

    def test_preprocess_no_contrast(self) -> None:
        """Preprocessing without contrast enhancement."""
        service = OcrService(contrast_enabled=False)
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="white")
        result = service._preprocess(img)
        assert hasattr(result, "shape")
        assert len(result.shape) == 2

    def test_preprocess_no_deskew(self) -> None:
        """Preprocessing without deskew."""
        service = OcrService(deskew_enabled=False)
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="white")
        result = service._preprocess(img)
        assert hasattr(result, "shape")
        assert len(result.shape) == 2


# ---------------------------------------------------------------------------
# EasyOCR extraction tests (mocked)
# ---------------------------------------------------------------------------


class TestEasyOCRExtraction:
    """Tests for EasyOCR extraction with mocked reader."""

    def test_confidence_filtering(self, ocr_service: OcrService) -> None:
        """Results below confidence threshold are filtered out."""
        mock_results = [
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "متن خوب", 0.95),
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "متن بد", 0.3),  # Below 0.5
        ]

        with patch.object(
            ocr_service, "_get_easyocr_reader"
        ) as mock_reader:
            mock_instance = MagicMock()
            mock_instance.readtext.return_value = mock_results
            mock_reader.return_value = mock_instance

            segments = ocr_service._extract_with_easyocr(
                "mock_img", page_num=1
            )

        assert len(segments) == 1
        assert segments[0].text == "متن خوب"
        assert segments[0].confidence == 0.95

    def test_empty_text_filtered(self, ocr_service: OcrService) -> None:
        """Empty text results are filtered out."""
        mock_results = [
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "   ", 0.9),
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "", 0.8),
        ]

        with patch.object(
            ocr_service, "_get_easyocr_reader"
        ) as mock_reader:
            mock_instance = MagicMock()
            mock_instance.readtext.return_value = mock_results
            mock_reader.return_value = mock_instance

            segments = ocr_service._extract_with_easyocr(
                "mock_img", page_num=1
            )

        assert len(segments) == 0

    def test_bbox_conversion(self, ocr_service: OcrService) -> None:
        """EasyOCR bbox format is correctly converted to (x1, y1, x2, y2)."""
        mock_results = [
            (
                [[10, 20], [100, 20], [100, 50], [10, 50]],
                "متن تست",
                0.9,
            ),
        ]

        with patch.object(
            ocr_service, "_get_easyocr_reader"
        ) as mock_reader:
            mock_instance = MagicMock()
            mock_instance.readtext.return_value = mock_results
            mock_reader.return_value = mock_instance

            segments = ocr_service._extract_with_easyocr(
                "mock_img", page_num=1
            )

        assert len(segments) == 1
        assert segments[0].bbox == (10.0, 20.0, 100.0, 50.0)
        assert segments[0].page == 1


# ---------------------------------------------------------------------------
# Tesseract fallback tests (mocked)
# ---------------------------------------------------------------------------


class TestTesseractFallback:
    """Tests for Tesseract fallback extraction."""

    def test_tesseract_extraction(self, ocr_service: OcrService) -> None:
        """Tesseract extraction returns TextSegments with bbox."""
        mock_data = {
            "text": ["متن", "تست", "", "تبریز"],
            "conf": ["90", "85", "-1", "70"],
            "left": [10, 100, 0, 50],
            "top": [20, 25, 0, 200],
            "width": [80, 50, 0, 100],
            "height": [15, 15, 0, 20],
        }

        with patch(
            "documents.services.ocr_service.pytesseract"
        ) as mock_pytesseract:
            mock_pytesseract.image_to_data.return_value = mock_data

            segments = ocr_service._extract_with_tesseract(
                "mock_img", page_num=2
            )

        assert len(segments) == 3  # Empty string and low conf filtered
        assert segments[0].text == "متن"
        assert segments[0].page == 2
        assert segments[0].bbox == (10, 20, 90, 35)
        assert segments[1].text == "تست"
        assert segments[2].text == "تبریز"

    def test_tesseract_not_available(self) -> None:
        """When Tesseract is not available, _tesseract_available is False."""
        with patch(
            "documents.services.ocr_service.pytesseract.get_tesseract_version"
        ) as mock_version:
            mock_version.side_effect = Exception("Not found")

            service = OcrService()
            assert service._tesseract_available is False


# ---------------------------------------------------------------------------
# Full extraction pipeline tests (mocked)
# ---------------------------------------------------------------------------


class TestExtractText:
    """Tests for the full ``extract_text`` pipeline."""

    @patch("documents.services.ocr_service.convert_from_bytes")
    def test_extract_text_empty_pdf(
        self, mock_convert: MagicMock, ocr_service: OcrService
    ) -> None:
        """Empty PDF (0 pages) → empty string and empty list."""
        mock_convert.return_value = []

        flat_text, segments = ocr_service.extract_text(b"fake_pdf_bytes")
        assert flat_text == ""
        assert segments == []

    @patch("documents.services.ocr_service.convert_from_bytes")
    def test_extract_text_single_page(
        self, mock_convert: MagicMock, ocr_service: OcrService
    ) -> None:
        """Single page PDF → text with [PAGE 1] marker."""
        from PIL import Image

        # Create a simple test image
        img = Image.new("RGB", (100, 100), color="white")
        mock_convert.return_value = [img]

        # Mock EasyOCR to return some text
        with patch.object(
            ocr_service, "_extract_with_easyocr"
        ) as mock_easyocr:
            mock_easyocr.return_value = [
                TextSegment(
                    text="متن تست",
                    page=1,
                    bbox=(10.0, 20.0, 100.0, 40.0),
                    confidence=0.95,
                )
            ]

            flat_text, segments = ocr_service.extract_text(
                b"fake_pdf_bytes"
            )

        assert "[PAGE 1]" in flat_text
        assert "متن تست" in flat_text
        assert len(segments) == 1

    @patch("documents.services.ocr_service.convert_from_bytes")
    def test_extract_text_multi_page(
        self, mock_convert: MagicMock, ocr_service: OcrService
    ) -> None:
        """Multi-page PDF → text with [PAGE N] markers for each page."""
        from PIL import Image

        img1 = Image.new("RGB", (100, 100), color="white")
        img2 = Image.new("RGB", (100, 100), color="white")
        mock_convert.return_value = [img1, img2]

        with patch.object(
            ocr_service, "_extract_with_easyocr"
        ) as mock_easyocr:
            mock_easyocr.side_effect = [
                [
                    TextSegment(
                        text="صفحه اول",
                        page=1,
                        bbox=(10.0, 20.0, 100.0, 40.0),
                        confidence=0.95,
                    )
                ],
                [
                    TextSegment(
                        text="صفحه دوم",
                        page=2,
                        bbox=(10.0, 20.0, 100.0, 40.0),
                        confidence=0.90,
                    )
                ],
            ]

            flat_text, segments = ocr_service.extract_text(
                b"fake_pdf_bytes"
            )

        assert "[PAGE 1]" in flat_text
        assert "[PAGE 2]" in flat_text
        assert "صفحه اول" in flat_text
        assert "صفحه دوم" in flat_text
        assert len(segments) == 2

    @patch("documents.services.ocr_service.convert_from_bytes")
    def test_tesseract_fallback_triggered(
        self, mock_convert: MagicMock, ocr_service: OcrService
    ) -> None:
        """Tesseract fallback is triggered when EasyOCR produces low content."""
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="white")
        mock_convert.return_value = [img]

        # EasyOCR returns very little content (below min_chars_for_easyocr)
        with patch.object(
            ocr_service, "_extract_with_easyocr"
        ) as mock_easyocr, patch.object(
            ocr_service, "_extract_with_tesseract"
        ) as mock_tesseract:
            mock_easyocr.return_value = [
                TextSegment(
                    text="کوتاه",
                    page=1,
                    bbox=(10.0, 20.0, 100.0, 40.0),
                    confidence=0.95,
                )
            ]
            mock_tesseract.return_value = [
                TextSegment(
                    text="متن طولانی‌تر از Tesseract",
                    page=1,
                    bbox=(10.0, 20.0, 200.0, 40.0),
                    confidence=0.85,
                )
            ]

            flat_text, segments = ocr_service.extract_text(
                b"fake_pdf_bytes"
            )

        # Should have used Tesseract output (longer text)
        assert "Tesseract" in flat_text
        mock_tesseract.assert_called_once()
