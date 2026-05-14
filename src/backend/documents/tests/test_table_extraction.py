"""
Tests for the table extraction utility.

Covers:
- pdfplumber table detection
- Markdown table conversion
- Semantic text conversion
- Integration with extraction pipeline
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from django.test import TestCase

from documents.utils.table_extractor import (
    ExtractedTable,
    TableExtractor,
    _table_to_markdown,
    _table_to_semantic_text,
)


# ===========================================================================
# 6.3.1 — pdfplumber Table Detection
# ===========================================================================


class TestPdfplumberTableDetection(TestCase):
    """Tests for pdfplumber-based table detection in :class:`TableExtractor`."""

    def test_detect_simple_table(self) -> None:
        """A simple 2x2 table is detected and extracted."""
        raw_data = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
        ]

        mock_table = MagicMock()
        mock_table.bbox = (10, 20, 200, 100)
        mock_table.extract.return_value = raw_data

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 1)
            table = result[0]
            self.assertEqual(table.page, 1)
            self.assertEqual(table.bbox, (10, 20, 200, 100))
            self.assertEqual(table.raw_data, raw_data)

    def test_detect_multiple_tables_on_same_page(self) -> None:
        """Multiple tables on the same page are all detected."""
        raw_data_1 = [["a", "b"], ["1", "2"]]
        raw_data_2 = [["c", "d"], ["3", "4"]]

        mock_table1 = MagicMock()
        mock_table1.bbox = (0, 0, 100, 50)
        mock_table1.extract.return_value = raw_data_1

        mock_table2 = MagicMock()
        mock_table2.bbox = (0, 60, 100, 110)
        mock_table2.extract.return_value = raw_data_2

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table1, mock_table2]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 2)
            self.assertEqual(result[0].page, 1)
            self.assertEqual(result[1].page, 1)

    def test_detect_tables_across_multiple_pages(self) -> None:
        """Tables on different pages are all detected with correct page numbers."""
        raw_data_page1 = [["a", "b"], ["1", "2"]]
        raw_data_page2 = [["c", "d"], ["3", "4"]]

        mock_table1 = MagicMock()
        mock_table1.bbox = (0, 0, 100, 50)
        mock_table1.extract.return_value = raw_data_page1

        mock_table2 = MagicMock()
        mock_table2.bbox = (0, 0, 100, 50)
        mock_table2.extract.return_value = raw_data_page2

        mock_page1 = MagicMock()
        mock_page1.find_tables.return_value = [mock_table1]

        mock_page2 = MagicMock()
        mock_page2.find_tables.return_value = [mock_table2]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 2)
            self.assertEqual(result[0].page, 1)
            self.assertEqual(result[1].page, 2)

    def test_no_tables_on_page(self) -> None:
        """A page with no tables returns an empty list."""
        mock_page = MagicMock()
        mock_page.find_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(result, [])

    def test_find_tables_exception_on_page(self) -> None:
        """If find_tables() raises an exception, other pages still work."""
        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = [["a", "b"], ["1", "2"]]

        mock_page1 = MagicMock()
        mock_page1.find_tables.side_effect = Exception("Page error")

        mock_page2 = MagicMock()
        mock_page2.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].page, 2)

    def test_min_rows_filter_applied(self) -> None:
        """Tables with fewer than min_rows are filtered out."""
        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = [["header1", "header2"]]

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(
                result,
                [],
                "Single-row table should be filtered out by min_rows=2",
            )

    def test_min_cols_filter_applied(self) -> None:
        """Tables with fewer than min_cols are filtered out."""
        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = [["header"], ["data"]]

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(
                result,
                [],
                "Single-column table should be filtered out by min_cols=2",
            )

    def test_custom_min_rows_and_cols(self) -> None:
        """Custom min_rows and min_cols parameters are respected."""
        # A 3x3 table — should pass default filters
        raw_data = [
            ["a", "b", "c"],
            ["1", "2", "3"],
            ["x", "y", "z"],
        ]

        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = raw_data

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            # With min_rows=4, this 3-row table should be filtered out
            result = extractor.extract_tables(
                b"fake pdf bytes", min_rows=4, min_cols=2
            )
            self.assertEqual(result, [])

            # With min_cols=4, this 3-col table should be filtered out
            result2 = extractor.extract_tables(
                b"fake pdf bytes", min_rows=2, min_cols=4
            )
            self.assertEqual(result2, [])

    def test_pdfplumber_not_installed(self) -> None:
        """When pdfplumber is not installed, returns empty list."""
        with patch.dict("sys.modules", {"pdfplumber": None}):
            from documents.utils.table_extractor import TableExtractor as TE

            extractor = TE()
            result = extractor.extract_tables(b"fake pdf bytes")
            self.assertEqual(result, [])

    def test_pdf_open_failure(self) -> None:
        """When pdfplumber fails to open the PDF, returns empty list."""
        extractor = TableExtractor()
        result = extractor.extract_tables(b"not a valid pdf")
        self.assertEqual(result, [])


# ===========================================================================
# 6.3.2 — Markdown Table Conversion
# ===========================================================================


class TestMarkdownTableConversion(TestCase):
    """Tests for :func:`_table_to_markdown`."""

    def test_empty_table(self) -> None:
        """Empty table returns empty string."""
        self.assertEqual(_table_to_markdown([]), "")
        self.assertEqual(_table_to_markdown([[]]), "")

    def test_single_row_header_only(self) -> None:
        """A single-row table produces header + separator (no data rows)."""
        table = [["نام", "خواهان"]]
        result = _table_to_markdown(table)
        expected = (
            "| نام | خواهان |\n"
            "| --- | ------ |"
        )
        self.assertEqual(result, expected)

    def test_basic_table(self) -> None:
        """A basic table with header and data rows."""
        table = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
            ["رضا", "محمدی"],
        ]
        result = _table_to_markdown(table)
        expected = (
            "| نام | خواهان |\n"
            "| --- | ------ |\n"
            "| علی | احمدی  |\n"
            "| رضا | محمدی  |"
        )
        self.assertEqual(result, expected)

    def test_table_with_none_cells(self) -> None:
        """None cells are converted to empty strings."""
        table = [
            ["نام", "خواهان", "سن"],
            ["علی", None, "۳۰"],
        ]
        result = _table_to_markdown(table)
        lines = result.split("\n")
        self.assertEqual(len(lines), 3)  # header + separator + data
        data_line = lines[2]
        cells = [c.strip() for c in data_line.split("|")[1:-1]]
        self.assertEqual(cells[0], "علی")
        self.assertEqual(cells[1], "")  # None converted to empty
        self.assertEqual(cells[2], "۳۰")

    def test_table_with_empty_cells(self) -> None:
        """Empty string cells are handled gracefully."""
        table = [
            ["نام", "خواهان"],
            ["علی", ""],
        ]
        result = _table_to_markdown(table)
        lines = result.split("\n")
        self.assertEqual(len(lines), 3)
        data_line = lines[2]
        cells = [c.strip() for c in data_line.split("|")[1:-1]]
        self.assertEqual(cells[0], "علی")
        self.assertEqual(cells[1], "")

    def test_table_with_wide_columns(self) -> None:
        """Columns with wide content are properly aligned."""
        table = [
            ["ردیف", "نام", "نام خانوادگی", "سمت"],
            ["۱", "علی", "احمدی", "خواهان"],
            ["۲", "مریم", "حسینی", "خوانده"],
        ]
        result = _table_to_markdown(table)
        lines = result.split("\n")
        self.assertEqual(len(lines), 4)  # header + separator + 2 data rows
        # Verify separator has correct dashes for each column width
        sep = lines[1]
        self.assertIn("---", sep)  # "ردیف" → width 4 → "---" (min 3)
        self.assertIn("------", sep)  # "نام خانوادگی" → width 12 → 12 dashes

    def test_table_with_numbers(self) -> None:
        """Tables with numeric data are formatted correctly."""
        table = [
            ["ردیف", "مبلغ (ریال)"],
            ["۱", "۱۰۰۰۰۰"],
            ["۲", "۲۰۰۰۰۰"],
        ]
        result = _table_to_markdown(table)
        self.assertIn("۱۰۰۰۰۰", result)
        self.assertIn("۲۰۰۰۰۰", result)

    def test_table_with_mixed_column_count(self) -> None:
        """Rows with fewer columns than the header are handled."""
        table = [
            ["نام", "خواهان", "سن"],
            ["علی", "احمدی"],  # Missing "سن"
        ]
        result = _table_to_markdown(table)
        # Should not crash; missing cell is treated as empty
        self.assertIn("علی", result)
        self.assertIn("احمدی", result)

    def test_persian_legal_table_markdown(self) -> None:
        """Realistic Persian legal table in Markdown format."""
        table = [
            ["ردیف", "نام", "نام خانوادگی", "سمت"],
            ["۱", "علی", "احمدی", "خواهان"],
            ["۲", "مریم", "حسینی", "خوانده"],
        ]
        result = _table_to_markdown(table)
        # Column widths: "ردیف"=4, "نام"=4, "نام خانوادگی"=12, "سمت"=4
        # Min width 3 → widths: [4, 4, 12, 4]
        # Each cell is left-justified to its column width
        expected = (
            "| ردیف | نام  | نام خانوادگی | سمت    |\n"
            "| ---- | ---- | ------------ | ------ |\n"
            "| ۱    | علی  | احمدی        | خواهان |\n"
            "| ۲    | مریم | حسینی        | خوانده |"
        )
        self.assertEqual(result, expected)


# ===========================================================================
# 6.3.3 — Semantic Text Conversion
# ===========================================================================


class TestSemanticTextConversion(TestCase):
    """Tests for :func:`_table_to_semantic_text`."""

    def test_empty_table(self) -> None:
        """Empty table returns empty string."""
        self.assertEqual(_table_to_semantic_text([]), "")
        self.assertEqual(_table_to_semantic_text([[]]), "")

    def test_single_row_header_only(self) -> None:
        """A single-row table lists cells directly (no key-value pairs)."""
        table = [["نام", "خواهان"]]
        result = _table_to_semantic_text(table)
        self.assertEqual(result, "نام | خواهان")

    def test_basic_key_value_pairs(self) -> None:
        """Header-data rows produce key: value pairs."""
        table = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
        ]
        result = _table_to_semantic_text(table)
        self.assertEqual(result, "نام: علی | خواهان: احمدی")

    def test_multiple_rows(self) -> None:
        """Multiple data rows produce multiple lines."""
        table = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
            ["رضا", "محمدی"],
        ]
        result = _table_to_semantic_text(table)
        expected = "نام: علی | خواهان: احمدی\nنام: رضا | خواهان: محمدی"
        self.assertEqual(result, expected)

    def test_table_with_none_cells(self) -> None:
        """None cells are skipped in key-value pairs."""
        table = [
            ["نام", "خواهان", "سن"],
            ["علی", None, "۳۰"],
        ]
        result = _table_to_semantic_text(table)
        self.assertNotIn("خواهان:", result)
        self.assertIn("نام: علی", result)
        self.assertIn("سن: ۳۰", result)

    def test_table_with_empty_header_cell(self) -> None:
        """Empty header cells cause that column to be skipped."""
        table = [
            ["نام", ""],
            ["علی", "احمدی"],
        ]
        result = _table_to_semantic_text(table)
        self.assertEqual(result, "نام: علی")

    def test_table_with_empty_value_cell(self) -> None:
        """Empty value cells are skipped."""
        table = [
            ["نام", "خواهان"],
            ["علی", ""],
        ]
        result = _table_to_semantic_text(table)
        self.assertEqual(result, "نام: علی")

    def test_table_with_all_empty_values(self) -> None:
        """All empty values produce empty string."""
        table = [
            ["نام", "خواهان"],
            ["", ""],
        ]
        result = _table_to_semantic_text(table)
        self.assertEqual(result, "")

    def test_persian_legal_table_semantic(self) -> None:
        """Realistic Persian legal table in semantic format."""
        table = [
            ["ردیف", "نام", "نام خانوادگی", "سمت"],
            ["۱", "علی", "احمدی", "خواهان"],
            ["۲", "مریم", "حسینی", "خوانده"],
        ]
        result = _table_to_semantic_text(table)
        expected = (
            "ردیف: ۱ | نام: علی | نام خانوادگی: احمدی | سمت: خواهان\n"
            "ردیف: ۲ | نام: مریم | نام خانوادگی: حسینی | سمت: خوانده"
        )
        self.assertEqual(result, expected)

    def test_semantic_text_with_numbers(self) -> None:
        """Numeric data in semantic format."""
        table = [
            ["ردیف", "مبلغ (ریال)", "تاریخ"],
            ["۱", "۱۰۰۰۰۰", "۱۳۷۶/۰۱/۱۵"],
            ["۲", "۲۰۰۰۰۰", "۱۳۷۶/۰۲/۲۰"],
        ]
        result = _table_to_semantic_text(table)
        self.assertIn("ردیف: ۱", result)
        self.assertIn("مبلغ (ریال): ۱۰۰۰۰۰", result)
        self.assertIn("تاریخ: ۱۳۷۶/۰۱/۱۵", result)

    def test_semantic_text_single_column(self) -> None:
        """Single-column table (headerless) lists cells directly."""
        table = [["مورد"]]
        result = _table_to_semantic_text(table)
        self.assertEqual(result, "مورد")

    def test_semantic_text_headerless_multi_row(self) -> None:
        """Multi-row table with single column lists cells."""
        table = [
            ["مورد اول"],
            ["مورد دوم"],
        ]
        result = _table_to_semantic_text(table)
        # First row is treated as header, second as data
        # "مورد اول" is the header, "مورد دوم" is the value
        self.assertIn("مورد اول", result)
        self.assertIn("مورد دوم", result)


# ===========================================================================
# 6.3.4 — Integration with Extraction Pipeline
# ===========================================================================


class TestTableExtractionPipeline(TestCase):
    """Integration tests for the full table extraction pipeline."""

    def test_full_pipeline_single_table(self) -> None:
        """Full pipeline: PDF bytes → extracted table with dual representation."""
        raw_data = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
        ]

        mock_table = MagicMock()
        mock_table.bbox = (10, 20, 200, 100)
        mock_table.extract.return_value = raw_data

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 1)
            table = result[0]

            # Verify all fields are populated
            self.assertEqual(table.page, 1)
            self.assertEqual(table.bbox, (10, 20, 200, 100))
            self.assertIsInstance(table.markdown, str)
            self.assertIsInstance(table.semantic_text, str)
            self.assertEqual(table.raw_data, raw_data)

            # Verify dual representation
            self.assertIn("| نام | خواهان |", table.markdown)
            self.assertEqual(
                table.semantic_text,
                "نام: علی | خواهان: احمدی",
            )

    def test_full_pipeline_multiple_tables(self) -> None:
        """Full pipeline with multiple tables across pages."""
        raw_data_1 = [["a", "b"], ["1", "2"]]
        raw_data_2 = [["c", "d"], ["3", "4"]]

        mock_table1 = MagicMock()
        mock_table1.bbox = (0, 0, 100, 50)
        mock_table1.extract.return_value = raw_data_1

        mock_table2 = MagicMock()
        mock_table2.bbox = (0, 60, 100, 110)
        mock_table2.extract.return_value = raw_data_2

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table1, mock_table2]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 2)
            # Both tables should have valid dual representation
            for table in result:
                self.assertTrue(table.markdown)
                self.assertTrue(table.semantic_text)
                self.assertTrue(table.raw_data)

    def test_pipeline_with_no_tables(self) -> None:
        """Pipeline with no tables returns empty list."""
        mock_page = MagicMock()
        mock_page.find_tables.return_value = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")
            self.assertEqual(result, [])

    def test_pipeline_with_empty_pdf(self) -> None:
        """Pipeline with empty PDF (no pages) returns empty list."""
        mock_pdf = MagicMock()
        mock_pdf.pages = []
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")
            self.assertEqual(result, [])

    def test_pipeline_preserves_raw_data(self) -> None:
        """Raw data is preserved in the ExtractedTable for debugging."""
        raw_data = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
        ]

        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = raw_data

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].raw_data, raw_data)
            # raw_data is the same reference (not deep-copied)
            self.assertIs(result[0].raw_data, raw_data)

    def test_pipeline_with_persian_legal_table(self) -> None:
        """Full pipeline with a realistic Persian legal table."""
        raw_data = [
            ["ردیف", "نام", "نام خانوادگی", "سمت", "مبلغ (ریال)"],
            ["۱", "علی", "احمدی", "خواهان", "۱۰۰۰۰۰"],
            ["۲", "مریم", "حسینی", "خوانده", "۲۰۰۰۰۰"],
            ["۳", "رضا", "محمدی", "وکیل", "۱۵۰۰۰۰"],
        ]

        mock_table = MagicMock()
        mock_table.bbox = (20, 30, 500, 200)
        mock_table.extract.return_value = raw_data

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")

            self.assertEqual(len(result), 1)
            table = result[0]

            # Verify Markdown representation
            self.assertIn("ردیف", table.markdown)
            self.assertIn("مبلغ (ریال)", table.markdown)
            self.assertIn("۱۰۰۰۰۰", table.markdown)

            # Verify semantic text representation
            self.assertIn("ردیف: ۱", table.semantic_text)
            self.assertIn("نام: علی", table.semantic_text)
            self.assertIn("مبلغ (ریال): ۱۰۰۰۰۰", table.semantic_text)

            # Verify page and bbox
            self.assertEqual(table.page, 1)
            self.assertEqual(table.bbox, (20, 30, 500, 200))

    def test_pipeline_graceful_degradation(self) -> None:
        """Pipeline degrades gracefully when pdfplumber fails."""
        # Test with completely invalid bytes
        extractor = TableExtractor()
        result = extractor.extract_tables(b"\x00\x01\x02\x03")
        self.assertEqual(result, [])

    def test_pipeline_with_table_containing_only_empty_cells(self) -> None:
        """Table with all empty cells produces markdown but empty semantic_text."""
        mock_table = MagicMock()
        mock_table.bbox = (0, 0, 100, 50)
        mock_table.extract.return_value = [["", ""], ["", ""]]

        mock_page = MagicMock()
        mock_page.find_tables.return_value = [mock_table]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__.return_value = mock_pdf

        with patch("pdfplumber.open", return_value=mock_pdf):
            extractor = TableExtractor()
            result = extractor.extract_tables(b"fake pdf bytes")
            # Empty cells produce a markdown table with empty cells
            # (|     |     |) but semantic_text is empty.
            # The filter checks if BOTH markdown AND semantic_text are empty.
            # Since markdown is non-empty, the table passes through.
            self.assertEqual(len(result), 1)
            self.assertTrue(result[0].markdown)
            self.assertEqual(result[0].semantic_text, "")


# ===========================================================================
# 6.3.5 — ExtractedTable Dataclass
# ===========================================================================


class TestExtractedTableDataclass(TestCase):
    """Tests for the :class:`ExtractedTable` dataclass."""

    def test_dataclass_creation(self) -> None:
        """ExtractedTable can be created with all fields."""
        table = ExtractedTable(
            page=1,
            bbox=(0, 0, 100, 50),
            markdown="| a | b |\n| --- | --- |\n| 1 | 2 |",
            semantic_text="a: 1 | b: 2",
            raw_data=[["a", "b"], ["1", "2"]],
        )
        self.assertEqual(table.page, 1)
        self.assertEqual(table.bbox, (0, 0, 100, 50))
        self.assertIn("a: 1", table.semantic_text)
        self.assertEqual(len(table.raw_data), 2)

    def test_dataclass_default_raw_data(self) -> None:
        """raw_data defaults to empty list."""
        table = ExtractedTable(
            page=1,
            bbox=(0, 0, 100, 50),
            markdown="",
            semantic_text="",
        )
        self.assertEqual(table.raw_data, [])

    def test_dataclass_repr(self) -> None:
        """ExtractedTable has a useful repr."""
        table = ExtractedTable(
            page=1,
            bbox=(0, 0, 100, 50),
            markdown="| a | b |",
            semantic_text="a: 1",
        )
        repr_str = repr(table)
        self.assertIn("ExtractedTable", repr_str)
        self.assertIn("page=1", repr_str)
