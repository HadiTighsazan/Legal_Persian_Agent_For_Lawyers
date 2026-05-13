"""
Management command to import Persian reference legal texts into the system.

This command reads JSON files from a configured data directory and creates
:class:`~documents.models.Document` and :class:`~documents.models.DocumentChunk`
records for each reference law, assigning them to the appropriate legal
knowledge hub (``legislation``, ``judicial_precedent``, or
``advisory_opinion``).

Usage::

    # Import all JSON files from the default data directory
    python manage.py import_reference_laws

    # Import a specific file
    python manage.py import_reference_laws --file /data/legislation.json

    # Dry-run mode (validate without writing)
    python manage.py import_reference_laws --dry-run

Expected JSON format per file::

    {
        "hub_type": "legislation",
        "documents": [
            {
                "title": "قانون مجازات اسلامی",
                "filename": "qanoon_mojazat_islami.pdf",
                "content": "... full text ...",
                "metadata": {
                    "law_name": "قانون مجازات اسلامی",
                    "legal_status": "جاری",
                    "approval_date": "1392-01-01",
                    "legal_type": "قانون"
                }
            }
        ]
    }
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from documents.models import Document, DocumentChunk
from documents.services.anchor_chunking_service import AnchorChunkingService
from documents.services.embedding_service import batch_generate_embeddings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR = "/data/reference_laws"

VALID_HUB_TYPES = frozenset({"legislation", "judicial_precedent", "advisory_opinion"})

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ImportStats:
    """Aggregate statistics for an import run."""

    files_processed: int = 0
    documents_created: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    """Import Persian reference legal texts into the system."""

    help = "Import Persian reference legal texts (legislation, judicial precedent, advisory opinions)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--data-dir",
            type=str,
            default=DEFAULT_DATA_DIR,
            help=f"Directory containing JSON files (default: {DEFAULT_DATA_DIR}).",
        )
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Path to a single JSON file to import (overrides --data-dir).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate input files without writing to the database.",
        )
        parser.add_argument(
            "--user-id",
            type=str,
            default=None,
            help="UUID of the user to assign as owner of imported documents. "
                 "If not provided, uses the first superuser.",
        )

    def handle(self, *args: Any, **options: Any) -> str | None:
        data_dir: str = options["data_dir"]
        single_file: str | None = options["file"]
        dry_run: bool = options["dry_run"]
        user_id: str | None = options["user_id"]

        # ------------------------------------------------------------------
        # Resolve files to process
        # ------------------------------------------------------------------
        if single_file:
            if not os.path.isfile(single_file):
                raise CommandError(f"File not found: {single_file}")
            file_paths = [single_file]
        else:
            if not os.path.isdir(data_dir):
                raise CommandError(f"Data directory not found: {data_dir}")
            file_paths = sorted(
                os.path.join(data_dir, f)
                for f in os.listdir(data_dir)
                if f.endswith(".json")
            )
            if not file_paths:
                self.stdout.write(self.style.WARNING(f"No JSON files found in {data_dir}"))
                return

        # ------------------------------------------------------------------
        # Resolve owner user
        # ------------------------------------------------------------------
        if user_id:
            from users.models import User
            try:
                owner = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise CommandError(f"User with id={user_id} not found.")
        else:
            owner = self._get_default_owner()

        # ------------------------------------------------------------------
        # Process each file
        # ------------------------------------------------------------------
        stats = ImportStats()
        chunking_service = AnchorChunkingService()

        for file_path in file_paths:
            self._process_file(
                file_path=file_path,
                owner=owner,
                dry_run=dry_run,
                stats=stats,
                chunking_service=chunking_service,
            )

        # ------------------------------------------------------------------
        # Report
        # ------------------------------------------------------------------
        self._report(stats, dry_run)

        if stats.errors:
            raise CommandError(
                f"Import completed with {len(stats.errors)} error(s). "
                f"See logs for details."
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_default_owner(self):
        """Return the first active superuser as the default document owner."""
        from users.models import User
        user = User.objects.filter(is_superuser=True, is_active=True).first()
        if not user:
            raise CommandError(
                "No superuser found. Create a superuser first or pass --user-id."
            )
        return user

    def _process_file(
        self,
        file_path: str,
        owner: Any,
        dry_run: bool,
        stats: ImportStats,
        chunking_service: AnchorChunkingService,
    ) -> None:
        """Process a single JSON file containing reference law documents."""
        self.stdout.write(f"Processing: {file_path}")

        try:
            with open(file_path, encoding="utf-8") as f:
                data: dict = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            msg = f"Failed to read {file_path}: {e}"
            logger.error(msg)
            stats.errors.append(msg)
            return

        # Validate top-level structure
        hub_type = data.get("hub_type")
        if hub_type not in VALID_HUB_TYPES:
            msg = (
                f"{file_path}: invalid or missing 'hub_type'. "
                f"Must be one of {sorted(VALID_HUB_TYPES)}."
            )
            logger.error(msg)
            stats.errors.append(msg)
            return

        documents_data = data.get("documents", [])
        if not documents_data:
            self.stdout.write(self.style.WARNING(f"{file_path}: no documents in file."))
            stats.skipped.append(file_path)
            return

        stats.files_processed += 1

        for doc_data in documents_data:
            self._process_document(
                doc_data=doc_data,
                hub_type=hub_type,
                owner=owner,
                dry_run=dry_run,
                stats=stats,
                chunking_service=chunking_service,
            )

    def _process_document(
        self,
        doc_data: dict,
        hub_type: str,
        owner: Any,
        dry_run: bool,
        stats: ImportStats,
        chunking_service: AnchorChunkingService,
    ) -> None:
        """Process a single document entry from a JSON file."""
        title = doc_data.get("title", "").strip()
        content = doc_data.get("content", "").strip()
        filename = doc_data.get("filename", f"{title}.txt")
        metadata: dict = doc_data.get("metadata", {})

        if not title:
            stats.errors.append("Skipping document with empty title.")
            return
        if not content:
            stats.errors.append(f"Skipping '{title}': empty content.")
            return

        # ------------------------------------------------------------------
        # Chunk the text
        # ------------------------------------------------------------------
        try:
            chunk_results = chunking_service.chunk_text(content)
        except Exception as e:
            msg = f"Chunking failed for '{title}': {e}"
            logger.exception(msg)
            stats.errors.append(msg)
            return

        if not chunk_results:
            msg = f"'{title}': chunking produced zero chunks (empty text?)."
            stats.errors.append(msg)
            return

        # ------------------------------------------------------------------
        # Generate embeddings (skip in dry-run mode)
        # ------------------------------------------------------------------
        embeddings: list[list[float] | None] | None = None
        if not dry_run:
            try:
                texts = [r.content for r in chunk_results]
                embeddings = batch_generate_embeddings(texts)
            except Exception as e:
                msg = f"Embedding generation failed for '{title}': {e}"
                logger.exception(msg)
                stats.errors.append(msg)
                return

        # ------------------------------------------------------------------
        # Dry-run: just report
        # ------------------------------------------------------------------
        if dry_run:
            self.stdout.write(
                f"  [DRY-RUN] Would create: '{title}' "
                f"(hub={hub_type}, chunks={len(chunk_results)})"
            )
            stats.documents_created += 1
            stats.chunks_created += len(chunk_results)
            return

        # ------------------------------------------------------------------
        # Create Document + Chunks (atomic)
        # ------------------------------------------------------------------
        try:
            with transaction.atomic():
                document = Document.objects.create(
                    user=owner,
                    title=title,
                    filename=filename,
                    original_filename=filename,
                    file_path="",
                    file_size=len(content.encode("utf-8")),
                    mime_type="text/plain",
                    storage_type="local",
                    status="completed",
                    document_type="reference_law",
                    hub_type=hub_type,
                    processing_status="completed",
                    total_chunks=len(chunk_results),
                    extracted_text_length=len(content),
                    extracted_text=content,
                    extraction_method="import",
                )

                chunks_to_create: list[DocumentChunk] = []
                for idx, chunk_result in enumerate(chunk_results):
                    embedding = embeddings[idx] if embeddings else None
                    chunk = DocumentChunk(
                        document=document,
                        chunk_index=idx,
                        page_start=min(chunk_result.pages) if chunk_result.pages else 1,
                        page_end=max(chunk_result.pages) if chunk_result.pages else 1,
                        content=chunk_result.content,
                        token_count=chunk_result.token_count,
                        embedding=embedding,
                        hub_type=hub_type,
                        metadata={
                            **(chunk_result.metadata or {}),
                            **metadata,
                            "hub_type": hub_type,
                        },
                        law_name=metadata.get("law_name"),
                        legal_status=metadata.get("legal_status"),
                        approval_date=metadata.get("approval_date"),
                        legal_type=metadata.get("legal_type"),
                    )
                    chunks_to_create.append(chunk)

                DocumentChunk.objects.bulk_create(chunks_to_create)

                embedded_count = sum(
                    1 for e in (embeddings or []) if e is not None
                )

                stats.documents_created += 1
                stats.chunks_created += len(chunks_to_create)
                stats.chunks_embedded += embedded_count

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ '{title}' — {len(chunks_to_create)} chunks "
                        f"({embedded_count} embedded)"
                    )
                )

        except Exception as e:
            msg = f"Database error for '{title}': {e}"
            logger.exception(msg)
            stats.errors.append(msg)

    def _report(self, stats: ImportStats, dry_run: bool) -> None:
        """Print a summary of the import run."""
        mode = " [DRY-RUN]" if dry_run else ""
        self.stdout.write("=" * 60)
        self.stdout.write(f"Import Summary{mode}")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Files processed:     {stats.files_processed}")
        self.stdout.write(f"  Documents created:   {stats.documents_created}")
        self.stdout.write(f"  Chunks created:      {stats.chunks_created}")
        self.stdout.write(f"  Chunks embedded:     {stats.chunks_embedded}")
        if stats.errors:
            self.stdout.write(self.style.ERROR(f"  Errors:              {len(stats.errors)}"))
            for err in stats.errors[:5]:
                self.stdout.write(f"    - {err}")
        if stats.skipped:
            self.stdout.write(self.style.WARNING(f"  Skipped:             {len(stats.skipped)}"))
        self.stdout.write("=" * 60)
