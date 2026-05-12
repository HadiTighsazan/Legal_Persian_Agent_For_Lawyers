"""
Tests for the ``import_chunked_data`` management command.

Tests cover:
- Format A ingestion (legislation — object with ``chunks`` array)
- Format B ingestion (precedent — flat array with ``hub_type`` in metadata)
- Format C ingestion (advisory — flat array, hub_type from folder)
- Folder-to-hub mapping (all 3 folder names)
- Hub type normalisation (``"precedent"`` → ``"judicial_precedent"``)
- Dry-run mode (no DB writes)
- Idempotency (running twice does not create duplicates)
- Transactional rollback on failure
- Missing ``text`` field validation
- Error handling (invalid JSON, unknown folder names)
- Embedding generation integration

All external dependencies (``batch_generate_embeddings``) are mocked using
``unittest.mock.patch``.
"""

from __future__ import annotations

import json
import os
import tempfile
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from documents.management.commands.import_chunked_data import (
    Command,
    FOLDER_HUB_MAP,
    HUB_TYPE_ALIASES,
    ImportStats,
)
from documents.models import Document, DocumentChunk
from users.models import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMBEDDING_DIM: int = 1024
"""Standard embedding dimension (bge-m3)."""


def _make_embedding(dim: int = EMBEDDING_DIM) -> list[float]:
    """Generate a mock embedding vector of the given dimension."""
    return [0.1] * dim


def _make_format_a_json(
    source_file: str = "قانون_مجازات_اسلامی.json",
    total_chunks: int = 2,
    hub_type: str = "legislation",
    chunk_id_prefix: str = "madde",
    source_name: str | None = None,
) -> str:
    """Return a valid Format A JSON string (legislation-style).

    Args:
        source_file: The source file name.
        total_chunks: Number of chunks to generate.
        hub_type: The hub type for metadata.
        chunk_id_prefix: Prefix for chunk_id values (used to avoid
            idempotency conflicts across test cases).
        source_name: Override for the metadata ``source`` field. If not
            provided, uses the default ``"قانون مجازات اسلامي"``.
    """
    if source_name is None:
        source_name = "قانون مجازات اسلامي"
    chunks = [
        {
            "chunk_id": f"{chunk_id_prefix}_{i+1}",
            "madde_number": i + 1,
            "madde_raw": f"ماده {i+1}",
            "text": f"متن ماده {i+1} برای تست.",
            "metadata": {
                "source": source_name,
                "hub_type": hub_type,
                "summary": f"خلاصه ماده {i+1}",
                "approval_authority": "مجلس شورای اسلامی",
                "approval_date": "1392/02/01",
                "status": "معتبر",
                "kitab": "كتاب اول ـ كليات",
                "bakhsh": "بخش اول ـ مواد عمومي",
                "fasl": "فصل اول ـ تعاريف",
                "char_count": 164,
                "line_count": 1,
            },
        }
        for i in range(total_chunks)
    ]
    return json.dumps(
        {
            "source_file": source_file,
            "total_chunks": total_chunks,
            "chunks": chunks,
        },
        ensure_ascii=False,
    )


def _make_format_b_json(
    hub_type: str = "precedent",
    num_chunks: int = 2,
) -> str:
    """Return a valid Format B JSON string (precedent-style flat array)."""
    chunks = [
        {
            "text": f"رای شماره {i+1}",
            "chunk_type": "header" if i == 0 else "body",
            "section_name": None if i == 0 else f"بخش {i}",
            "full_title": "رای وحدت رویه شماره ۱",
            "metadata": {
                "judgment_number": f"14033139000301810{i}",
                "issue_date": "1403/12/14",
                "court": "هیات عمومی دیوان عدالت اداری",
                "url": f"https://example.com/ruling/{i}",
                "hub_type": hub_type,
            },
        }
        for i in range(num_chunks)
    ]
    return json.dumps(chunks, ensure_ascii=False)


def _make_format_c_json(num_chunks: int = 2) -> str:
    """Return a valid Format C JSON string (advisory-style flat array)."""
    chunks = [
        {
            "chunk_id": f"7/1403/87{8}_metadata" if i == 0 else f"7/1403/87{8}_question",
            "opinion_number": f"7/1403/87{8}",
            "issue_date": "1404/02/23",
            "source_type": "اداره حقوقی",
            "chunk_type": "metadata" if i == 0 else "question",
            "position": i + 1,
            "text": f"نظریه مشورتی شماره {i+1}",
            "url": f"https://example.com/opinion/{i}",
            "parent_title": "نظریه مشورتی ۷/۱۴۰۳/۸۷۸",
            "record_index": i,
        }
        for i in range(num_chunks)
    ]
    return json.dumps(chunks, ensure_ascii=False)


def _write_temp_json(content: str) -> str:
    """Write content to a temp file and return the path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


def _create_temp_data_dir(
    folder_name: str,
    json_contents: list[tuple[str, str]],
) -> str:
    """Create a temporary data directory with a subfolder and JSON files.

    Args:
        folder_name: The subdirectory name (e.g., ``"هاب قوانین مصوب"``).
        json_contents: List of ``(filename, json_string)`` tuples.

    Returns:
        The path to the temporary data directory.
    """
    tmp_dir = tempfile.mkdtemp()
    sub_dir = os.path.join(tmp_dir, folder_name)
    os.makedirs(sub_dir, exist_ok=True)
    for fname, content in json_contents:
        fpath = os.path.join(sub_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
    return tmp_dir


# ---------------------------------------------------------------------------
# ImportStatsTests
# ---------------------------------------------------------------------------


class ImportStatsTests(TestCase):
    """Tests for the :class:`ImportStats` dataclass."""

    def test_default_values(self) -> None:
        """All counters start at zero and lists are empty."""
        stats = ImportStats()
        self.assertEqual(stats.files_processed, 0)
        self.assertEqual(stats.documents_created, 0)
        self.assertEqual(stats.chunks_created, 0)
        self.assertEqual(stats.chunks_embedded, 0)
        self.assertEqual(stats.errors, [])
        self.assertEqual(stats.skipped, [])


# ---------------------------------------------------------------------------
# ImportChunkedDataCommandTests
# ---------------------------------------------------------------------------


class ImportChunkedDataCommandTests(TestCase):
    """Tests for the ``import_chunked_data`` management command."""

    def setUp(self) -> None:
        self.superuser = User.objects.create_superuser(
            email="admin@test.com",
            password="adminpass123",
        )

    # -- 1. Format A ingestion (legislation) -----------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_format_a_legislation_ingestion(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Format A JSON creates correct Document + DocumentChunk records."""
        mock_batch_embeddings.return_value = [
            _make_embedding(),
            _make_embedding(),
        ]

        json_content = _make_format_a_json(total_chunks=2)
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("test_legislation.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out,
        )

        # Verify Document was created
        doc = Document.objects.get(title="قانون مجازات اسلامي")
        self.assertEqual(doc.document_type, "reference_law")
        self.assertEqual(doc.hub_type, "legislation")
        self.assertEqual(doc.status, "completed")
        self.assertEqual(doc.total_chunks, 2)
        self.assertEqual(doc.user, self.superuser)

        # Verify DocumentChunks were created
        chunks = DocumentChunk.objects.filter(document=doc).order_by("chunk_index")
        self.assertEqual(chunks.count(), 2)
        for chunk in chunks:
            self.assertEqual(chunk.hub_type, "legislation")
            self.assertIsNotNone(chunk.embedding)
            self.assertEqual(chunk.metadata.get("hub_type"), "legislation")

        # Verify chunk metadata
        self.assertEqual(
            chunks[0].metadata.get("chunk_id"),
            "madde_1",
        )
        self.assertEqual(
            chunks[1].metadata.get("chunk_id"),
            "madde_2",
        )

        # Verify output
        self.assertIn("✓ 'قانون مجازات اسلامي'", out.getvalue())
        self.assertIn("2 chunks (2 embedded)", out.getvalue())

    # -- 2. Format B ingestion (precedent) with hub type normalisation ---------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_format_b_precedent_with_normalisation(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Format B JSON normalises ``precedent`` → ``judicial_precedent``."""
        mock_batch_embeddings.return_value = [
            _make_embedding(),
            _make_embedding(),
        ]

        json_content = _make_format_b_json(hub_type="precedent", num_chunks=2)
        data_dir = _create_temp_data_dir(
            "هاب رویه های قضایی",
            [("test_precedent.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out,
        )

        # Verify hub_type was normalised
        doc = Document.objects.get(hub_type="judicial_precedent")
        self.assertEqual(doc.hub_type, "judicial_precedent")

        chunks = DocumentChunk.objects.filter(document=doc)
        for chunk in chunks:
            self.assertEqual(chunk.hub_type, "judicial_precedent")
            self.assertEqual(
                chunk.metadata.get("hub_type"),
                "judicial_precedent",
            )

        # Verify document title came from metadata.source fallback
        # (metadata has no 'source' key in Format B, so it uses full_title)
        self.assertIn("رای وحدت رویه شماره ۱", doc.title)

    # -- 3. Format C ingestion (advisory) with folder-based hub type -----------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_format_c_advisory_folder_based_hub(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Format C JSON uses folder name to determine hub_type."""
        mock_batch_embeddings.return_value = [
            _make_embedding(),
            _make_embedding(),
        ]

        json_content = _make_format_c_json(num_chunks=2)
        data_dir = _create_temp_data_dir(
            "هاب نظریات مشورتی و رویه عملی",
            [("test_advisory.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out,
        )

        # Verify hub_type from folder mapping
        doc = Document.objects.get(hub_type="advisory_opinion")
        self.assertEqual(doc.hub_type, "advisory_opinion")

        chunks = DocumentChunk.objects.filter(document=doc)
        for chunk in chunks:
            self.assertEqual(chunk.hub_type, "advisory_opinion")
            self.assertEqual(
                chunk.metadata.get("hub_type"),
                "advisory_opinion",
            )

        # Verify chunk metadata from Format C fields
        chunk0 = chunks.order_by("chunk_index")[0]
        self.assertEqual(chunk0.metadata.get("chunk_id"), "7/1403/878_metadata")
        self.assertEqual(chunk0.metadata.get("opinion_number"), "7/1403/878")
        self.assertEqual(chunk0.metadata.get("chunk_type"), "metadata")
        self.assertEqual(chunk0.metadata.get("position"), 1)

    # -- 4. All folder-to-hub mappings -----------------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_all_folder_to_hub_mappings(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Each folder name maps to the correct hub_type."""
        mock_batch_embeddings.return_value = [_make_embedding()]

        for idx, (folder_name, expected_hub) in enumerate(FOLDER_HUB_MAP.items()):
            # Use unique chunk_id_prefix and source_name to avoid
            # idempotency conflicts across iterations
            json_content = _make_format_a_json(
                source_file=f"test_{expected_hub}.json",
                total_chunks=1,
                hub_type=expected_hub,
                chunk_id_prefix=f"hub_test_{idx}",
                source_name=f"Test {expected_hub} Law",
            )
            data_dir = _create_temp_data_dir(
                folder_name,
                [(f"test_{expected_hub}.json", json_content)],
            )

            out = StringIO()
            call_command(
                "import_chunked_data",
                f"--data-dir={data_dir}",
                stdout=out,
            )

            doc = Document.objects.get(hub_type=expected_hub)
            self.assertEqual(doc.hub_type, expected_hub)

    # -- 5. Hub type normalisation ---------------------------------------------

    def test_hub_type_normalisation(self) -> None:
        """All known aliases are normalised correctly."""
        cmd = Command()
        test_cases = [
            ("precedent", "judicial_precedent"),
            ("judicial_precedent", "judicial_precedent"),
            ("legislation", "legislation"),
            ("advisory_opinion", "advisory_opinion"),
            ("advisory", "advisory_opinion"),
            (None, None),
            ("unknown", None),
        ]
        for raw, expected in test_cases:
            with self.subTest(raw=raw):
                self.assertEqual(cmd._normalize_hub_type(raw), expected)

    # -- 6. Dry-run mode -------------------------------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_dry_run_does_not_write_to_db(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Dry-run mode validates without creating DB records."""
        mock_batch_embeddings.return_value = [_make_embedding()]

        json_content = _make_format_a_json(total_chunks=1)
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("test_legislation.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            "--dry-run",
            stdout=out,
        )

        # No records should exist
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentChunk.objects.count(), 0)

        # Output should indicate dry-run
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertIn("قانون مجازات اسلامي", out.getvalue())

    # -- 7. Idempotency --------------------------------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_idempotency_skips_existing_chunks(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Running the same command twice does not create duplicate chunks."""
        mock_batch_embeddings.return_value = [_make_embedding()]

        json_content = _make_format_a_json(total_chunks=1)
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("test_legislation.json", json_content)],
        )

        # First run
        out1 = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out1,
        )
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(DocumentChunk.objects.count(), 1)

        # Second run — should skip due to idempotency
        out2 = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out2,
        )

        # No new records
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(DocumentChunk.objects.count(), 1)
        self.assertIn("already exist", out2.getvalue())

    # -- 8. Transactional rollback on failure ----------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_transactional_rollback_on_embedding_failure(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """If embedding fails mid-way, no partial data remains."""
        # First batch succeeds, second batch fails
        mock_batch_embeddings.side_effect = [
            [_make_embedding()],
            ValueError("Embedding API error"),
        ]

        json_content = _make_format_a_json(total_chunks=2)
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("test_legislation.json", json_content)],
        )

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_chunked_data",
                f"--data-dir={data_dir}",
                "--embedding-batch-size",
                "1",
                stdout=out,
                stderr=StringIO(),
            )

        # No records should exist (rolled back)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentChunk.objects.count(), 0)

    # -- 9. Missing text field validation --------------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_missing_text_field_raises_error(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """A chunk without a 'text' field raises a meaningful error."""
        mock_batch_embeddings.return_value = [_make_embedding()]

        # Create a Format A JSON with a chunk missing the 'text' field
        chunks = [
            {
                "chunk_id": "madde_1",
                "madde_number": 1,
                "madde_raw": "ماده 1",
                # No 'text' field
                "metadata": {
                    "source": "قانون تست",
                    "hub_type": "legislation",
                },
            },
        ]
        json_content = json.dumps(
            {
                "source_file": "test.json",
                "total_chunks": 1,
                "chunks": chunks,
            },
            ensure_ascii=False,
        )
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("test_missing_text.json", json_content)],
        )

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_chunked_data",
                f"--data-dir={data_dir}",
                stdout=out,
                stderr=StringIO(),
            )

        # No records should exist
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentChunk.objects.count(), 0)

    # -- 10. Invalid JSON ------------------------------------------------------

    def test_invalid_json_raises_error(self) -> None:
        """Invalid JSON file is reported as an error."""
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("invalid.json", "{invalid json}")],
        )

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_chunked_data",
                f"--data-dir={data_dir}",
                stdout=out,
                stderr=StringIO(),
            )

        self.assertEqual(Document.objects.count(), 0)

    # -- 11. Unknown folder name -----------------------------------------------

    def test_unknown_folder_skipped(self) -> None:
        """An unknown folder name is skipped with a warning."""
        data_dir = _create_temp_data_dir(
            "پوشه ناشناخته",
            [("test.json", "[]")],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out,
        )

        self.assertEqual(Document.objects.count(), 0)
        self.assertIn("unknown folder", out.getvalue())

    # -- 12. Non-existent data directory ---------------------------------------

    def test_non_existent_data_dir(self) -> None:
        """A non-existent data directory raises CommandError."""
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "import_chunked_data",
                "--data-dir=/nonexistent/path",
                stdout=StringIO(),
            )
        self.assertIn("Data directory not found", str(ctx.exception))

    # -- 13. User-id parameter -------------------------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_user_id_parameter(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """The --user-id parameter assigns a specific owner."""
        mock_batch_embeddings.return_value = [_make_embedding()]

        regular_user = User.objects.create_user(
            email="regular@test.com",
            password="pass123",
        )

        json_content = _make_format_a_json(total_chunks=1)
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("test_legislation.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            f"--user-id={regular_user.id}",
            stdout=out,
        )

        doc = Document.objects.first()
        self.assertEqual(doc.user, regular_user)

    # -- 14. Multiple files in one folder --------------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_multiple_files_in_folder(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Multiple JSON files in one folder are all processed."""
        mock_batch_embeddings.return_value = [_make_embedding()]

        json1 = _make_format_a_json(
            source_file="law_one.json",
            total_chunks=1,
            chunk_id_prefix="law_one",
        )
        json2 = _make_format_a_json(
            source_file="law_two.json",
            total_chunks=1,
            chunk_id_prefix="law_two",
        )
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("law_one.json", json1), ("law_two.json", json2)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out,
        )

        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(DocumentChunk.objects.count(), 2)

    # -- 15. Format detection --------------------------------------------------

    def test_format_detection(self) -> None:
        """Format detection correctly identifies Format A vs Format B."""
        cmd = Command()

        # Format A: dict with 'chunks' key
        fmt_a = {"source_file": "test.json", "total_chunks": 1, "chunks": []}
        self.assertEqual(cmd._detect_format(fmt_a), "format_a")

        # Format B: list
        fmt_b: list = []
        self.assertEqual(cmd._detect_format(fmt_b), "format_b")

        # Invalid: plain dict without 'chunks'
        with self.assertRaises(ValueError):
            cmd._detect_format({"key": "value"})

        # Invalid: string
        with self.assertRaises(ValueError):
            cmd._detect_format("not valid")

    # -- 16. Embedding batch size parameter ------------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_embedding_batch_size_parameter(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """The --embedding-batch-size parameter controls sub-batching."""
        mock_batch_embeddings.return_value = [_make_embedding()]

        json_content = _make_format_a_json(total_chunks=1)
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("test_legislation.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            "--embedding-batch-size=1",
            stdout=out,
        )

        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(DocumentChunk.objects.count(), 1)

    # -- 17. Empty chunks array ------------------------------------------------

    def test_empty_chunks_array_skipped(self) -> None:
        """A file with an empty chunks array is skipped."""
        json_content = json.dumps(
            {"source_file": "empty.json", "total_chunks": 0, "chunks": []},
            ensure_ascii=False,
        )
        data_dir = _create_temp_data_dir(
            "هاب قوانین مصوب",
            [("empty.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out,
        )

        self.assertEqual(Document.objects.count(), 0)
        self.assertIn("no chunks in file", out.getvalue())

    # -- 18. Format B with multiple full_titles --------------------------------

    @patch(
        "documents.management.commands.import_chunked_data.batch_generate_embeddings"
    )
    def test_format_b_multiple_documents(
        self,
        mock_batch_embeddings: MagicMock,
    ) -> None:
        """Format B chunks with different full_titles create separate documents."""
        mock_batch_embeddings.return_value = [
            _make_embedding(),
            _make_embedding(),
        ]

        chunks = [
            {
                "text": "رای شماره ۱",
                "chunk_type": "header",
                "full_title": "رای وحدت رویه شماره ۱",
                "metadata": {
                    "hub_type": "precedent",
                },
            },
            {
                "text": "رای شماره ۲",
                "chunk_type": "header",
                "full_title": "رای وحدت رویه شماره ۲",
                "metadata": {
                    "hub_type": "precedent",
                },
            },
        ]
        json_content = json.dumps(chunks, ensure_ascii=False)
        data_dir = _create_temp_data_dir(
            "هاب رویه های قضایی",
            [("test_precedent.json", json_content)],
        )

        out = StringIO()
        call_command(
            "import_chunked_data",
            f"--data-dir={data_dir}",
            stdout=out,
        )

        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(DocumentChunk.objects.count(), 2)
