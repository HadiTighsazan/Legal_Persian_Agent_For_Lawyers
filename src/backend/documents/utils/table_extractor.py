"""
Table extraction utility for Persian legal PDFs.

Provides the :class:`TableExtractor` class that uses **PyMuPDF** (``fitz``)
built-in :meth:`~fitz.Page.find_tables` to detect tables on PDF pages and
produce a **dual representation**:

1. **Markdown format** — For human readability and LLM context.
2. **Normalized semantic text** — For embedding (key-value pairs), avoiding
   the token noise that raw Markdown tables create in vector representations.

.. note::

   This module previously used ``pdfplumber`` for table detection. It was
   migrated to PyMuPDF's native :meth:`~fitz.Page.find_tables` in the Phase 1
   refactoring to eliminate the ``pdfplumber`` dependency. The output format
   (the :class:`ExtractedTable` dataclass) is identical to the old version.

Usage::

    from documents.utils.table_extractor import TableExtractor

    extractor = TableExtractor()
    tables = extractor.extract_tables(pdf_bytes)
    for table in tables:
        print(table.markdown)       # Markdown table
        print(table.semantic_text)  # Key-value pairs for embedding
        print(table.page)           # Page number
        print(table.bbox)           # Bounding box (x0, y0, x1, y1)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExtractedTable:
    """A table extracted from a PDF page.

    Attributes:
        page: The 1-based page number this table was found on.
        bbox: Bounding box ``(x0, y0, x1, y1)`` in PDF coordinate space.
        markdown: Markdown representation of the table for display/LLM context.
        semantic_text: Normalized key-value pair text for embedding (avoids
            Markdown token noise).
        raw_data: The raw table data as a list of lists (rows of cells).
            Each cell is ``str | None``. Useful for debugging or custom
            processing.
    """

    page: int
    bbox: Tuple[float, float, float, float]
    markdown: str
    semantic_text: str
    raw_data: List[List[Optional[str]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_to_markdown(table: list[list[str | None]]) -> str:
    """Convert a table (list of rows) to Markdown format.

    Produces a GitHub-flavoured Markdown table with a header separator row.
    Empty cells are represented as empty strings.

    Args:
        table: A list of rows, where each row is a list of cell values
            (``str`` or ``None``).

    Returns:
        A Markdown-formatted table string, or an empty string if the table
        has no rows.
    """
    if not table or not table[0]:
        return ""

    # Convert None to empty string for consistent rendering
    rows: list[list[str]] = []
    for row in table:
        rows.append([(cell or "").strip() for cell in row])

    # Determine column widths (max cell width per column)
    col_widths: list[int] = []
    for col_idx in range(len(rows[0])):
        max_w = 0
        for row in rows:
            if col_idx < len(row):
                max_w = max(max_w, len(row[col_idx]))
        col_widths.append(max(max_w, 3))  # Minimum width of 3 for alignment

    lines: list[str] = []

    # Header row
    header_cells = []
    for i, cell in enumerate(rows[0]):
        w = col_widths[i] if i < len(col_widths) else 3
        header_cells.append(cell.ljust(w))
    lines.append("| " + " | ".join(header_cells) + " |")

    # Separator row
    sep_cells = []
    for w in col_widths:
        sep_cells.append("-" * w)
    lines.append("| " + " | ".join(sep_cells) + " |")

    # Data rows
    for row in rows[1:]:
        data_cells = []
        for i, cell in enumerate(row):
            w = col_widths[i] if i < len(col_widths) else 3
            data_cells.append(cell.ljust(w))
        lines.append("| " + " | ".join(data_cells) + " |")

    return "\n".join(lines)


def _table_to_semantic_text(table: list[list[str | None]]) -> str:
    """Convert a table to normalized semantic text for embedding.

    Instead of Markdown (which creates token noise in vector representations),
    produce natural language key-value pairs.

    Example::

        | نام | خواهان |
        | --- | --- |
        | علی | احمدی |

    Becomes::

        نام: علی | خواهان: احمدی

    If the table has no header row (single row), each cell is treated as
    a standalone item::

        سلول ۱ | سلول ۲ | سلول ۳

    Args:
        table: A list of rows, where each row is a list of cell values
            (``str`` or ``None``).

    Returns:
        A string of pipe-separated key-value pairs, one row per line.
        Returns an empty string if the table is empty.
    """
    if not table or not table[0]:
        return ""

    header = table[0]
    rows: list[str] = []

    if len(table) == 1:
        # Single row — treat as headerless table, list cells directly
        cells = [cell.strip() for cell in header if cell and cell.strip()]
        if cells:
            return " | ".join(cells)
        return ""

    for row in table[1:]:
        pairs: list[str] = []
        for i, cell in enumerate(row):
            if i < len(header) and header[i] and cell:
                key = header[i].strip()
                value = cell.strip()
                if key and value:
                    pairs.append(f"{key}: {value}")
        if pairs:
            rows.append(" | ".join(pairs))

    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class TableExtractor:
    """Extract tables from PDF bytes using **PyMuPDF** ``page.find_tables()``.

    Provides dual representation (Markdown + semantic text) for each detected
    table, enabling clean storage and LLM-friendly display while avoiding
    embedding pollution from Markdown syntax tokens.

    The extractor uses PyMuPDF's built-in :meth:`~fitz.Page.find_tables` which
    provides bounding-box-level table detection. Each detected table is
    converted to both representations.

    .. note::

       This class previously used ``pdfplumber``. It was migrated to PyMuPDF
       in the Phase 1 refactoring. The :class:`ExtractedTable` output format
       is unchanged.

    Usage::

        extractor = TableExtractor()
        tables = extractor.extract_tables(pdf_bytes)
        for t in tables:
            print(t.markdown)
            print(t.semantic_text)
    """

    # Minimum number of rows for a detected table to be considered valid.
    # PyMuPDF can sometimes detect text blocks as 1-row "tables".
    _MIN_TABLE_ROWS: int = 2

    # Minimum number of columns for a detected table.
    _MIN_TABLE_COLS: int = 2

    def extract_tables(
        self,
        pdf_bytes: bytes,
        min_rows: int | None = None,
        min_cols: int | None = None,
    ) -> list[ExtractedTable]:
        """Extract all tables from a PDF.

        Iterates over every page, runs PyMuPDF's :meth:`~fitz.Page.find_tables`,
        and converts each detected table to dual representation.

        Args:
            pdf_bytes: Raw PDF file bytes.
            min_rows: Minimum number of rows (including header) for a table
                to be included. Defaults to :attr:`_MIN_TABLE_ROWS` (2).
            min_cols: Minimum number of columns for a table to be included.
                Defaults to :attr:`_MIN_TABLE_COLS` (2).

        Returns:
            A list of :class:`ExtractedTable` instances, one per detected
            table across all pages. Returns an empty list if no tables are
            found or if the PDF cannot be opened.
        """
        min_rows = min_rows or self._MIN_TABLE_ROWS
        min_cols = min_cols or self._MIN_TABLE_COLS

        extracted: list[ExtractedTable] = []

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            logger.warning(
                "TableExtractor: Failed to open PDF: %s",
                e,
            )
            return []

        try:
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                page_tables = self._extract_tables_from_page(
                    page=page,
                    page_num=page_num + 1,  # 1-based
                    min_rows=min_rows,
                    min_cols=min_cols,
                )
                extracted.extend(page_tables)
        except Exception as e:
            logger.warning(
                "Failed to extract tables from PDF: %s",
                e,
                exc_info=True,
            )
            return []
        finally:
            doc.close()

        logger.debug(
            "TableExtractor: extracted %d table(s) from PDF",
            len(extracted),
        )
        return extracted

    def _extract_tables_from_page(
        self,
        page: fitz.Page,
        page_num: int,
        min_rows: int,
        min_cols: int,
    ) -> list[ExtractedTable]:
        """Extract tables from a single PyMuPDF page.

        Args:
            page: A ``fitz.Page`` instance.
            page_num: The 1-based page number.
            min_rows: Minimum rows for a valid table.
            min_cols: Minimum columns for a valid table.

        Returns:
            List of :class:`ExtractedTable` instances for this page.
        """
        tables: list[ExtractedTable] = []

        try:
            found = page.find_tables()
        except Exception as e:
            logger.warning(
                "PyMuPDF find_tables() failed on page %d: %s",
                page_num,
                e,
            )
            return []

        for pymupdf_table in found:
            raw_data = pymupdf_table.extract()

            # Filter out tables that are too small (likely false positives)
            if not raw_data or len(raw_data) < min_rows:
                continue

            # Check column count
            if not raw_data[0] or len(raw_data[0]) < min_cols:
                continue

            # Get bounding box — PyMuPDF returns Rect (x0, y0, x1, y1)
            bbox = pymupdf_table.bbox

            # Generate dual representation
            markdown = _table_to_markdown(raw_data)
            semantic_text = _table_to_semantic_text(raw_data)

            if not markdown and not semantic_text:
                continue

            tables.append(
                ExtractedTable(
                    page=page_num,
                    bbox=bbox,
                    markdown=markdown,
                    semantic_text=semantic_text,
                    raw_data=raw_data,
                )
            )

        return tables
