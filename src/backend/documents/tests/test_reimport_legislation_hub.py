"""
Tests for the ``reimport_legislation_hub`` management command.

Tests cover:
- Purge phase: deleting existing legislation data
- Purge isolation: other hubs are NOT affected
- Load phase: reading and validating JSON files
- Grouping phase: grouping chunks by ``metadata.source``
- Import phase: creating Documents and Chunks with correct fields
- Embedding phase: generating embeddings for all chunks
- Dry-run mode: no DB writes
- Error handling: invalid JSON, missing fields, empty directories
- Idempotency: re-running is safe (purge + re-import)

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

from documents.management.commands.reimport_legislation_hub import (
    LEGISLATION_HUB_TYPE,
    ReimportStats,
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


def _make_law_chunk(
    law_name: str,
    madde_number: int,
    chunk_id_suffix: str = "",
    text_override: str | None = None,
) -> dict:
    """Create a single chunk dict mimicking the legislation JSON format.

    Args:
        law_name: The law name (e.g., ``"قانون مجازات اسلامی"``).
        madde_number: The article number.
        chunk_id_suffix: Optional suffix for chunk_id uniqueness.
        text_override: Optional override for the text field.

    Returns:
        A chunk dict matching the Format B structure.
    """
    chunk_id = f"{law_name}-madde_{madde_number}"
    if chunk_id_suffix:
        chunk_id += f"_{chunk_id_suffix}"

    text = text_override or f"ماده {madde_number} متن ماده {madde_number} برای تست."

    return {
        "chunk_id": chunk_id,
        "madde_number": madde_number,
        "madde_suffix": "",
        "madde_raw": f"ماده {madde_number}\n{text}",
        "text": text,
        "metadata": {
            "source": law_name,
            "hub_type": "legislation",
            "approval_date": "1392/02/01",
            "approval_authority": "مجلس شورای اسلامی",
            "status": "معتبر",
            "summary": f"{law_name} - مصوب 1392/02/01",
            "kitab": "کتاب اول - کلیات",
            "bakhsh": "بخش اول - مواد عمومی",
            "fasl": "فصل اول - تعاریف",
            "mabhath": "",
            "char_count": len(text),
            "line_count": 1,
        },
    }


def _make_law_json(
    law_name: str,
    num_chunks: int = 3,
    chunk_id_prefix: str = "",
) -> str:
    """Create a JSON string for a single law file (Format B — flat array).

    Args:
        law_name: The law name.
        num_chunks: Number of chunks to generate.
        chunk_id_prefix: Optional prefix for chunk_id uniqueness.

    Returns:
        A JSON string representing the law file.
    """
    chunks = [
        _make_law_chunk(
            law_name=law_name,
            madde_number=i + 1,
            chunk_id_suffix=chunk_id_prefix,
        )
        for i in range(num_chunks)
    ]
    return json.dumps(chunks, ensure_ascii=False)


def _setup_legislation_data(
    num_docs: int = 2,
    chunks_per_doc: int = 3,
) -> list[Document]:
    """Create existing legislation documents in the database for purge testing.

    Args:
        num_docs: Number of legislation documents to create.
        chunks_per_doc: Number of chunks per document.

    Returns:
        The list of created Document instances.
    """
    user = User.objects.create_user(
        email="legacy@test.com",
        password="testpass123",
        is_superuser=True,
        is_active=True,
    )
    docs: list[Document] = []
    for i in range(num_docs):
        doc = Document.objects.create(
            user=user,
            title=f"Existing Law {i + 1}",
            filename=f"existing_law_{i + 1}.txt",
            original_filename=f"existing_law_{i + 1}.txt",
            file_path="",
            file_size=1000,
            mime_type="text/plain",
            storage_type="local",
            status="completed",
            document_type="reference_law",
            hub_type=LEGISLATION_HUB_TYPE,
            processing_status="completed",
            total_chunks=chunks_per_doc,
            extracted_text="test " * 100,
            extracted_text_length=500,
            extraction_method="import_chunked",
        )
        for j in range(chunks_per_doc):
            DocumentChunk.objects.create(
                document=doc,
                chunk_index=j,
                page_start=1,
                page_end=1,
                content=f"Existing chunk {j + 1} of law {i + 1}.",
                hub_type=LEGISLATION_HUB_TYPE,
                metadata={"source": f"Existing Law {i + 1}", "hub_type": "legislation"},
                law_name=f"Existing Law {i + 1}",
                legal_status="معتبر",
            )
        docs.append(doc)
    return docs


def _setup_other_hub_data(hub_type: str = "judicial_precedent") -> Document:
    """Create a document in a non-legislation hub for isolation testing.

    Args:
        hub_type: The hub type to create (default: judicial_precedent).

    Returns:
        The created Document instance.
    """
    user = User.objects.first()
    if not user:
        user = User.objects.create_user(
            email="other@test.com",
            password="testpass123",
            is_superuser=True,
            is_active=True,
        )
    doc = Document.objects.create(
        user=user,
        title=f"Other Hub Document ({hub_type})",
        filename="other.txt",
        original_filename="other.txt",
        file_path="",
        file_size=500,
        mime_type="text/plain",
        storage_type="local",
        status="completed",
        document_type="reference_law",
        hub_type=hub_type,
        processing_status="completed",
        total_chunks=2,
        extracted_text="other data",
        extracted_text_length=10,
        extraction_method="import_chunked",
    )
    for j in range(2):
        DocumentChunk.objects.create(
            document=doc,
            chunk_index=j,
            page_start=1,
            page_end=1,
            content=f"Other chunk {j + 1}.",
            hub_type=hub_type,
            metadata={"source": f"Other ({hub_type})", "hub_type": hub_type},
        )
    return doc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class ReimportLegislationHubCommandTests(TestCase):
    """Tests for the ``reimport_legislation_hub`` management command."""

    def setUp(self) -> None:
        """Create a superuser for default owner resolution."""
        self.superuser = User.objects.create_user(
            email="admin@test.com",
            password="adminpass123",
            is_superuser=True,
            is_active=True,
        )
        # Create a temp directory for test JSON files
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        self.temp_dir = self.temp_dir_obj.name

    def tearDown(self) -> None:
        """Clean up temp directory."""
        self.temp_dir_obj.cleanup()

    def _write_json_file(self, filename: str, content: str) -> str:
        """Write a JSON file to the temp directory and return its path."""
        file_path = os.path.join(self.temp_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return file_path

    # ------------------------------------------------------------------
    # Purge Phase Tests
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_purge_existing_legislation_data(
        self, mock_embed: MagicMock
    ) -> None:
        """Verify existing legislation docs/chunks are deleted during import."""
        mock_embed.return_value = [_make_embedding()] * 3

        # Setup existing legislation data
        _setup_legislation_data(num_docs=2, chunks_per_doc=3)

        # Verify data exists before purge
        self.assertEqual(
            Document.objects.filter(hub_type=LEGISLATION_HUB_TYPE).count(), 2
        )
        self.assertEqual(
            DocumentChunk.objects.filter(hub_type=LEGISLATION_HUB_TYPE).count(), 6
        )

        # Write a test law file to import
        law_json = _make_law_json(law_name="قانون تست", num_chunks=3)
        self._write_json_file("قانون_تست.json", law_json)

        # Run the command
        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        # Verify old data is gone
        old_docs = Document.objects.filter(
            title__startswith="Existing Law"
        )
        self.assertEqual(old_docs.count(), 0)

        # Verify new data exists
        new_docs = Document.objects.filter(hub_type=LEGISLATION_HUB_TYPE)
        self.assertEqual(new_docs.count(), 1)
        self.assertEqual(new_docs[0].title, "قانون تست")

        # Verify output contains purge info
        output = out.getvalue()
        self.assertIn("Purge", output)
        self.assertIn("2 document(s)", output)
        self.assertIn("6 chunk(s)", output)

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_purge_only_legislation_not_other_hubs(
        self, mock_embed: MagicMock
    ) -> None:
        """Verify other hubs are NOT affected by the purge."""
        mock_embed.return_value = [_make_embedding()] * 3

        # Setup data in all 3 hubs
        _setup_legislation_data(num_docs=1, chunks_per_doc=2)
        precedent_doc = _setup_other_hub_data("judicial_precedent")
        advisory_doc = _setup_other_hub_data("advisory_opinion")

        # Write a test law file
        law_json = _make_law_json(law_name="قانون تست", num_chunks=3)
        self._write_json_file("قانون_تست.json", law_json)

        # Run the command
        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        # Verify legislation data was purged and re-created
        legis_docs = Document.objects.filter(hub_type=LEGISLATION_HUB_TYPE)
        self.assertEqual(legis_docs.count(), 1)  # The new one
        self.assertEqual(legis_docs[0].title, "قانون تست")

        # Verify other hubs are untouched
        self.assertTrue(
            Document.objects.filter(id=precedent_doc.id).exists()
        )
        self.assertTrue(
            Document.objects.filter(id=advisory_doc.id).exists()
        )

        precedent_chunks = DocumentChunk.objects.filter(
            hub_type="judicial_precedent"
        )
        advisory_chunks = DocumentChunk.objects.filter(
            hub_type="advisory_opinion"
        )
        self.assertEqual(precedent_chunks.count(), 2)
        self.assertEqual(advisory_chunks.count(), 2)

    # ------------------------------------------------------------------
    # Import Phase Tests
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_import_single_law_file(self, mock_embed: MagicMock) -> None:
        """Import one JSON file, verify 1 document + N chunks created."""
        mock_embed.return_value = [_make_embedding()] * 5

        law_json = _make_law_json(
            law_name="قانون مجازات اسلامی", num_chunks=5
        )
        self._write_json_file("قانون_مجازات_اسلامی.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        # Verify document
        docs = Document.objects.filter(hub_type=LEGISLATION_HUB_TYPE)
        self.assertEqual(docs.count(), 1)
        doc = docs[0]
        self.assertEqual(doc.title, "قانون مجازات اسلامی")
        self.assertEqual(doc.document_type, "reference_law")
        self.assertEqual(doc.hub_type, "legislation")
        self.assertEqual(doc.status, "completed")
        self.assertEqual(doc.total_chunks, 5)

        # Verify chunks
        chunks = DocumentChunk.objects.filter(document=doc).order_by(
            "chunk_index"
        )
        self.assertEqual(chunks.count(), 5)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[0].hub_type, "legislation")
        self.assertIn("ماده 1", chunks[0].content)
        self.assertEqual(chunks[4].chunk_index, 4)
        self.assertIn("ماده 5", chunks[4].content)

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_import_multiple_law_files(self, mock_embed: MagicMock) -> None:
        """Import multiple files, verify correct document count."""
        mock_embed.return_value = [_make_embedding()] * 8

        # Create 3 law files
        laws = [
            ("قانون مجازات اسلامی", 3),
            ("قانون مدنی", 3),
            ("قانون تجارت", 2),
        ]
        for law_name, num_chunks in laws:
            law_json = _make_law_json(
                law_name=law_name, num_chunks=num_chunks
            )
            self._write_json_file(f"{law_name}.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        # Verify 3 documents created
        docs = Document.objects.filter(hub_type=LEGISLATION_HUB_TYPE).order_by(
            "title"
        )
        self.assertEqual(docs.count(), 3)
        self.assertEqual(docs[0].title, "قانون تجارت")
        self.assertEqual(docs[1].title, "قانون مجازات اسلامی")
        self.assertEqual(docs[2].title, "قانون مدنی")

        # Verify total chunks
        total_chunks = DocumentChunk.objects.filter(
            hub_type=LEGISLATION_HUB_TYPE
        ).count()
        self.assertEqual(total_chunks, 8)

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_grouping_by_metadata_source(self, mock_embed: MagicMock) -> None:
        """Verify chunks are grouped by metadata.source."""
        mock_embed.return_value = [_make_embedding()] * 6

        # Create a single file with chunks from TWO different laws
        # This simulates a file that contains mixed content
        chunks = [
            _make_law_chunk(law_name="قانون الف", madde_number=1),
            _make_law_chunk(law_name="قانون الف", madde_number=2),
            _make_law_chunk(law_name="قانون ب", madde_number=1),
            _make_law_chunk(law_name="قانون ب", madde_number=2),
            _make_law_chunk(law_name="قانون ب", madde_number=3),
            _make_law_chunk(law_name="قانون ج", madde_number=1),
        ]
        self._write_json_file("mixed.json", json.dumps(chunks, ensure_ascii=False))

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        # Verify 3 documents created (one per unique law name)
        docs = Document.objects.filter(
            hub_type=LEGISLATION_HUB_TYPE
        ).order_by("title")
        self.assertEqual(docs.count(), 3)

        # Verify chunk counts per document
        doc_a = docs.get(title="قانون الف")
        self.assertEqual(doc_a.total_chunks, 2)

        doc_b = docs.get(title="قانون ب")
        self.assertEqual(doc_b.total_chunks, 3)

        doc_c = docs.get(title="قانون ج")
        self.assertEqual(doc_c.total_chunks, 1)

    # ------------------------------------------------------------------
    # Denormalized Fields Tests
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_denormalized_fields_populated(self, mock_embed: MagicMock) -> None:
        """Verify law_name, legal_status, approval_date, legal_type are set."""
        mock_embed.return_value = [_make_embedding()] * 2

        law_json = _make_law_json(law_name="قانون مدنی", num_chunks=2)
        self._write_json_file("قانون_مدنی.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        chunks = DocumentChunk.objects.filter(
            document__title="قانون مدنی"
        ).order_by("chunk_index")

        for chunk in chunks:
            self.assertEqual(chunk.law_name, "قانون مدنی")
            self.assertEqual(chunk.legal_status, "معتبر")
            self.assertIsNotNone(chunk.approval_date)
            self.assertEqual(chunk.legal_type, "article")
            self.assertEqual(chunk.hub_type, "legislation")

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_hub_type_is_legislation(self, mock_embed: MagicMock) -> None:
        """Verify all documents and chunks have hub_type='legislation'."""
        mock_embed.return_value = [_make_embedding()] * 4

        laws = [
            ("قانون الف", 2),
            ("قانون ب", 2),
        ]
        for law_name, num_chunks in laws:
            law_json = _make_law_json(
                law_name=law_name, num_chunks=num_chunks
            )
            self._write_json_file(f"{law_name}.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        # All documents
        for doc in Document.objects.filter(hub_type=LEGISLATION_HUB_TYPE):
            self.assertEqual(doc.hub_type, "legislation")

        # All chunks
        for chunk in DocumentChunk.objects.filter(
            hub_type=LEGISLATION_HUB_TYPE
        ):
            self.assertEqual(chunk.hub_type, "legislation")
            self.assertEqual(
                chunk.metadata.get("hub_type"), "legislation"
            )

    # ------------------------------------------------------------------
    # Embedding Tests
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_embeddings_generated(self, mock_embed: MagicMock) -> None:
        """Verify embeddings are created for all chunks."""
        mock_embed.return_value = [_make_embedding()] * 3

        law_json = _make_law_json(law_name="قانون تست", num_chunks=3)
        self._write_json_file("قانون_تست.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        chunks = DocumentChunk.objects.filter(
            document__title="قانون تست"
        ).order_by("chunk_index")

        for chunk in chunks:
            self.assertIsNotNone(chunk.embedding)
            self.assertEqual(len(chunk.embedding), EMBEDDING_DIM)

        # Verify mock was called
        mock_embed.assert_called_once()

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_skip_embedding_flag(self, mock_embed: MagicMock) -> None:
        """Verify --skip-embedding skips embedding generation."""
        law_json = _make_law_json(law_name="قانون تست", num_chunks=3)
        self._write_json_file("قانون_تست.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            "--skip-embedding",
            stdout=out,
        )

        chunks = DocumentChunk.objects.filter(
            document__title="قانون تست"
        ).order_by("chunk_index")

        for chunk in chunks:
            self.assertIsNone(chunk.embedding)

        # Verify mock was NOT called
        mock_embed.assert_not_called()

        # Verify output mentions skip
        output = out.getvalue()
        self.assertIn("skip-embedding", output.lower())

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_embedding_batch_size(self, mock_embed: MagicMock) -> None:
        """Verify custom batch size is respected."""
        mock_embed.return_value = [_make_embedding()] * 5

        law_json = _make_law_json(law_name="قانون تست", num_chunks=5)
        self._write_json_file("قانون_تست.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            "--embedding-batch-size=2",
            stdout=out,
        )

        # With batch size 2 and 5 chunks, mock should be called 3 times
        # (batches of 2, 2, 1)
        self.assertEqual(mock_embed.call_count, 3)

    # ------------------------------------------------------------------
    # Dry-Run Tests
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_dry_run_no_changes(self, mock_embed: MagicMock) -> None:
        """Verify dry-run mode doesn't modify the database."""
        # Setup existing legislation data
        _setup_legislation_data(num_docs=1, chunks_per_doc=2)

        law_json = _make_law_json(law_name="قانون تست", num_chunks=3)
        self._write_json_file("قانون_تست.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            "--dry-run",
            stdout=out,
        )

        # Verify existing data is still there (not purged)
        self.assertEqual(
            Document.objects.filter(hub_type=LEGISLATION_HUB_TYPE).count(), 1
        )

        # Verify no new documents were created
        self.assertFalse(
            Document.objects.filter(title="قانون تست").exists()
        )

        # Verify mock was NOT called (no embedding in dry-run)
        mock_embed.assert_not_called()

        # Verify output mentions DRY-RUN
        output = out.getvalue()
        self.assertIn("DRY-RUN", output)

    # ------------------------------------------------------------------
    # Error Handling Tests
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_missing_text_field_validation(self, mock_embed: MagicMock) -> None:
        """Verify error on chunks without text field."""
        # Create a file with one valid chunk and one without text
        chunks = [
            _make_law_chunk(law_name="قانون تست", madde_number=1),
            {
                "chunk_id": "bad_chunk",
                "madde_number": 2,
                "text": "",  # Empty text
                "metadata": {"source": "قانون تست", "hub_type": "legislation"},
            },
            {
                "chunk_id": "no_text_chunk",
                "madde_number": 3,
                # No 'text' field at all
                "metadata": {"source": "قانون تست", "hub_type": "legislation"},
            },
        ]
        self._write_json_file(
            "partial.json", json.dumps(chunks, ensure_ascii=False)
        )

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "reimport_legislation_hub",
                f"--data-dir={self.temp_dir}",
                "--skip-embedding",
                stdout=out,
            )

        # Only the valid chunk should have been imported
        doc = Document.objects.filter(title="قانون تست").first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.total_chunks, 1)

        # Verify errors were reported
        output = out.getvalue()
        self.assertIn("missing the 'text' field", output)

    def test_invalid_json_handling(self) -> None:
        """Verify graceful handling of corrupt JSON files."""
        # Write invalid JSON
        self._write_json_file("corrupt.json", "{invalid json content")

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "reimport_legislation_hub",
                f"--data-dir={self.temp_dir}",
                "--skip-embedding",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Failed to read", output)

    def test_empty_directory(self) -> None:
        """Verify graceful handling of empty data-dir."""
        # Temp dir is empty
        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            "--skip-embedding",
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("No JSON files found", output)

    def test_nonexistent_directory(self) -> None:
        """Verify error on non-existent data-dir."""
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "reimport_legislation_hub",
                "--data-dir=/nonexistent/path",
                "--skip-embedding",
            )
        self.assertIn("not found", str(ctx.exception))

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_not_a_list_format(self, mock_embed: MagicMock) -> None:
        """Verify error when JSON is not a flat array."""
        # Write a JSON object instead of array
        self._write_json_file(
            "object.json",
            json.dumps(
                {"source_file": "test.json", "chunks": []},
                ensure_ascii=False,
            ),
        )

        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "reimport_legislation_hub",
                f"--data-dir={self.temp_dir}",
                "--skip-embedding",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("expected a JSON array", output)

    # ------------------------------------------------------------------
    # Idempotency Test
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_idempotency_re_run(self, mock_embed: MagicMock) -> None:
        """Verify re-running is safe (purge + re-import)."""
        mock_embed.return_value = [_make_embedding()] * 3

        law_json = _make_law_json(law_name="قانون تست", num_chunks=3)
        self._write_json_file("قانون_تست.json", law_json)

        # First run
        out1 = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out1,
        )

        # Verify first run created data
        self.assertEqual(
            Document.objects.filter(title="قانون تست").count(), 1
        )
        first_doc_id = Document.objects.get(title="قانون تست").id

        # Second run (re-import)
        out2 = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out2,
        )

        # Verify old document is gone (new one has different ID)
        self.assertFalse(
            Document.objects.filter(id=first_doc_id).exists()
        )

        # Verify new document exists
        self.assertEqual(
            Document.objects.filter(title="قانون تست").count(), 1
        )
        self.assertEqual(
            DocumentChunk.objects.filter(
                document__title="قانون تست"
            ).count(),
            3,
        )

    # ------------------------------------------------------------------
    # Metadata Preservation Test
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_metadata_preserved_in_chunks(self, mock_embed: MagicMock) -> None:
        """Verify all metadata fields are preserved in chunk metadata."""
        mock_embed.return_value = [_make_embedding()] * 1

        chunk = _make_law_chunk(
            law_name="قانون تست",
            madde_number=1,
            chunk_id_suffix="test",
        )
        self._write_json_file(
            "test.json", json.dumps([chunk], ensure_ascii=False)
        )

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        db_chunk = DocumentChunk.objects.filter(
            document__title="قانون تست"
        ).first()
        self.assertIsNotNone(db_chunk)

        meta = db_chunk.metadata
        self.assertEqual(meta.get("source"), "قانون تست")
        self.assertEqual(meta.get("hub_type"), "legislation")
        self.assertEqual(meta.get("approval_date"), "1392/02/01")
        self.assertEqual(meta.get("status"), "معتبر")
        self.assertEqual(meta.get("chunk_id"), chunk["chunk_id"])
        self.assertEqual(meta.get("madde_number"), 1)

    # ------------------------------------------------------------------
    # User Assignment Test
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_custom_user_id(self, mock_embed: MagicMock) -> None:
        """Verify --user-id assigns documents to the specified user."""
        mock_embed.return_value = [_make_embedding()] * 2

        # Create a non-superuser
        custom_user = User.objects.create_user(
            email="custom@test.com",
            password="custompass123",
            is_active=True,
        )

        law_json = _make_law_json(law_name="قانون تست", num_chunks=2)
        self._write_json_file("قانون_تست.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            f"--user-id={custom_user.id}",
            stdout=out,
        )

        doc = Document.objects.get(title="قانون تست")
        self.assertEqual(doc.user.id, custom_user.id)

    # ------------------------------------------------------------------
    # No Existing Data Test
    # ------------------------------------------------------------------

    @patch(
        "documents.management.commands.reimport_legislation_hub.batch_generate_embeddings"
    )
    def test_no_existing_data(self, mock_embed: MagicMock) -> None:
        """Verify command works when there's no existing legislation data."""
        mock_embed.return_value = [_make_embedding()] * 3

        law_json = _make_law_json(law_name="قانون تست", num_chunks=3)
        self._write_json_file("قانون_تست.json", law_json)

        out = StringIO()
        call_command(
            "reimport_legislation_hub",
            f"--data-dir={self.temp_dir}",
            stdout=out,
        )

        self.assertEqual(
            Document.objects.filter(title="قانون تست").count(), 1
        )
        self.assertEqual(
            DocumentChunk.objects.filter(
                document__title="قانون تست"
            ).count(),
            3,
        )

        output = out.getvalue()
        self.assertIn("No existing legislation data found", output)
