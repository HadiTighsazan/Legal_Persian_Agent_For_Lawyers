"""
Management command to import pre-chunked Persian legal datasets into the system.

This command is designed specifically for the **pre-chunked JSON datasets**
produced by the Phase 2a chunking pipeline. Unlike ``import_reference_laws``
(which accepts raw text and re-chunks it), this command ingests data that is
**already chunked** and simply needs to be stored in the
:class:`~documents.models.Document` and :class:`~documents.models.DocumentChunk`
tables with embeddings generated.

The command supports three data formats (auto-detected):

**Format A** (Legislation hub — object with ``chunks`` array)::

    {
        "source_file": "قانون مجازات اسلامی.json",
        "total_chunks": 1018,
        "chunks": [
            {
                "chunk_id": "madde_1_اول_ـ_كليات",
                "madde_number": 1,
                "madde_raw": "ماده 1 ...",
                "text": "ماده 1 ...",
                "metadata": {
                    "source": "قانون مجازات اسلامي",
                    "hub_type": "legislation",
                    ...
                }
            }
        ]
    }

**Format B** (Precedent hub — flat array with ``hub_type`` in metadata)::

    [
        {
            "text": "رای شماره ...",
            "chunk_type": "header",
            "full_title": "...",
            "metadata": {
                "hub_type": "precedent",
                ...
            }
        }
    ]

**Format C** (Advisory hub — flat array, no ``hub_type`` in metadata)::

    [
        {
            "chunk_id": "7/1403/878_metadata",
            "text": "نظریه مشورتی شماره ...",
            "chunk_type": "metadata",
            ...
        }
    ]

Folder-to-Hub Mapping
---------------------
The command maps subdirectory names under ``--data-dir`` to hub types::

    "هاب قوانین مصوب"              → "legislation"
    "هاب رویه های قضایی"           → "judicial_precedent"
    "هاب نظریات مشورتی و رویه عملی" → "advisory_opinion"

Hub Type Normalization
----------------------
The ``"precedent"`` value in metadata is normalised to ``"judicial_precedent"``.

Usage::

    # Ingest all 6 files from the chunked_datasets directory
    python manage.py import_chunked_data --data-dir /data/chunked_datasets

    # Dry-run to preview
    python manage.py import_chunked_data --data-dir /data/chunked_datasets --dry-run

    # Specify owner user
    python manage.py import_chunked_data --data-dir /data/chunked_datasets \\
        --user-id <UUID>

    # Custom embedding batch size (default 16 for bge-m3 on 4GB VRAM)
    python manage.py import_chunked_data --data-dir /data/chunked_datasets \\
        --embedding-batch-size 32
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
from documents.services.embedding_service import batch_generate_embeddings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Folder name → hub_type mapping
FOLDER_HUB_MAP: dict[str, str] = {
    "هاب قوانین مصوب": "legislation",
    "هاب رویه های قضایی": "judicial_precedent",
    "هاب نظریات مشورتی و رویه عملی": "advisory_opinion",
}

# Hub type aliases for normalisation
HUB_TYPE_ALIASES: dict[str, str] = {
    "precedent": "judicial_precedent",
    "judicial_precedent": "judicial_precedent",
    "legislation": "legislation",
    "advisory_opinion": "advisory_opinion",
    "advisory": "advisory_opinion",
}

VALID_HUB_TYPES: frozenset[str] = frozenset(HUB_TYPE_ALIASES.keys())

# Default embedding batch size (conservative for bge-m3 on 4GB VRAM)
DEFAULT_EMBEDDING_BATCH_SIZE: int = 16

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
    """Import pre-chunked Persian legal datasets into the system."""

    help = (
        "Import pre-chunked Persian legal datasets (legislation, judicial "
        "precedent, advisory opinions) from a directory of JSON files."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--data-dir",
            type=str,
            required=True,
            help="Root directory containing subdirectories with chunked JSON files.",
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
        parser.add_argument(
            "--embedding-batch-size",
            type=int,
            default=DEFAULT_EMBEDDING_BATCH_SIZE,
            help=f"Batch size for embedding generation (default: {DEFAULT_EMBEDDING_BATCH_SIZE}).",
        )

    def handle(self, *args: Any, **options: Any) -> str | None:
        data_dir: str = options["data_dir"]
        dry_run: bool = options["dry_run"]
        user_id: str | None = options["user_id"]
        embedding_batch_size: int = options["embedding_batch_size"]

        # ------------------------------------------------------------------
        # Validate data directory
        # ------------------------------------------------------------------
        if not os.path.isdir(data_dir):
            raise CommandError(f"Data directory not found: {data_dir}")

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
        # Discover files grouped by subdirectory
        # ------------------------------------------------------------------
        file_groups: list[tuple[str, str, list[str]]] = []
        # (folder_name, hub_type, [file_paths])

        for entry_name in sorted(os.listdir(data_dir)):
            entry_path = os.path.join(data_dir, entry_name)
            if not os.path.isdir(entry_path):
                # Skip loose files at the root; only process subdirectories
                continue

            hub_type = FOLDER_HUB_MAP.get(entry_name)
            if hub_type is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping unknown folder '{entry_name}' — "
                        f"not in FOLDER_HUB_MAP."
                    )
                )
                continue

            json_files = sorted(
                os.path.join(entry_path, f)
                for f in os.listdir(entry_path)
                if f.endswith(".json")
            )
            if not json_files:
                self.stdout.write(
                    self.style.WARNING(
                        f"No JSON files found in '{entry_name}'."
                    )
                )
                continue

            file_groups.append((entry_name, hub_type, json_files))

        if not file_groups:
            self.stdout.write(
                self.style.WARNING(
                    f"No recognised hub subdirectories found in {data_dir}. "
                    f"Expected one of: {list(FOLDER_HUB_MAP.keys())}"
                )
            )
            return

        # ------------------------------------------------------------------
        # Process each file group
        # ------------------------------------------------------------------
        stats = ImportStats()

        for folder_name, hub_type, file_paths in file_groups:
            self.stdout.write(
                f"\n{'=' * 60}\n"
                f"Folder: {folder_name} → hub_type: {hub_type}\n"
                f"{'=' * 60}"
            )
            for file_path in file_paths:
                self._process_file(
                    file_path=file_path,
                    folder_hub_type=hub_type,
                    owner=owner,
                    dry_run=dry_run,
                    stats=stats,
                    embedding_batch_size=embedding_batch_size,
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

    def _normalize_hub_type(self, raw: str | None) -> str | None:
        """Normalise a hub type value using the alias map.

        Returns ``None`` if the value is not recognised.
        """
        if raw is None:
            return None
        return HUB_TYPE_ALIASES.get(raw)

    def _detect_format(self, data: Any) -> str:
        """Detect the format of the loaded JSON data.

        Returns:
            ``"format_a"`` for legislation-style (object with ``chunks`` key).
            ``"format_b"`` for flat array (precedent / advisory).

        Raises:
            ValueError: If the data format is not recognised.
        """
        if isinstance(data, dict) and "chunks" in data:
            return "format_a"
        elif isinstance(data, list):
            return "format_b"
        else:
            raise ValueError(
                "Unknown data format: expected a dict with 'chunks' key "
                "or a list of chunk objects."
            )

    def _chunk_exists(self, chunk_id: str) -> bool:
        """Check if a chunk with the given ``chunk_id`` already exists.

        Idempotency check: looks up ``metadata__chunk_id`` on
        :class:`DocumentChunk`.
        """
        return DocumentChunk.objects.filter(
            metadata__chunk_id=chunk_id
        ).exists()

    def _process_file(
        self,
        file_path: str,
        folder_hub_type: str,
        owner: Any,
        dry_run: bool,
        stats: ImportStats,
        embedding_batch_size: int,
    ) -> None:
        """Process a single JSON file containing pre-chunked data."""
        self.stdout.write(f"\nProcessing: {file_path}")

        try:
            with open(file_path, encoding="utf-8") as f:
                data: Any = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            msg = f"Failed to read {file_path}: {e}"
            logger.error(msg)
            stats.errors.append(msg)
            return

        # Detect format
        try:
            fmt = self._detect_format(data)
        except ValueError as e:
            msg = f"{file_path}: {e}"
            logger.error(msg)
            stats.errors.append(msg)
            return

        # Extract chunks list based on format
        if fmt == "format_a":
            chunks_data: list[dict[str, Any]] = data.get("chunks", [])
            source_file_name: str = data.get("source_file", os.path.basename(file_path))
        else:
            chunks_data = data
            source_file_name = os.path.basename(file_path)

        if not chunks_data:
            self.stdout.write(
                self.style.WARNING(f"{file_path}: no chunks in file.")
            )
            stats.skipped.append(file_path)
            return

        stats.files_processed += 1

        # ------------------------------------------------------------------
        # Group chunks into logical documents
        # ------------------------------------------------------------------
        # For Format A: all chunks belong to one document (the source file)
        # For Format B: group by full_title
        # For Format C: group by parent_title
        # ------------------------------------------------------------------
        doc_groups: dict[str, list[dict[str, Any]]] = {}

        if fmt == "format_a":
            doc_title = source_file_name.replace(".json", "")
            doc_groups[doc_title] = chunks_data
        else:
            for chunk in chunks_data:
                title_key = (
                    chunk.get("full_title")
                    or chunk.get("parent_title")
                    or "Unknown Document"
                )
                doc_groups.setdefault(title_key, []).append(chunk)

        # ------------------------------------------------------------------
        # Process each document group
        # ------------------------------------------------------------------
        for doc_title, doc_chunks in doc_groups.items():
            self._process_document_group(
                doc_title=doc_title,
                chunks_data=doc_chunks,
                folder_hub_type=folder_hub_type,
                owner=owner,
                dry_run=dry_run,
                stats=stats,
                embedding_batch_size=embedding_batch_size,
                fmt=fmt,
            )

    def _process_document_group(
        self,
        doc_title: str,
        chunks_data: list[dict[str, Any]],
        folder_hub_type: str,
        owner: Any,
        dry_run: bool,
        stats: ImportStats,
        embedding_batch_size: int,
        fmt: str,
    ) -> None:
        """Process a group of chunks that form a logical document."""
        # ------------------------------------------------------------------
        # Extract hub_type from first chunk's metadata (with fallback)
        # ------------------------------------------------------------------
        first_chunk = chunks_data[0]
        metadata: dict[str, Any] = first_chunk.get("metadata", {})
        raw_hub_type = metadata.get("hub_type", folder_hub_type)
        hub_type = self._normalize_hub_type(raw_hub_type) or folder_hub_type

        # ------------------------------------------------------------------
        # Extract document title from metadata
        # ------------------------------------------------------------------
        title = metadata.get("source") or doc_title

        # ------------------------------------------------------------------
        # Validate chunks have text field
        # ------------------------------------------------------------------
        for chunk in chunks_data:
            text = chunk.get("text", "").strip()
            if not text:
                msg = (
                    f"Chunk in '{title}' is missing the 'text' field "
                    f"(chunk_id={chunk.get('chunk_id', 'unknown')}). "
                    f"Skipping document group."
                )
                logger.error(msg)
                stats.errors.append(msg)
                return

        # ------------------------------------------------------------------
        # Idempotency check: skip if all chunks already exist
        # ------------------------------------------------------------------
        chunk_ids = [
            c.get("chunk_id") or f"{c.get('judgment_number', '')}_{c.get('chunk_type', '')}"
            for c in chunks_data
        ]
        existing_ids = [
            cid for cid in chunk_ids
            if cid and self._chunk_exists(cid)
        ]
        if existing_ids:
            self.stdout.write(
                self.style.WARNING(
                    f"  Skipping '{title}' — {len(existing_ids)} chunk(s) "
                    f"already exist (idempotency). Use --update to force."
                )
            )
            stats.skipped.append(title)
            return

        # ------------------------------------------------------------------
        # Extract texts for embedding
        # ------------------------------------------------------------------
        texts = [c["text"] for c in chunks_data]

        # ------------------------------------------------------------------
        # Generate embeddings (skip in dry-run mode)
        # ------------------------------------------------------------------
        embeddings: list[list[float] | None] | None = None
        if not dry_run:
            try:
                # Process in sub-batches to avoid VRAM OOM
                all_embeddings: list[list[float] | None] = []
                for i in range(0, len(texts), embedding_batch_size):
                    batch = texts[i:i + embedding_batch_size]
                    batch_embeddings = batch_generate_embeddings(batch)
                    all_embeddings.extend(batch_embeddings)
                embeddings = all_embeddings
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
                f"(hub={hub_type}, chunks={len(chunks_data)})"
            )
            stats.documents_created += 1
            stats.chunks_created += len(chunks_data)
            return

        # ------------------------------------------------------------------
        # Create Document + Chunks (atomic per document group)
        # ------------------------------------------------------------------
        try:
            with transaction.atomic():
                # Build the content for the document (concatenate all chunks)
                full_content = "\n\n".join(texts)

                document = Document.objects.create(
                    user=owner,
                    title=title,
                    filename=f"{title}.txt",
                    original_filename=f"{title}.txt",
                    file_path="",
                    file_size=len(full_content.encode("utf-8")),
                    mime_type="text/plain",
                    storage_type="local",
                    status="completed",
                    document_type="reference_law",
                    hub_type=hub_type,
                    processing_status="completed",
                    total_chunks=len(chunks_data),
                    extracted_text_length=len(full_content),
                    extracted_text=full_content,
                    extraction_method="import_chunked",
                )

                chunks_to_create: list[DocumentChunk] = []
                for idx, chunk_data in enumerate(chunks_data):
                    embedding = embeddings[idx] if embeddings else None
                    chunk_text = chunk_data["text"]
                    chunk_metadata = chunk_data.get("metadata", {}).copy()

                    # Ensure hub_type is in metadata
                    chunk_metadata["hub_type"] = hub_type

                    # Store original chunk_id in metadata for idempotency
                    chunk_id_val = chunk_data.get("chunk_id")
                    if chunk_id_val:
                        chunk_metadata["chunk_id"] = chunk_id_val

                    # Store chunk_type if present
                    chunk_type_val = chunk_data.get("chunk_type")
                    if chunk_type_val:
                        chunk_metadata["chunk_type"] = chunk_type_val

                    # Store judgment_number if present (Format B)
                    judgment_number = chunk_data.get("judgment_number")
                    if judgment_number:
                        chunk_metadata["judgment_number"] = judgment_number

                    # Store opinion_number if present (Format C)
                    opinion_number = chunk_data.get("opinion_number")
                    if opinion_number:
                        chunk_metadata["opinion_number"] = opinion_number

                    # Store section_name if present (Format B)
                    section_name = chunk_data.get("section_name")
                    if section_name:
                        chunk_metadata["section_name"] = section_name

                    # Store full_title if present (Format B)
                    full_title = chunk_data.get("full_title")
                    if full_title:
                        chunk_metadata["full_title"] = full_title

                    # Store parent_title if present (Format C)
                    parent_title = chunk_data.get("parent_title")
                    if parent_title:
                        chunk_metadata["parent_title"] = parent_title

                    # Store url if present
                    url = chunk_data.get("url")
                    if url:
                        chunk_metadata["url"] = url

                    # Store position if present (Format C)
                    position = chunk_data.get("position")
                    if position is not None:
                        chunk_metadata["position"] = position

                    # Store record_index if present (Format C)
                    record_index = chunk_data.get("record_index")
                    if record_index is not None:
                        chunk_metadata["record_index"] = record_index

                    # Denormalised metadata fields
                    law_name = chunk_metadata.get("source")
                    legal_status = chunk_metadata.get("status")
                    approval_date_str = chunk_metadata.get("approval_date")

                    # Parse approval_date if present (format: YYYY/MM/DD or YYYY-MM-DD)
                    approval_date = None
                    if approval_date_str:
                        from datetime import datetime
                        try:
                            # Try YYYY/MM/DD first
                            approval_date = datetime.strptime(
                                approval_date_str.replace("-", "/"),
                                "%Y/%m/%d",
                            ).date()
                        except (ValueError, TypeError):
                            pass

                    chunk = DocumentChunk(
                        document=document,
                        chunk_index=idx,
                        page_start=1,
                        page_end=1,
                        content=chunk_text,
                        token_count=None,
                        embedding=embedding,
                        hub_type=hub_type,
                        metadata=chunk_metadata,
                        law_name=law_name,
                        legal_status=legal_status,
                        approval_date=approval_date,
                        legal_type=chunk_metadata.get("legal_type"),
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
            self.stdout.write(
                self.style.ERROR(f"  Errors:              {len(stats.errors)}")
            )
            for err in stats.errors[:5]:
                self.stdout.write(f"    - {err}")
        if stats.skipped:
            self.stdout.write(
                self.style.WARNING(f"  Skipped:             {len(stats.skipped)}")
            )
        self.stdout.write("=" * 60)
