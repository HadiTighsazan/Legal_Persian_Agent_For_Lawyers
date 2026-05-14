"""
Tests for the table extraction utility.

Covers:
- :func:`~documents.utils.table_extractor._table_to_markdown`
- :func:`~documents.utils.table_extractor._table_to_semantic_text`
- :class:`~documents.utils.table_extractor.TableExtractor`
"""

from __future__ import annotations

import io
import tempfile
from unittest.mock import MagicMock, patch

from django.test import TestCase

from documents.utils.table_extractor import (
    ExtractedTable,
    TableExtractor,
    _table_to_markdown,
    _table_to_semantic_text,
)


# ---------------------------------------------------------------------------
# Tests for _table_to_markdown
# ---------------------------------------------------------------------------


class TableToMarkdownTest(TestCase):
    """Tests for the ``_table_to_markdown`` helper."""

    def test_empty_table(self) -> None:
        """Empty table returns empty string."""
        assert _table_to_markdown([]) == ""
        assert _table_to_markdown([[]]) == ""

    def test_single_row_header_only(self) -> None:
        """A single-row table produces only a header + separator (no data rows)."""
        table = [["نام", "خواهان"]]
        result = _table_to_markdown(table)
        expected = (
            "| نام | خواهان |\n"
            "| --- | ------ |"
        )
        assert result == expected, f"\nExpected:\n{expected}\nGot:\n{result}"

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
        assert result == expected, f"\nExpected:\n{expected}\nGot:\n{result}"

    def test_table_with_none_cells(self) -> None:
        """None cells are converted to empty strings."""
        table = [
            ["نام", "خواهان", "سن"],
            ["علی", None, "۳۰"],
        ]
        result = _table_to_markdown(table)
        # The empty cell (None → "") should appear as whitespace-only
        lines = result.split("\n")
        assert len(lines) == 3  # header + separator + data
        data_line = lines[2]
        assert "علی" in data_line
        assert "۳۰" in data_line
        # The middle cell should be empty (just padding spaces)
        cells = [c.strip() for c in data_line.split("|")[1:-1]]
        assert cells[0] == "علی"
        assert cells[1] == ""  # None converted to empty
        assert cells[2] == "۳۰"

    def test_table_with_empty_cells(self) -> None:
        """Empty string cells are handled gracefully."""
        table = [
            ["نام", "خواهان"],
            ["علی", ""],
        ]
        result = _table_to_markdown(table)
        lines = result.split("\n")
        assert len(lines) == 3  # header + separator + data
        data_line = lines[2]
        assert "علی" in data_line
        # The empty cell should appear as whitespace-only
        cells = [c.strip() for c in data_line.split("|")[1:-1]]
        assert cells[0] == "علی"
        assert cells[1] == ""  # empty string


# ---------------------------------------------------------------------------
# Tests for _table_to_semantic_text
# ---------------------------------------------------------------------------


class TableToSemanticTextTest(TestCase):
    """Tests for the ``_table_to_semantic_text`` helper."""

    def test_empty_table(self) -> None:
        """Empty table returns empty string."""
        assert _table_to_semantic_text([]) == ""
        assert _table_to_semantic_text([[]]) == ""

    def test_single_row_header_only(self) -> None:
        """A single-row table lists cells directly (no key-value pairs)."""
        table = [["نام", "خواهان"]]
        result = _table_to_semantic_text(table)
        assert result == "نام | خواهان"

    def test_basic_key_value_pairs(self) -> None:
        """Header-data rows produce key: value pairs."""
        table = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
        ]
        result = _table_to_semantic_text(table)
        assert result == "نام: علی | خواهان: احمدی"

    def test_multiple_rows(self) -> None:
        """Multiple data rows produce multiple lines."""
        table = [
            ["نام", "خواهان"],
            ["علی", "احمدی"],
            ["رضا", "محمدی"],
        ]
        result = _table_to_semantic_text(table)
        expected = "نام: علی | خواهان: احمدی\nنام: رضا | خواهان: محمدی"
        assert result == expected, f"\nExpected:\n{expected}\nGot:\n{result}"

    def test_table_with_none_cells(self) -> None:
        """None cells are skipped in key-value pairs."""
        table = [
            ["نام", "خواهان", "سن"],
            ["علی", None, "۳۰"],
        ]
        result = _table_to_semantic_text(table)
        # "خواهان" has None value, so it's skipped
        assert "خواهان:" not in result
        assert "نام: علی" in result
        assert "سن: ۳۰" in result

    def test_table_with_empty_header_cell(self) -> None:
        """Empty header cells cause that column to be skipped."""
        table = [
            ["نام", ""],
            ["علی", "احمدی"],
        ]
        result = _table_to_semantic_text(table)
        assert result == "نام: علی"

    def test_persian_legal_table(self) -> None:
        """Realistic Persian legal table."""
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
        assert result == expected, f"\nExpected:\n{expected}\nGot:\n{result}"


# ---------------------------------------------------------------------------
# Tests for ExtractedTable dataclass
# ---------------------------------------------------------------------------


class ExtractedTableTest(TestCase):
    """Tests for the ``ExtractedTable`` dataclass."""

    def test_dataclass_creation(self) -> None:
        """ExtractedTable can be created with all fields."""
        table = ExtractedTable(
            page=1,
            bbox=(0, 0, 100, 50),
            markdown="| a | b |\n| --- | --- |\n| 1 | 2 |",
            semantic_text="a: 1 | b: 2",
            raw_data=[["a", "b"], ["1", "2"]],
        )
        assert table.page == 1
        assert table.bbox == (0, 0, 100, 50)
        assert "a: 1" in table.semantic_text
        assert len(table.raw_data) == 2

    def test_dataclass_default_raw_data(self) -> None:
        """raw_data defaults to empty list."""
        table = ExtractedTable(
            page=1,
            bbox=(0, 0, 100, 50),
            markdown="",
            semantic_text="",
        )
        assert table.raw_data == []


# ---------------------------------------------------------------------------
# Tests for TableExtractor
# ---------------------------------------------------------------------------


class TableExtractorTest(TestCase):
    """Tests for the ``TableExtractor`` class."""

    def test_extract_tables_pdfplumber_not_installed(self) -> None:
        """When pdfplumber is not installed, returns empty list."""
        with patch.dict("sys.modules", {"pdfplumber": None}):
            # Re-import to clear any cached import
            from documents.utils.table_extractor import TableExtractor as TE

            extractor = TE()
            result = extractor.extract_tables(b"fake pdf bytes")
            assert result == []

    def test_extract_tables_pdfplumber_import_error(self) -> None:
        """When pdfplumber import fails, returns empty list."""
        # Simulate ImportError by patching the import inside the method
        original_import = __import__

        def _mock_import(name, *args, **kwargs):
            if name == "pdfplumber":
                raise ImportError("pdfplumber not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            from documents.utils.table_extractor import TableExtractor as TE

            extractor = TE()
            result = extractor.extract_tables(b"fake pdf bytes")
            assert result == []

    def test_extract_tables_pdf_open_failure(self) -> None:
        """When pdfplumber fails to open the PDF, returns empty list."""
        extractor = TableExtractor()
        result = extractor.extract_tables(b"not a valid pdf")
        assert result == []

    def test_min_rows_filter(self) -> None:
        """Tables with fewer than min_rows are filtered out."""
        # Mock a pdfplumber page that returns a single-row "table"
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
            assert result == [], (
                "Single-row table should be filtered out by min_rows=2"
            )

    def test_min_cols_filter(self) -> None:
        """Tables with fewer than min_cols are filtered out."""
        # Mock a pdfplumber page that returns a single-column "table"
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
            assert result == [], (
                "Single-column table should be filtered out by min_cols=2"
            )

    def test_successful_extraction(self) -> None:
        """A valid table is extracted with dual representation."""
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

            assert len(result) == 1
            table = result[0]

            assert table.page == 1
            assert table.bbox == (10, 20, 200, 100)
            assert "| نام | خواهان |" in table.markdown
            assert "| علی | احمدی  |" in table.markdown
            assert table.semantic_text == "نام: علی | خواهان: احمدی"
            assert table.raw_data == raw_data

    def test_multiple_pages(self) -> None:
        """Tables from multiple pages are all extracted."""
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

            assert len(result) == 2
            assert result[0].page == 1
            assert result[1].page == 2

    def test_find_tables_failure_on_page(self) -> None:
        """If find_tables() fails on one page, other pages still work."""
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

            # Page 1 fails, but page 2 should still produce a table
            assert len(result) == 1
            assert result[0].page == 2


# ---------------------------------------------------------------------------
# Tests for _prepare_embedding_content (integration with embedding service)
# ---------------------------------------------------------------------------


class PrepareEmbeddingContentTest(TestCase):
    """Tests for the ``_prepare_embedding_content`` function."""

    def test_no_tables(self) -> None:
        """When chunk has no tables, content is returned as-is."""
        from documents.services.embedding_service import _prepare_embedding_content

        chunk = MagicMock()
        chunk.content = "این یک متن ساده است."
        chunk.metadata = {}

        result = _prepare_embedding_content(chunk)
        assert result == "این یک متن ساده است."

    def test_with_tables(self) -> None:
        """When chunk has tables, semantic text is appended."""
        from documents.services.embedding_service import _prepare_embedding_content

        chunk = MagicMock()
        chunk.content = "متن اصلی"
        chunk.metadata = {
            "tables": [
                {
                    "page": 1,
                    "markdown": "| نام | خواهان |\n| --- | --- |\n| علی | احمدی |",
                    "semantic_text": "نام: علی | خواهان: احمدی",
                }
            ]
        }

        result = _prepare_embedding_content(chunk)
        assert "متن اصلی" in result
        assert "نام: علی | خواهان: احمدی" in result
        # Markdown should NOT be in the embedding content
        assert "| نام | خواهان |" not in result

    def test_multiple_tables(self) -> None:
        """Multiple tables are all appended."""
        from documents.services.embedding_service import _prepare_embedding_content

        chunk = MagicMock()
        chunk.content = "متن اصلی"
        chunk.metadata = {
            "tables": [
                {
                    "page": 1,
                    "semantic_text": "نام: علی | خواهان: احمدی",
                },
                {
                    "page": 1,
                    "semantic_text": "ردیف: ۱ | مبلغ: ۱۰۰۰۰۰",
                },
            ]
        }

        result = _prepare_embedding_content(chunk)
        assert "نام: علی | خواهان: احمدی" in result
        assert "ردیف: ۱ | مبلغ: ۱۰۰۰۰۰" in result

    def test_empty_semantic_text_skipped(self) -> None:
        """Tables with empty semantic_text are not appended."""
        from documents.services.embedding_service import _prepare_embedding_content

        chunk = MagicMock()
        chunk.content = "متن اصلی"
        chunk.metadata = {
            "tables": [
                {
                    "page": 1,
                    "semantic_text": "",
                },
                {
                    "page": 1,
                    "semantic_text": "نام: علی | خواهان: احمدی",
                },
            ]
        }

        result = _prepare_embedding_content(chunk)
        assert "متن اصلی" in result
        assert "نام: علی | خواهان: احمدی" in result

    def test_metadata_is_none(self) -> None:
        """When metadata is None, content is returned as-is."""
        from documents.services.embedding_service import _prepare_embedding_content

        chunk = MagicMock()
        chunk.content = "متن ساده"
        chunk.metadata = None

        result = _prepare_embedding_content(chunk)
        assert result == "متن ساده"
