"""
Migration 0009: Normalize Persian digits in existing DocumentChunk content for FTS.

The DB trigger ``trg_chunk_search_vector`` builds the ``search_vector`` using
``to_tsvector('simple', ...)``, which does NOT convert Persian digits
(۰۱۲۳۴۵۶۷۸۹) to English digits (0123456789).

Previously, chunk content was stored with raw Persian digits, so the
``search_vector`` contained Persian-digit tokens (e.g., ``'۱۹۵'``). FTS queries
produced by the query formulation layer convert Persian digits to English digits
(e.g., ``'195'``), causing a mismatch and zero FTS results for digit-containing
queries.

This migration:
1. Iterates over all existing ``DocumentChunk`` rows.
2. Calls ``PersianNormalizer.normalize_for_fts()`` on each chunk's ``content``.
3. Saves the normalized content, which triggers the
   ``trg_chunk_search_vector`` trigger to regenerate the ``search_vector`` with
   English-digit tokens.

After this migration, FTS queries with English digits will correctly match
chunk content.

See also:
- ``documents/migrations/0006_add_fts_and_metadata_fields.py`` — the original
  migration that created the trigger (which assumed application-layer
  normalization would happen before save).
- ``documents/services/persian_normalizer.py`` — the ``normalize_for_fts()``
  method.
"""

from __future__ import annotations

from django.db import migrations


def normalize_existing_chunks(apps, schema_editor):
    """Normalize Persian digits in all existing DocumentChunk content.

    Iterates in batches to avoid memory issues with large datasets. Each
    chunk's ``content`` is normalized via ``PersianNormalizer.normalize_for_fts``
    and saved, which triggers the ``trg_chunk_search_vector`` trigger to
    regenerate the ``search_vector`` with English-digit tokens.
    """
    DocumentChunk = apps.get_model("documents", "DocumentChunk")
    PersianNormalizer = __import__(
        "documents.services.persian_normalizer",
        fromlist=["PersianNormalizer"],
    ).PersianNormalizer

    total = DocumentChunk.objects.count()
    batch_size = 500
    processed = 0

    while processed < total:
        chunks = list(
            DocumentChunk.objects.all()[processed : processed + batch_size]
        )
        for chunk in chunks:
            normalized = PersianNormalizer.normalize_for_fts(chunk.content)
            if normalized != chunk.content:
                chunk.content = normalized
                chunk.save(update_fields=["content"])
        processed += len(chunks)


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0008_document_documents_documen_fc21d0_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(
            normalize_existing_chunks,
            reverse_code=migrations.RunPython.noop,
            hints={"target_db": "default"},
        ),
    ]
