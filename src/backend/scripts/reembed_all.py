"""
Re-embed all document chunks by clearing existing embeddings and
re-triggering the embed_document Celery task for every document.

Usage:
    docker-compose exec backend python scripts/reembed_all.py
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

# ── Django setup ──────────────────────────────────────────────────────────
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

# ── Imports (after django.setup) ──────────────────────────────────────────
from django.db.models import QuerySet  # noqa: E402
from django.utils import timezone  # noqa: E402

from documents.models import Document, DocumentChunk  # noqa: E402
from documents.tasks import embed_document  # noqa: E402
from tasks.models import ProcessingTask  # noqa: E402

# ── Logger ────────────────────────────────────────────────────────────────
logger = logging.getLogger("reembed_all")
logger.setLevel(logging.INFO)

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(
    logging.Formatter("[%(name)s] %(message)s")
)
logger.addHandler(_handler)


# ── Constants ─────────────────────────────────────────────────────────────
CHUNK_BATCH_SIZE: int = 500
"""Number of chunks to process per iteration when collecting document IDs."""


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the re-embed script."""
    logger.info("Starting re-embed of all document chunks")

    # ── Step 1: Count total chunks ───────────────────────────────────────
    total_chunks: int = DocumentChunk.objects.count()
    if total_chunks == 0:
        logger.info("No chunks found — nothing to re-embed")
        return

    logger.info("Found %d chunks to re-embed", total_chunks)

    # ── Step 2: Clear all embeddings ─────────────────────────────────────
    # Single UPDATE query — no memory overhead regardless of dataset size.
    updated_count: int = (
        DocumentChunk.objects
        .update(embedding=None)
    )
    logger.info("Cleared embeddings for %d chunks", updated_count)

    # ── Step 3: Collect unique document IDs ───────────────────────────────
    # Use iterator() to stream results in batches, avoiding loading all
    # chunk IDs into memory at once.
    doc_id_set: set[str] = set()
    chunk_count: int = 0

    chunk_qs: QuerySet = (
        DocumentChunk.objects
        .values_list("document_id", flat=True)
        .iterator(chunk_size=CHUNK_BATCH_SIZE)
    )

    for doc_id in chunk_qs:
        doc_id_set.add(str(doc_id))
        chunk_count += 1

        # Log progress every CHUNK_BATCH_SIZE chunks
        if chunk_count % CHUNK_BATCH_SIZE == 0:
            logger.info(
                "Scanning chunks... %d/%d (%.0f%%)",
                chunk_count,
                total_chunks,
                (chunk_count / total_chunks) * 100,
            )

    logger.info(
        "Collected %d unique documents from %d chunks",
        len(doc_id_set),
        chunk_count,
    )

    # ── Step 4: Queue embed_document task per document ───────────────────
    queued_count: int = 0
    failed_count: int = 0

    for doc_id in sorted(doc_id_set):
        try:
            # Verify document still exists
            document = Document.objects.get(id=doc_id)

            # Create a ProcessingTask for this embed operation
            processing_task = ProcessingTask.objects.create(
                document=document,
                task_type="embed",
                status="pending",
            )

            # Dispatch the Celery task
            embed_document.delay(doc_id, str(processing_task.id))

            logger.info(
                "Queued re-embed for document %s (task=%s)",
                doc_id,
                processing_task.id,
            )
            queued_count += 1

        except Document.DoesNotExist:
            logger.warning(
                "Document %s no longer exists — skipping", doc_id
            )
            failed_count += 1

        except Exception as e:
            logger.exception(
                "Failed to queue re-embed for document %s — %s",
                doc_id,
                e,
            )
            failed_count += 1

    # ── Step 5: Summary ──────────────────────────────────────────────────
    logger.info(
        "Re-embedding complete: %d documents queued, %d failed "
        "(%d total chunks)",
        queued_count,
        failed_count,
        total_chunks,
    )

    if failed_count > 0:
        logger.warning(
            "%d document(s) failed to queue — check logs above for details",
            failed_count,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
