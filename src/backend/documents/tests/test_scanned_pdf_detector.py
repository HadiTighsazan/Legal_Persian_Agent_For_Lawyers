"""
Tests for the scanned PDF detector utility.

Tests cover:
- Typed PDF (has selectable text) → returns ``False``
- Scanned PDF (no selectable text) → returns ``True``
- Mixed PDF (some typed, some scanned pages) → returns ``False`` (conservative)
- Empty PDF (0 pages) → returns ``True`` (conservative)
- Invalid file path → raises ``FileNotFoundError``
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from documents.utils.scanned_pdf_detector import is_scanned_pdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_typed_pdf(path: str, num_pages: int = 3) -> str:
    """Create a typed PDF with Persian text on each page.

    Args:
        path: Output file path.
        num_pages: Number of pages to create.

    Returns:
        The path to the created PDF.
    """
    doc = fitz.open()
    try:
        for i in range(num_pages):
            page = doc.new_page()
            # Insert Persian text — this creates selectable text
            page.insert_text(
                (50, 100 + i * 200),
                f"این یک سند تایپ شده است. صفحه {i + 1} از {num_pages}. "
                f"ماده ۱: این قانون برای تنظیم روابط اجتماعی وضع می‌شود.",
                fontsize=12,
            )
        doc.save(path)
    finally:
        doc.close()
    return path


def _create_scanned_pdf(path: str, num_pages: int = 3) -> str:
    """Create a PDF with no selectable text (simulating a scanned document).

    Creates a PDF with blank pages (no text inserted) and adds a small image
    to ensure the page has content but no selectable text.

    Args:
        path: Output file path.
        num_pages: Number of pages to create.

    Returns:
        The path to the created PDF.
    """
    doc = fitz.open()
    try:
        for _ in range(num_pages):
            page = doc.new_page()
            # Insert a small rectangle as "image content" — no selectable text
            page.draw_rect(
                fitz.Rect(50, 50, 550, 750),
                color=(0, 0, 0),
                width=1,
            )
        doc.save(path)
    finally:
        doc.close()
    return path


def _create_mixed_pdf(path: str) -> str:
    """Create a mixed PDF: first page typed, rest scanned.

    Args:
        path: Output file path.

    Returns:
        The path to the created PDF.
    """
    doc = fitz.open()
    try:
        # Page 1: typed (has selectable text)
        # Text must exceed _TYPED_TEXT_THRESHOLD (50 chars) to be detected as typed
        page1 = doc.new_page()
        page1.insert_text(
            (50, 100),
            "این صفحه اول است و متن قابل انتخاب دارد. "
            "این یک سند تایپ شده است که بیش از پنجاه کاراکتر متن دارد.",
            fontsize=12,
        )

        # Page 2: scanned (no selectable text)
        page2 = doc.new_page()
        page2.draw_rect(
            fitz.Rect(50, 50, 550, 750),
            color=(0, 0, 0),
            width=1,
        )

        doc.save(path)
    finally:
        doc.close()
    return path


def _create_blank_pdf(path: str) -> str:
    """Create a blank PDF with one page and no text.

    PyMuPDF v24+ does not allow saving documents with zero pages, so we
    create a single blank page with no selectable text. A blank page has
    0 chars of selectable text, so ``is_scanned_pdf`` correctly returns
    ``True`` (scanned).

    Args:
        path: Output file path.

    Returns:
        The path to the created PDF.
    """
    doc = fitz.open()
    try:
        doc.new_page()  # One blank page, no text
        doc.save(path)
    finally:
        doc.close()
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIsScannedPdf:
    """Tests for :func:`is_scanned_pdf`."""

    def test_typed_pdf_returns_false(self) -> None:
        """Typed PDF with selectable text → returns ``False``."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            _create_typed_pdf(pdf_path)
            assert is_scanned_pdf(pdf_path) is False
        finally:
            os.unlink(pdf_path)

    def test_scanned_pdf_returns_true(self) -> None:
        """Scanned PDF with no selectable text → returns ``True``."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            _create_scanned_pdf(pdf_path)
            assert is_scanned_pdf(pdf_path) is True
        finally:
            os.unlink(pdf_path)

    def test_mixed_pdf_returns_false(self) -> None:
        """Mixed PDF (typed + scanned pages) → returns ``False`` (conservative)."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            _create_mixed_pdf(pdf_path)
            # Even though page 2 is scanned, page 1 has selectable text
            assert is_scanned_pdf(pdf_path) is False
        finally:
            os.unlink(pdf_path)

    def test_empty_pdf_returns_true(self) -> None:
        """Blank PDF (1 page, no text) → returns ``True`` (conservative)."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            _create_blank_pdf(pdf_path)
            assert is_scanned_pdf(pdf_path) is True
        finally:
            os.unlink(pdf_path)

    def test_invalid_path_raises_file_not_found(self) -> None:
        """Non-existent file path → raises ``fitz.FileNotFoundError``."""
        with pytest.raises(fitz.FileNotFoundError):
            is_scanned_pdf("/tmp/nonexistent_file_12345.pdf")

    def test_invalid_pdf_raises_fitz_error(self) -> None:
        """Invalid file (not a PDF) → raises ``fitz.FileDataError``."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"This is not a valid PDF file content")
            pdf_path = f.name

        try:
            with pytest.raises(fitz.FileDataError):
                is_scanned_pdf(pdf_path)
        finally:
            os.unlink(pdf_path)

    def test_single_page_typed_returns_false(self) -> None:
        """Single-page typed PDF → returns ``False``."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            _create_typed_pdf(pdf_path, num_pages=1)
            assert is_scanned_pdf(pdf_path) is False
        finally:
            os.unlink(pdf_path)

    def test_single_page_scanned_returns_true(self) -> None:
        """Single-page scanned PDF → returns ``True``."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name

        try:
            _create_scanned_pdf(pdf_path, num_pages=1)
            assert is_scanned_pdf(pdf_path) is True
        finally:
            os.unlink(pdf_path)
