"""
Management command to audit and fix ``hub_type`` on reference law documents.

Detects documents whose ``hub_type`` does not match the expected value based
on the source folder structure, and optionally corrects them (including
denormalised ``hub_type`` on child chunks).

Modes
-----
``audit`` (default)
    Scan all ``reference_law`` documents and report mismatches without
    making any changes.  Exit code is 0 even if mismatches are found.

``fix``
    Correct ``hub_type`` on mismatched documents and their chunks.
    Also re-embeds chunks whose hub_type changed (optional).

``reembed``
    Re-embed all chunks for documents whose hub_type was fixed in a
    previous run (useful if you skipped re-embedding during ``fix``).

Usage
-----
::

    # Audit only (safe, no changes)
    docker-compose exec backend python manage.py fix_hub_types audit

    # Fix + re-embed
    docker-compose exec backend python manage.py fix_hub_types fix \\
        --reembed

    # Re-embed only (after a previous fix without --reembed)
    docker-compose exec backend python manage.py fix_hub_types reembed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from documents.models import Document, DocumentChunk
from documents.services.embedding_service import batch_generate_embeddings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hub type mapping (mirrors import_chunked_data.py)
# ---------------------------------------------------------------------------

# Folder name → hub_type mapping (used to determine expected hub_type)
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

# Reverse map: hub_type → list of known folder names (for reporting)
HUB_TO_FOLDERS: dict[str, list[str]] = {}
for folder, hub in FOLDER_HUB_MAP.items():
    HUB_TO_FOLDERS.setdefault(hub, []).append(folder)

# All valid hub types
VALID_HUB_TYPES: frozenset[str] = frozenset(HUB_TYPE_ALIASES.keys())

# Default embedding batch size
DEFAULT_EMBEDDING_BATCH_SIZE: int = 16


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FixStats:
    """Aggregate statistics for a fix_hub_types run."""

    documents_scanned: int = 0
    documents_matched: int = 0
    documents_mismatched: int = 0
    documents_fixed: int = 0
    chunks_fixed: int = 0
    chunks_reembedded: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_hub_type(raw: str | None) -> str | None:
    """Normalise a hub type value using the alias map.

    Returns ``None`` if the value is not recognised.
    """
    if raw is None:
        return None
    return HUB_TYPE_ALIASES.get(raw)


def _infer_expected_hub_type(document: Document) -> str | None:
    """Try to infer the expected ``hub_type`` for a reference law document.

    Strategy (in order of precedence):

    1. **Folder name from ``file_path``**: If the document was imported via
       :command:`import_chunked_data`, the ``file_path`` may contain the
       Persian folder name (e.g. ``هاب قوانین مصوب``).  We check if any
       known folder name appears in the path.

    2. **Metadata ``hub_type`` from first chunk**: If the document has
       chunks, check the first chunk's metadata for a ``hub_type`` value
       that normalises to a valid hub type.

    3. **Heuristic from title**: If the title contains keywords like
       ``قانون``, ``ماده``, ``اصلاحیه`` → ``legislation``.
       If it contains ``رأی``, ``دادنامه``, ``حکم`` → ``judicial_precedent``.
       If it contains ``نظریه``, ``استعلام`` → ``advisory_opinion``.

    Returns:
        The expected hub type string, or ``None`` if it cannot be inferred.
    """
    # Strategy 1: Check file_path for known folder names
    file_path = document.file_path or ""
    for folder_name, hub_type in FOLDER_HUB_MAP.items():
        if folder_name in file_path:
            return hub_type

    # Strategy 2: Check first chunk's metadata
    first_chunk = (
        DocumentChunk.objects.filter(document=document)
        .order_by("chunk_index")
        .first()
    )
    if first_chunk and first_chunk.metadata:
        meta_hub = first_chunk.metadata.get("hub_type")
        normalized = _normalize_hub_type(meta_hub)
        if normalized:
            return normalized

    # Strategy 3: Heuristic from title
    title = (document.title or "").lower()
    legislation_keywords = ["قانون", "ماده", "اصلاحیه", "آیین نامه", "مصوب"]
    precedent_keywords = ["رأی", "دادنامه", "حکم", "رای", "قضایی"]
    advisory_keywords = ["نظریه", "استعلام", "نظر", "مشورتی"]

    # Score each hub type
    scores: dict[str, int] = {
        "legislation": sum(1 for kw in legislation_keywords if kw in title),
        "judicial_precedent": sum(1 for kw in precedent_keywords if kw in title),
        "advisory_opinion": sum(1 for kw in advisory_keywords if kw in title),
    }

    best_hub = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best_hub] > 0:
        return best_hub

    return None


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    """Audit and fix ``hub_type`` on reference law documents."""

    help = (
        "Audit or fix hub_type on reference_law documents. "
        "Use 'audit' to scan without changes, 'fix' to correct mismatches, "
        "or 'reembed' to re-embed chunks after a fix."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "mode",
            type=str,
            choices=["audit", "fix", "reembed"],
            help="Operation mode: 'audit' (default, no changes), "
                 "'fix' (correct mismatches), "
                 "'reembed' (re-embed after fix).",
        )
        parser.add_argument(
            "--reembed",
            action="store_true",
            default=False,
            help="When used with 'fix', also re-embed chunks whose "
                 "hub_type changed.",
        )
        parser.add_argument(
            "--embedding-batch-size",
            type=int,
            default=DEFAULT_EMBEDDING_BATCH_SIZE,
            help=f"Batch size for embedding generation "
                 f"(default: {DEFAULT_EMBEDDING_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="In 'fix' mode, report what would be changed without "
                 "making any modifications.",
        )

    def handle(self, *args: Any, **options: Any) -> str | None:
        mode: str = options["mode"]
        reembed: bool = options["reembed"]
        embedding_batch_size: int = options["embedding_batch_size"]
        dry_run: bool = options["dry_run"]

        if mode == "audit":
            self._run_audit()
        elif mode == "fix":
            self._run_fix(
                reembed=reembed,
                embedding_batch_size=embedding_batch_size,
                dry_run=dry_run,
            )
        elif mode == "reembed":
            self._run_reembed(embedding_batch_size=embedding_batch_size)
        else:
            raise CommandError(f"Unknown mode: {mode}")

    # ------------------------------------------------------------------
    # Audit mode
    # ------------------------------------------------------------------

    def _run_audit(self) -> None:
        """Scan all reference_law documents and report hub_type mismatches."""
        stats = FixStats()

        docs = Document.objects.filter(document_type="reference_law").order_by(
            "title"
        )
        total = docs.count()
        self.stdout.write(f"Scanning {total} reference_law documents...\n")

        for doc in docs.iterator(chunk_size=200):
            stats.documents_scanned += 1
            expected = _infer_expected_hub_type(doc)
            actual = doc.hub_type

            if expected and actual != expected:
                stats.documents_mismatched += 1
                self._report_mismatch(doc, expected, actual)
            else:
                stats.documents_matched += 1

        self._print_audit_summary(stats, total)

    def _report_mismatch(
        self, doc: Document, expected: str, actual: str | None
    ) -> None:
        """Print a single mismatch report line."""
        chunk_count = doc.chunks.count()
        self.stdout.write(
            self.style.WARNING(
                f"  MISMATCH: {doc.title[:80]}"
            )
        )
        self.stdout.write(
            f"    id:       {doc.id}"
        )
        self.stdout.write(
            f"    expected: {expected}"
        )
        self.stdout.write(
            f"    actual:   {actual or '<None>'}"
        )
        self.stdout.write(
            f"    chunks:   {chunk_count}"
        )
        self.stdout.write("")

    def _print_audit_summary(self, stats: FixStats, total: int) -> None:
        """Print audit summary."""
        self.stdout.write("=" * 60)
        self.stdout.write("Audit Summary")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Documents scanned:  {stats.documents_scanned}")
        self.stdout.write(f"  Correct:            {stats.documents_matched}")
        if stats.documents_mismatched > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"  MISMATCHED:         {stats.documents_mismatched}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "  MISMATCHED:         0  ✓ All documents have correct hub_type"
                )
            )
        if stats.errors:
            self.stdout.write(
                self.style.ERROR(f"  Errors:             {len(stats.errors)}")
            )
            for err in stats.errors[:5]:
                self.stdout.write(f"    - {err}")

    # ------------------------------------------------------------------
    # Fix mode
    # ------------------------------------------------------------------

    def _run_fix(
        self,
        reembed: bool,
        embedding_batch_size: int,
        dry_run: bool,
    ) -> None:
        """Correct hub_type on mismatched documents and their chunks."""
        stats = FixStats()

        docs = Document.objects.filter(document_type="reference_law").order_by(
            "title"
        )
        total = docs.count()
        mode_label = " [DRY-RUN]" if dry_run else ""
        self.stdout.write(
            f"Scanning {total} reference_law documents for fix{mode_label}...\n"
        )

        mismatched_docs: list[tuple[Document, str]] = []

        for doc in docs.iterator(chunk_size=200):
            stats.documents_scanned += 1
            expected = _infer_expected_hub_type(doc)
            actual = doc.hub_type

            if expected and actual != expected:
                mismatched_docs.append((doc, expected))
                stats.documents_mismatched += 1
                self._report_mismatch(doc, expected, actual)
            else:
                stats.documents_matched += 1

        if not mismatched_docs:
            self.stdout.write(
                self.style.SUCCESS(
                    "No mismatches found. Nothing to fix."
                )
            )
            return

        self.stdout.write(
            f"\nFound {len(mismatched_docs)} mismatched document(s).\n"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "DRY-RUN: No changes were made. "
                    "Re-run without --dry-run to apply fixes."
                )
            )
            return

        # Apply fixes
        for doc, expected_hub in mismatched_docs:
            try:
                self._fix_document(
                    doc=doc,
                    expected_hub=expected_hub,
                    stats=stats,
                    reembed=reembed,
                    embedding_batch_size=embedding_batch_size,
                )
            except Exception as e:
                msg = f"Failed to fix document '{doc.title}' ({doc.id}): {e}"
                logger.exception(msg)
                stats.errors.append(msg)

        # Summary
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write("Fix Summary")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Documents scanned:  {stats.documents_scanned}")
        self.stdout.write(f"  Documents fixed:    {stats.documents_fixed}")
        self.stdout.write(f"  Chunks fixed:       {stats.chunks_fixed}")
        self.stdout.write(f"  Chunks re-embedded: {stats.chunks_reembedded}")
        if stats.errors:
            self.stdout.write(
                self.style.ERROR(f"  Errors:             {len(stats.errors)}")
            )
            for err in stats.errors[:5]:
                self.stdout.write(f"    - {err}")
        self.stdout.write(
            self.style.SUCCESS("\nFix complete. Run 'fix_hub_types audit' to verify.")
        )

    def _fix_document(
        self,
        doc: Document,
        expected_hub: str,
        stats: FixStats,
        reembed: bool,
        embedding_batch_size: int,
    ) -> None:
        """Fix hub_type on a single document and its chunks."""
        old_hub = doc.hub_type

        with transaction.atomic():
            # Update document hub_type
            doc.hub_type = expected_hub
            doc.save(update_fields=["hub_type"])

            # Update all chunks' hub_type
            chunks = list(
                doc.chunks.all().only("id", "hub_type", "embedding")
            )
            for chunk in chunks:
                chunk.hub_type = expected_hub
                # Also update metadata
                if chunk.metadata:
                    chunk.metadata["hub_type"] = expected_hub

            DocumentChunk.objects.bulk_update(
                chunks,
                fields=["hub_type", "metadata"],
            )

            stats.documents_fixed += 1
            stats.chunks_fixed += len(chunks)

            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Fixed: '{doc.title[:60]}' "
                    f"({old_hub} → {expected_hub}, "
                    f"{len(chunks)} chunks)"
                )
            )

        # Re-embed if requested (outside transaction to avoid long locks)
        if reembed and chunks:
            self._reembed_chunks(
                doc=doc,
                chunks=chunks,
                stats=stats,
                embedding_batch_size=embedding_batch_size,
            )

    # ------------------------------------------------------------------
    # Re-embed mode
    # ------------------------------------------------------------------

    def _run_reembed(self, embedding_batch_size: int) -> None:
        """Re-embed all chunks for documents whose hub_type was fixed."""
        stats = FixStats()

        # Find documents that were fixed (we track this via a simple heuristic:
        # documents where hub_type differs from what we'd infer)
        docs = Document.objects.filter(document_type="reference_law").order_by(
            "title"
        )
        total = docs.count()
        self.stdout.write(
            f"Scanning {total} reference_law documents for re-embedding...\n"
        )

        docs_to_reembed: list[Document] = []
        for doc in docs.iterator(chunk_size=200):
            expected = _infer_expected_hub_type(doc)
            if expected and doc.hub_type == expected:
                # This doc has the correct hub_type — check if chunks need
                # re-embedding (they might have been fixed but not re-embedded)
                docs_to_reembed.append(doc)

        if not docs_to_reembed:
            self.stdout.write(
                self.style.WARNING(
                    "No documents found with correct hub_type. "
                    "Run 'fix_hub_types fix' first."
                )
            )
            return

        self.stdout.write(
            f"Found {len(docs_to_reembed)} document(s) to re-embed.\n"
        )

        for doc in docs_to_reembed:
            try:
                chunks = list(
                    doc.chunks.all().only("id", "hub_type", "embedding", "content")
                )
                if not chunks:
                    continue

                self._reembed_chunks(
                    doc=doc,
                    chunks=chunks,
                    stats=stats,
                    embedding_batch_size=embedding_batch_size,
                )
            except Exception as e:
                msg = f"Failed to re-embed document '{doc.title}' ({doc.id}): {e}"
                logger.exception(msg)
                stats.errors.append(msg)

        # Summary
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write("Re-embed Summary")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Documents processed: {stats.documents_fixed}")
        self.stdout.write(f"  Chunks re-embedded:  {stats.chunks_reembedded}")
        if stats.errors:
            self.stdout.write(
                self.style.ERROR(f"  Errors:              {len(stats.errors)}")
            )
            for err in stats.errors[:5]:
                self.stdout.write(f"    - {err}")

    def _reembed_chunks(
        self,
        doc: Document,
        chunks: list[DocumentChunk],
        stats: FixStats,
        embedding_batch_size: int,
    ) -> None:
        """Re-generate embeddings for a list of chunks."""
        texts = [c.content for c in chunks]

        try:
            all_embeddings: list[list[float] | None] = []
            for i in range(0, len(texts), embedding_batch_size):
                batch = texts[i : i + embedding_batch_size]
                batch_embeddings = batch_generate_embeddings(batch)
                all_embeddings.extend(batch_embeddings)

            # Update embeddings in bulk
            for chunk, embedding in zip(chunks, all_embeddings):
                chunk.embedding = embedding

            DocumentChunk.objects.bulk_update(chunks, fields=["embedding"])

            embedded_count = sum(1 for e in all_embeddings if e is not None)
            stats.chunks_reembedded += embedded_count
            stats.documents_fixed += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Re-embedded: '{doc.title[:60]}' "
                    f"({embedded_count}/{len(chunks)} chunks)"
                )
            )

        except Exception as e:
            msg = (
                f"Embedding generation failed for '{doc.title}' "
                f"({doc.id}): {e}"
            )
            logger.exception(msg)
            stats.errors.append(msg)
