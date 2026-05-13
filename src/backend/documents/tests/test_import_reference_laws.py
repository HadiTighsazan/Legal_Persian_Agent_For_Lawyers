"""
Tests for the ``import_reference_laws`` management command.

Tests cover:
- JSON parsing and validation (hub_type, documents array)
- Document and DocumentChunk creation
- Dry-run mode (no DB writes)
- Error handling (invalid files, missing fields, chunking failures)
- Embedding generation integration

All external dependencies (``AnchorChunkingService``, ``batch_generate_embeddings``)
are mocked using ``unittest.mock.patch``.
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

from documents.management.commands.import_reference_laws import (
    VALID_HUB_TYPES,
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


def _make_valid_json(
    hub_type: str = "legislation",
    documents: list[dict] | None = None,
) -> str:
    """Return a valid JSON string for the import command."""
    if documents is None:
        documents = [
            {
                "title": "قانون مجازات اسلامی",
                "filename": "qanoon_mojazat_islami.pdf",
                "content": "متن کامل قانون مجازات اسلامی برای تست.",
                "metadata": {
                    "law_name": "قانون مجازات اسلامی",
                    "legal_status": "جاری",
                    "approval_date": "1392-01-01",
                    "legal_type": "قانون",
                },
            },
        ]
    return json.dumps({"hub_type": hub_type, "documents": documents}, ensure_ascii=False)


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
# ImportCommandTests
# ---------------------------------------------------------------------------


class ImportCommandTests(TestCase):
    """Tests for the ``import_reference_laws`` management command."""

    def setUp(self) -> None:
        self.superuser = User.objects.create_superuser(
            email="admin@test.com",
            password="adminpass123",
        )

    # -- 1. Valid JSON with hub_type -----------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    @patch(
        "documents.management.commands.import_reference_laws.batch_generate_embeddings"
    )
    def test_import_creates_document_and_chunks(
        self,
        mock_batch_embeddings: MagicMock,
        mock_chunk_text: MagicMock,
    ) -> None:
        """A valid JSON file creates one Document and one DocumentChunk."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="متن کامل قانون مجازات اسلامی برای تست.",
                pages=[1],
                token_count=10,
                metadata={"law_name": "قانون مجازات اسلامی"},
            ),
        ]
        mock_batch_embeddings.return_value = [_make_embedding()]

        json_content = _make_valid_json()
        file_path = _write_temp_json(json_content)

        out = StringIO()
        call_command(
            "import_reference_laws",
            f"--file={file_path}",
            stdout=out,
        )

        # Verify Document was created
        doc = Document.objects.get(title="قانون مجازات اسلامی")
        self.assertEqual(doc.document_type, "reference_law")
        self.assertEqual(doc.hub_type, "legislation")
        self.assertEqual(doc.status, "completed")
        self.assertEqual(doc.user, self.superuser)

        # Verify DocumentChunk was created
        chunk = DocumentChunk.objects.get(document=doc)
        self.assertEqual(chunk.hub_type, "legislation")
        self.assertEqual(chunk.chunk_index, 0)
        self.assertEqual(chunk.page_start, 1)
        self.assertEqual(chunk.page_end, 1)
        self.assertIsNotNone(chunk.embedding)

        # Verify output contains success message
        self.assertIn("✓ 'قانون مجازات اسلامی'", out.getvalue())

        os.unlink(file_path)

    # -- 2. Invalid hub_type -------------------------------------------------

    def test_invalid_hub_type_rejected(self) -> None:
        """A JSON file with an invalid hub_type is rejected."""
        json_content = _make_valid_json(hub_type="invalid_hub")
        file_path = _write_temp_json(json_content)

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_reference_laws",
                f"--file={file_path}",
                stdout=out,
                stderr=StringIO(),
            )

        # No documents should have been created
        self.assertEqual(Document.objects.count(), 0)

        os.unlink(file_path)

    # -- 3. Missing hub_type -------------------------------------------------

    def test_missing_hub_type_rejected(self) -> None:
        """A JSON file without a hub_type key is rejected."""
        data = {"documents": [{"title": "Test", "content": "Test content."}]}
        json_content = json.dumps(data, ensure_ascii=False)
        file_path = _write_temp_json(json_content)

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_reference_laws",
                f"--file={file_path}",
                stdout=out,
                stderr=StringIO(),
            )

        self.assertEqual(Document.objects.count(), 0)
        os.unlink(file_path)

    # -- 4. Empty documents array --------------------------------------------

    def test_empty_documents_array_skipped(self) -> None:
        """A JSON file with an empty documents array is skipped."""
        json_content = _make_valid_json(documents=[])
        file_path = _write_temp_json(json_content)

        out = StringIO()
        call_command(
            "import_reference_laws",
            f"--file={file_path}",
            stdout=out,
        )

        self.assertEqual(Document.objects.count(), 0)
        self.assertIn("no documents in file", out.getvalue())
        os.unlink(file_path)

    # -- 5. Document with empty title ----------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    def test_empty_title_skipped(
        self,
        mock_chunk_text: MagicMock,
    ) -> None:
        """A document with an empty title is skipped with an error."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="Some content.",
                pages=[1],
                token_count=5,
                metadata={},
            ),
        ]

        documents = [
            {
                "title": "",
                "content": "Some content.",
                "metadata": {},
            },
        ]
        json_content = _make_valid_json(documents=documents)
        file_path = _write_temp_json(json_content)

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_reference_laws",
                f"--file={file_path}",
                stdout=out,
                stderr=StringIO(),
            )

        self.assertEqual(Document.objects.count(), 0)
        os.unlink(file_path)

    # -- 6. Document with empty content --------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    def test_empty_content_skipped(
        self,
        mock_chunk_text: MagicMock,
    ) -> None:
        """A document with empty content is skipped with an error."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="",
                pages=[1],
                token_count=0,
                metadata={},
            ),
        ]

        documents = [
            {
                "title": "Empty Document",
                "content": "",
                "metadata": {},
            },
        ]
        json_content = _make_valid_json(documents=documents)
        file_path = _write_temp_json(json_content)

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_reference_laws",
                f"--file={file_path}",
                stdout=out,
                stderr=StringIO(),
            )

        self.assertEqual(Document.objects.count(), 0)
        os.unlink(file_path)

    # -- 7. Dry-run mode -----------------------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    def test_dry_run_does_not_write_to_db(
        self,
        mock_chunk_text: MagicMock,
    ) -> None:
        """Dry-run mode validates the file without creating DB records."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="Test content for dry run.",
                pages=[1, 2],
                token_count=8,
                metadata={},
            ),
        ]

        json_content = _make_valid_json()
        file_path = _write_temp_json(json_content)

        out = StringIO()
        call_command(
            "import_reference_laws",
            f"--file={file_path}",
            "--dry-run",
            stdout=out,
        )

        # No records should exist
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(DocumentChunk.objects.count(), 0)

        # Output should indicate dry-run
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertIn("قانون مجازات اسلامی", out.getvalue())

        os.unlink(file_path)

    # -- 8. Multiple documents in one file -----------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    @patch(
        "documents.management.commands.import_reference_laws.batch_generate_embeddings"
    )
    def test_multiple_documents_in_file(
        self,
        mock_batch_embeddings: MagicMock,
        mock_chunk_text: MagicMock,
    ) -> None:
        """A file with multiple documents creates all of them."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="Document content.",
                pages=[1],
                token_count=5,
                metadata={},
            ),
        ]
        mock_batch_embeddings.return_value = [_make_embedding()]

        documents = [
            {
                "title": "قانون اول",
                "content": "متن قانون اول.",
                "metadata": {"law_name": "قانون اول"},
            },
            {
                "title": "قانون دوم",
                "content": "متن قانون دوم.",
                "metadata": {"law_name": "قانون دوم"},
            },
        ]
        json_content = _make_valid_json(documents=documents)
        file_path = _write_temp_json(json_content)

        out = StringIO()
        call_command(
            "import_reference_laws",
            f"--file={file_path}",
            stdout=out,
        )

        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(DocumentChunk.objects.count(), 2)
        os.unlink(file_path)

    # -- 9. All valid hub types ----------------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    @patch(
        "documents.management.commands.import_reference_laws.batch_generate_embeddings"
    )
    def test_all_valid_hub_types(
        self,
        mock_batch_embeddings: MagicMock,
        mock_chunk_text: MagicMock,
    ) -> None:
        """Each valid hub type is accepted."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="Hub test content.",
                pages=[1],
                token_count=5,
                metadata={},
            ),
        ]
        mock_batch_embeddings.return_value = [_make_embedding()]

        for hub_type in sorted(VALID_HUB_TYPES):
            json_content = _make_valid_json(hub_type=hub_type)
            file_path = _write_temp_json(json_content)

            out = StringIO()
            call_command(
                "import_reference_laws",
                f"--file={file_path}",
                stdout=out,
            )

            doc = Document.objects.get(hub_type=hub_type)
            self.assertEqual(doc.hub_type, hub_type)
            os.unlink(file_path)

    # -- 10. Invalid file path -----------------------------------------------

    def test_invalid_file_path_raises_error(self) -> None:
        """A non-existent file path raises CommandError."""
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "import_reference_laws",
                "--file=/nonexistent/file.json",
                stdout=StringIO(),
            )
        self.assertIn("File not found", str(ctx.exception))

    # -- 11. Chunking failure -------------------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    def test_chunking_failure_reported(
        self,
        mock_chunk_text: MagicMock,
    ) -> None:
        """If chunking fails, the error is recorded and no document is created."""
        mock_chunk_text.side_effect = ValueError("Chunking error")

        json_content = _make_valid_json()
        file_path = _write_temp_json(json_content)

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_reference_laws",
                f"--file={file_path}",
                stdout=out,
                stderr=StringIO(),
            )

        self.assertEqual(Document.objects.count(), 0)
        os.unlink(file_path)

    # -- 12. Embedding failure -------------------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    @patch(
        "documents.management.commands.import_reference_laws.batch_generate_embeddings"
    )
    def test_embedding_failure_reported(
        self,
        mock_batch_embeddings: MagicMock,
        mock_chunk_text: MagicMock,
    ) -> None:
        """If embedding generation fails, the error is recorded."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="Test content.",
                pages=[1],
                token_count=5,
                metadata={},
            ),
        ]
        mock_batch_embeddings.side_effect = ValueError("Embedding error")

        json_content = _make_valid_json()
        file_path = _write_temp_json(json_content)

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "import_reference_laws",
                f"--file={file_path}",
                stdout=out,
                stderr=StringIO(),
            )

        self.assertEqual(Document.objects.count(), 0)
        os.unlink(file_path)

    # -- 13. Hub_type stored in chunk metadata --------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    @patch(
        "documents.management.commands.import_reference_laws.batch_generate_embeddings"
    )
    def test_hub_type_in_chunk_metadata(
        self,
        mock_batch_embeddings: MagicMock,
        mock_chunk_text: MagicMock,
    ) -> None:
        """The hub_type is stored in the chunk's metadata dict."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="Test content.",
                pages=[1],
                token_count=5,
                metadata={"section": "intro"},
            ),
        ]
        mock_batch_embeddings.return_value = [_make_embedding()]

        json_content = _make_valid_json(hub_type="judicial_precedent")
        file_path = _write_temp_json(json_content)

        out = StringIO()
        call_command(
            "import_reference_laws",
            f"--file={file_path}",
            stdout=out,
        )

        chunk = DocumentChunk.objects.first()
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.hub_type, "judicial_precedent")
        self.assertEqual(chunk.metadata.get("hub_type"), "judicial_precedent")
        self.assertEqual(chunk.metadata.get("section"), "intro")

        os.unlink(file_path)

    # -- 14. User-id parameter ------------------------------------------------

    @patch(
        "documents.management.commands.import_reference_laws.AnchorChunkingService.chunk_text"
    )
    @patch(
        "documents.management.commands.import_reference_laws.batch_generate_embeddings"
    )
    def test_user_id_parameter(
        self,
        mock_batch_embeddings: MagicMock,
        mock_chunk_text: MagicMock,
    ) -> None:
        """The --user-id parameter assigns a specific owner."""
        mock_chunk_text.return_value = [
            MagicMock(
                content="Test content.",
                pages=[1],
                token_count=5,
                metadata={},
            ),
        ]
        mock_batch_embeddings.return_value = [_make_embedding()]

        # Create a non-superuser
        regular_user = User.objects.create_user(
            email="regular@test.com",
            password="pass123",
        )

        json_content = _make_valid_json()
        file_path = _write_temp_json(json_content)

        out = StringIO()
        call_command(
            "import_reference_laws",
            f"--file={file_path}",
            f"--user-id={regular_user.id}",
            stdout=out,
        )

        doc = Document.objects.first()
        self.assertEqual(doc.user, regular_user)

        os.unlink(file_path)
