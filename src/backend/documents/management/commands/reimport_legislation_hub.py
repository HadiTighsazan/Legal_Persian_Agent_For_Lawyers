"""
Management command to purge and re-import the legislation hub (هاب قوانین مصوب).

This command performs a **complete purge** of all existing legislation hub data
(``hub_type='legislation'``) and then **re-imports** from pre-chunked JSON files
that are already split into chunks and only need embedding.

The input JSON files must be **Format B** (flat array of chunk objects), where
each chunk has at least ``chunk_id``, ``text``, and ``metadata.source`` fields.
Chunks are grouped by ``metadata.source`` (the law name) — one Document per law.

Usage::

    # Dry-run (validate without writing)
    docker-compose exec backend python manage.py reimport_legislation_hub \\
        --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \\
        --dry-run

    # Actual import
    docker-compose exec backend python manage.py reimport_legislation_hub \\
        --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws

    # Skip embedding (for testing)
    docker-compose exec backend python manage.py reimport_legislation_hub \\
        --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \\
        --skip-embedding

    # Custom embedding batch size
    docker-compose exec backend python manage.py reimport_legislation_hub \\
        --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \\
        --embedding-batch-size 32

    # Specify owner user
    docker-compose exec backend python manage.py reimport_legislation_hub \\
        --data-dir /data/chunked_datasets/هاب قوانین مصوب/laws \\
        --user-id <UUID>
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from documents.models import Document, DocumentChunk
from documents.services.embedding_service import batch_generate_embeddings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The only hub type this command operates on
LEGISLATION_HUB_TYPE: str = "legislation"

# Default embedding batch size (conservative for bge-m3 on 4GB VRAM)
# Matches EMBEDDING_SUB_BATCH_SIZE in providers/base.py
DEFAULT_EMBEDDING_BATCH_SIZE: int = 8


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ReimportStats:
    """Aggregate statistics for a reimport run."""

    # Purge phase
    documents_deleted: int = 0
    chunks_deleted: int = 0

    # Load phase
    files_found: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    total_chunks_loaded: int = 0

    # Import phase
    documents_created: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0

    # Errors / skips
    errors: list[str] = field(default_factory=list)
    skipped_documents: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    """Purge and re-import the legislation hub from pre-chunked JSON files."""

    help = (
        "Purge all existing legislation hub data and re-import from "
        "pre-chunked JSON files. Only operates on hub_type='legislation'."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--data-dir",
            type=str,
            required=True,
            help="Directory containing the pre-chunked JSON files for legislation.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Validate without making any changes to the database.",
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
        parser.add_argument(
            "--skip-embedding",
            action="store_true",
            default=False,
            help="Skip embedding generation (useful for testing).",
        )

    def handle(self, *args: Any, **options: Any) -> str | None:
        data_dir: str = options["data_dir"]
        dry_run: bool = options["dry_run"]
        user_id: str | None = options["user_id"]
        embedding_batch_size: int = options["embedding_batch_size"]
        skip_embedding: bool = options["skip_embedding"]

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

        stats = ReimportStats()

        # ------------------------------------------------------------------
        # Phase 1: Purge existing legislation data
        # ------------------------------------------------------------------
        self.stdout.write("=" * 60)
        self.stdout.write("Phase 1: Purge existing legislation data")
        self.stdout.write("=" * 60)
        self._purge_existing_legislation(stats=stats, dry_run=dry_run)

        # ------------------------------------------------------------------
        # Phase 2: Discover and load JSON files
        # ------------------------------------------------------------------
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Phase 2: Discover and load JSON files")
        self.stdout.write("=" * 60)

        json_files = sorted(
            os.path.join(data_dir, f)
            for f in os.listdir(data_dir)
            if f.endswith(".json")
        )
        stats.files_found = len(json_files)

        if not json_files:
            self.stdout.write(
                self.style.WARNING("No JSON files found in the data directory.")
            )
            self._report(stats, dry_run)
            if stats.errors:
                raise CommandError(
                    f"Reimport completed with {len(stats.errors)} error(s). "
                    f"See logs for details."
                )
            return

        self.stdout.write(f"Found {len(json_files)} JSON file(s).")

        # Load and validate all files
        all_chunks_data: list[dict[str, Any]] = []
        for file_path in json_files:
            file_chunks = self._load_file(file_path=file_path, stats=stats)
            if file_chunks is not None:
                all_chunks_data.extend(file_chunks)

        if not all_chunks_data:
            self.stdout.write(
                self.style.ERROR("No valid chunks loaded from any file. Aborting.")
            )
            self._report(stats, dry_run)
            if stats.errors:
                raise CommandError(
                    f"Reimport completed with {len(stats.errors)} error(s). "
                    f"See logs for details."
                )
            return

        stats.total_chunks_loaded = len(all_chunks_data)
        self.stdout.write(
            f"Loaded {len(all_chunks_data)} total chunks from "
            f"{stats.files_processed} file(s)."
        )

        # ------------------------------------------------------------------
        # Phase 3: Group chunks by law name (metadata.source)
        # ------------------------------------------------------------------
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Phase 3: Group chunks by law name")
        self.stdout.write("=" * 60)

        doc_groups: dict[str, list[dict[str, Any]]] = {}
        for chunk in all_chunks_data:
            metadata: dict[str, Any] = chunk.get("metadata", {})
            law_name = metadata.get("source")
            if not law_name:
                msg = (
                    f"Chunk {chunk.get('chunk_id', 'unknown')} is missing "
                    f"metadata.source. Skipping."
                )
                logger.warning(msg)
                stats.errors.append(msg)
                continue
            doc_groups.setdefault(law_name, []).append(chunk)

        self.stdout.write(
            f"Grouped into {len(doc_groups)} unique law document(s)."
        )

        # ------------------------------------------------------------------
        # Phase 4: Create Documents + Chunks
        # ------------------------------------------------------------------
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Phase 4: Create Documents and Chunks")
        self.stdout.write("=" * 60)

        # Collect all texts for embedding (across all documents)
        all_texts: list[str] = []
        all_chunks_for_embedding: list[DocumentChunk] = []

        for law_name, law_chunks in sorted(doc_groups.items()):
            self._import_law_group(
                law_name=law_name,
                chunks_data=law_chunks,
                owner=owner,
                dry_run=dry_run,
                stats=stats,
                all_texts=all_texts,
                all_chunks_for_embedding=all_chunks_for_embedding,
            )

        # ------------------------------------------------------------------
        # Phase 5: Generate embeddings
        # ------------------------------------------------------------------
        if not dry_run and not skip_embedding and all_chunks_for_embedding:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Phase 5: Generate embeddings")
            self.stdout.write("=" * 60)
            self._generate_embeddings(
                chunks=all_chunks_for_embedding,
                texts=all_texts,
                batch_size=embedding_batch_size,
                stats=stats,
            )
        elif dry_run:
            self.stdout.write(
                "\n  [DRY-RUN] Would generate embeddings for "
                f"{len(all_texts)} chunk(s)."
            )
        elif skip_embedding:
            self.stdout.write(
                "\n  Skipping embedding generation (--skip-embedding)."
            )

        # ------------------------------------------------------------------
        # Report
        # ------------------------------------------------------------------
        self._report(stats, dry_run)

        if stats.errors:
            raise CommandError(
                f"Reimport completed with {len(stats.errors)} error(s). "
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

    def _purge_existing_legislation(
        self,
        stats: ReimportStats,
        dry_run: bool,
    ) -> None:
        """Delete all documents with ``hub_type='legislation'``.

        CASCADE delete will remove all related chunks, conversations, and
        processing tasks.
        """
        docs_to_delete = Document.objects.filter(
            document_type="reference_law",
            hub_type=LEGISLATION_HUB_TYPE,
        )

        total_docs = docs_to_delete.count()
        total_chunks = DocumentChunk.objects.filter(
            document__in=docs_to_delete
        ).count()

        if total_docs == 0:
            self.stdout.write("  No existing legislation data found to purge.")
            return

        self.stdout.write(
            f"  Found {total_docs} document(s) with {total_chunks} chunk(s) "
            f"to delete."
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "  [DRY-RUN] Would delete the above documents and chunks."
                )
            )
            stats.documents_deleted = total_docs
            stats.chunks_deleted = total_chunks
            return

        # Perform the delete (CASCADE handles chunks, conversations, tasks)
        deleted_count, delete_details = docs_to_delete.delete()
        # delete_details is a dict like {'documents.DocumentChunk': 4612, 'documents.Document': 2}
        stats.documents_deleted = delete_details.get(
            f"{Document._meta.app_label}.{Document._meta.model_name}", 0
        )
        stats.chunks_deleted = delete_details.get(
            f"{DocumentChunk._meta.app_label}.{DocumentChunk._meta.model_name}", 0
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Purged {stats.documents_deleted} document(s) and "
                f"{stats.chunks_deleted} chunk(s)."
            )
        )

    def _load_file(
        self,
        file_path: str,
        stats: ReimportStats,
    ) -> list[dict[str, Any]] | None:
        """Load and validate a single JSON file.

        Returns:
            A list of chunk dicts, or ``None`` if the file could not be loaded.
        """
        filename = os.path.basename(file_path)
        self.stdout.write(f"\n  Loading: {filename}")

        try:
            with open(file_path, encoding="utf-8") as f:
                data: Any = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            msg = f"Failed to read {filename}: {e}"
            logger.error(msg)
            stats.errors.append(msg)
            return None

        # Validate it's a flat array (Format B)
        if not isinstance(data, list):
            msg = (
                f"{filename}: expected a JSON array (flat list of chunks), "
                f"got {type(data).__name__}. Skipping."
            )
            logger.error(msg)
            stats.errors.append(msg)
            return None

        # Validate each chunk has a 'text' field
        valid_chunks: list[dict[str, Any]] = []
        for chunk in data:
            text = chunk.get("text", "").strip()
            if not text:
                msg = (
                    f"{filename}: chunk {chunk.get('chunk_id', 'unknown')} "
                    f"is missing the 'text' field. Skipping chunk."
                )
                logger.warning(msg)
                stats.errors.append(msg)
                continue
            valid_chunks.append(chunk)

        if not valid_chunks:
            msg = f"{filename}: no valid chunks found after validation."
            logger.error(msg)
            stats.errors.append(msg)
            return None

        stats.files_processed += 1
        self.stdout.write(
            f"    {len(valid_chunks)} valid chunk(s) loaded."
        )
        return valid_chunks

    def _import_law_group(
        self,
        law_name: str,
        chunks_data: list[dict[str, Any]],
        owner: Any,
        dry_run: bool,
        stats: ReimportStats,
        all_texts: list[str],
        all_chunks_for_embedding: list[DocumentChunk],
    ) -> None:
        """Import a single law group as one Document with its Chunks.

        Args:
            law_name: The law name (from ``metadata.source``).
            chunks_data: List of chunk dicts belonging to this law.
            owner: The User to own the document.
            dry_run: If True, only report what would be done.
            stats: Accumulator for statistics.
            all_texts: Accumulator for all chunk texts (for later embedding).
            all_chunks_for_embedding: Accumulator for all chunk instances
                (for later embedding update).
        """
        # Sort chunks by chunk_index if available, otherwise by chunk_id
        chunks_data_sorted = sorted(
            chunks_data,
            key=lambda c: (
                c.get("metadata", {}).get("chunk_index", 0)
                if c.get("metadata", {}).get("chunk_index") is not None
                else c.get("madde_number", 0)
                if c.get("madde_number") is not None
                else 0
            ),
        )

        # Build the full content for the document (concatenated)
        texts = [c["text"] for c in chunks_data_sorted]
        full_content = "\n\n".join(texts)

        if dry_run:
            self.stdout.write(
                f"  [DRY-RUN] Would create: '{law_name}' "
                f"(chunks={len(chunks_data_sorted)})"
            )
            stats.documents_created += 1
            stats.chunks_created += len(chunks_data_sorted)
            all_texts.extend(texts)
            return

        try:
            with transaction.atomic():
                document = Document.objects.create(
                    user=owner,
                    title=law_name,
                    filename=f"{law_name}.txt",
                    original_filename=f"{law_name}.txt",
                    file_path="",
                    file_size=len(full_content.encode("utf-8")),
                    mime_type="text/plain",
                    storage_type="local",
                    status="completed",
                    document_type="reference_law",
                    hub_type=LEGISLATION_HUB_TYPE,
                    processing_status="completed",
                    total_chunks=len(chunks_data_sorted),
                    extracted_text_length=len(full_content),
                    extracted_text=full_content,
                    extraction_method="import_chunked",
                )

                chunks_to_create: list[DocumentChunk] = []
                for idx, chunk_data in enumerate(chunks_data_sorted):
                    chunk_text = chunk_data["text"]
                    chunk_metadata = chunk_data.get("metadata", {}).copy()

                    # Ensure hub_type is in metadata
                    chunk_metadata["hub_type"] = LEGISLATION_HUB_TYPE

                    # Store original chunk_id in metadata for idempotency
                    chunk_id_val = chunk_data.get("chunk_id")
                    if chunk_id_val:
                        chunk_metadata["chunk_id"] = chunk_id_val

                    # Store madde_number if present
                    madde_number = chunk_data.get("madde_number")
                    if madde_number is not None:
                        chunk_metadata["madde_number"] = madde_number

                    # Store madde_suffix if present
                    madde_suffix = chunk_data.get("madde_suffix")
                    if madde_suffix:
                        chunk_metadata["madde_suffix"] = madde_suffix

                    # Store madde_raw if present
                    madde_raw = chunk_data.get("madde_raw")
                    if madde_raw:
                        chunk_metadata["madde_raw"] = madde_raw

                    # Denormalised metadata fields
                    law_name_field = chunk_metadata.get("source")
                    legal_status = chunk_metadata.get("status")
                    approval_date_str = chunk_metadata.get("approval_date")

                    # Parse approval_date if present (format: YYYY/MM/DD or YYYY-MM-DD)
                    approval_date = None
                    if approval_date_str:
                        try:
                            approval_date = datetime.strptime(
                                approval_date_str.replace("-", "/"),
                                "%Y/%m/%d",
                            ).date()
                        except (ValueError, TypeError):
                            pass

                    # Determine legal_type from metadata
                    # These are law articles, so default to "article"
                    legal_type = chunk_metadata.get("legal_type", "article")

                    chunk = DocumentChunk(
                        document=document,
                        chunk_index=idx,
                        page_start=1,
                        page_end=1,
                        content=chunk_text,
                        token_count=None,
                        embedding=None,  # Will be set in Phase 5
                        hub_type=LEGISLATION_HUB_TYPE,
                        metadata=chunk_metadata,
                        law_name=law_name_field,
                        legal_status=legal_status,
                        approval_date=approval_date,
                        legal_type=legal_type,
                    )
                    chunks_to_create.append(chunk)

                DocumentChunk.objects.bulk_create(chunks_to_create)

                stats.documents_created += 1
                stats.chunks_created += len(chunks_to_create)

                # Accumulate for embedding phase
                all_texts.extend(texts)
                all_chunks_for_embedding.extend(chunks_to_create)

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ '{law_name}' — {len(chunks_to_create)} chunks created."
                    )
                )

        except Exception as e:
            msg = f"Database error for '{law_name}': {e}"
            logger.exception(msg)
            stats.errors.append(msg)
            stats.skipped_documents.append(law_name)

    def _generate_embeddings(
        self,
        chunks: list[DocumentChunk],
        texts: list[str],
        batch_size: int,
        stats: ReimportStats,
    ) -> None:
        """Generate embeddings for all chunks in batches."""
        if not chunks:
            self.stdout.write("  No chunks to embed.")
            return

        self.stdout.write(
            f"  Generating embeddings for {len(chunks)} chunk(s) "
            f"(batch size: {batch_size})..."
        )

        try:
            all_embeddings: list[list[float] | None] = []
            total_batches = (len(texts) + batch_size - 1) // batch_size

            for i in range(0, len(texts), batch_size):
                batch_num = (i // batch_size) + 1
                batch = texts[i:i + batch_size]
                self.stdout.write(
                    f"    Batch {batch_num}/{total_batches} "
                    f"({len(batch)} texts)..."
                )
                batch_embeddings = batch_generate_embeddings(batch)
                all_embeddings.extend(batch_embeddings)

            # Update embeddings in bulk
            updated_count = 0
            for chunk, embedding in zip(chunks, all_embeddings):
                if embedding is not None:
                    chunk.embedding = embedding
                    updated_count += 1

            DocumentChunk.objects.bulk_update(chunks, fields=["embedding"])

            stats.chunks_embedded = updated_count

            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Embedded {updated_count}/{len(chunks)} chunk(s)."
                )
            )

        except Exception as e:
            msg = f"Embedding generation failed: {e}"
            logger.exception(msg)
            stats.errors.append(msg)

    def _report(self, stats: ReimportStats, dry_run: bool) -> None:
        """Print a summary of the reimport run."""
        mode = " [DRY-RUN]" if dry_run else ""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Reimport Summary{mode}")
        self.stdout.write("=" * 60)

        # Purge phase
        self.stdout.write("\n  --- Purge ---")
        self.stdout.write(f"  Documents deleted:   {stats.documents_deleted}")
        self.stdout.write(f"  Chunks deleted:      {stats.chunks_deleted}")

        # Load phase
        self.stdout.write("\n  --- Load ---")
        self.stdout.write(f"  Files found:         {stats.files_found}")
        self.stdout.write(f"  Files processed:     {stats.files_processed}")
        self.stdout.write(f"  Total chunks loaded: {stats.total_chunks_loaded}")

        # Import phase
        self.stdout.write("\n  --- Import ---")
        self.stdout.write(f"  Documents created:   {stats.documents_created}")
        self.stdout.write(f"  Chunks created:      {stats.chunks_created}")
        self.stdout.write(f"  Chunks embedded:     {stats.chunks_embedded}")

        # Errors
        if stats.errors:
            self.stdout.write(
                self.style.ERROR(f"\n  Errors:              {len(stats.errors)}")
            )
            for err in stats.errors[:10]:
                self.stdout.write(f"    - {err}")
        if stats.skipped_documents:
            self.stdout.write(
                self.style.WARNING(
                    f"\n  Skipped documents:   {len(stats.skipped_documents)}"
                )
            )
            for name in stats.skipped_documents[:5]:
                self.stdout.write(f"    - {name}")

        self.stdout.write("\n" + "=" * 60)
