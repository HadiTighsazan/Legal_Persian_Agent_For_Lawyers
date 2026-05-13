"""
Scanned PDF detection utility for the document processing pipeline.

Provides :func:`is_scanned_pdf` to determine whether a PDF is scanned
(image-based) or typed (has selectable text). Uses a conservative approach:
if ANY page has more than 50 characters of selectable text, the PDF is
considered typed. This avoids unnecessary OCR overhead for mixed documents
where some pages are typed and others are scanned.

Usage::

    from documents.utils.scanned_pdf_detector import is_scanned_pdf

    if is_scanned_pdf("/path/to/document.pdf"):
        # Route to EasyOCR pipeline
        ...
    else:
        # Route to PyMuPDF pipeline
        ...
"""

from __future__ import annotations

import logging

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Minimum number of selectable text characters required on a single page
# to consider the PDF "typed" (not scanned). This threshold is deliberately
# low to be conservative: even a page with a few lines of selectable text
# is treated as typed, avoiding unnecessary OCR overhead.
_TYPED_TEXT_THRESHOLD: int = 50


def is_scanned_pdf(pdf_path: str) -> bool:
    """Determine whether a PDF is scanned (image-based) or typed.

    Opens the PDF with PyMuPDF and samples each page for selectable text.
    Uses a **conservative** approach:

    - If **any** page has more than ``_TYPED_TEXT_THRESHOLD`` (50) characters
      of selectable text, the PDF is considered **typed** (returns ``False``).
    - If **all** pages have little or no selectable text (≤ 50 chars each),
      the PDF is considered **scanned** (returns ``True``).

    This conservative strategy avoids unnecessary OCR overhead for mixed
    documents where some pages are typed and others are scanned. A single
    typed page is sufficient to use the faster PyMuPDF extraction path.

    Args:
        pdf_path: Path to the PDF file on disk.

    Returns:
        ``True`` if the PDF appears to be scanned (image-based).
        ``False`` if the PDF has selectable text (typed).

    Raises:
        FileNotFoundError: If ``pdf_path`` does not exist.
        fitz.FileDataError: If the file is not a valid PDF.
    """
    doc = fitz.open(pdf_path)
    try:
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            text = page.get_text().strip()
            if len(text) > _TYPED_TEXT_THRESHOLD:
                logger.debug(
                    "Page %d has %d chars of selectable text — "
                    "treating PDF as typed",
                    page_num + 1,
                    len(text),
                )
                return False  # Found a typed page — conservative exit

        logger.info(
            "No page has >%d chars of selectable text — "
            "treating PDF as scanned",
            _TYPED_TEXT_THRESHOLD,
        )
        return True  # All pages appear scanned

    finally:
        doc.close()
