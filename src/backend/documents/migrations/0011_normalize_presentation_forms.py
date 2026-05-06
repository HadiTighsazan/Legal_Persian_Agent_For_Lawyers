"""
Migration 0011: Re-normalize existing DocumentChunk content with NFKC normalization.

The updated :meth:`PersianNormalizer.normalize_for_fts` now applies
``unicodedata.normalize('NFKC', text)`` as its first step, which converts
Arabic Presentation Forms-B (U+FE70–U+FEFF) — positional glyph variants
commonly produced by PDF extractors — to standard Unicode codepoints.

**Why this matters:**

PDF extractors (PyMuPDF, pdfplumber) often preserve **positional glyph
variants** of Arabic/Persian letters instead of converting them to standard
Unicode codepoints.  For example, the word ``"لازم"`` might be stored as:

- ``ل`` (U+FEDF — Lam initial form) instead of standard ``ل`` (U+0644)
- ``ا`` (U+FE8D — Alef isolated form) instead of standard ``ا`` (U+0627)
- ``ز`` (U+FEB1 — Zain isolated form) instead of standard ``ز`` (U+0632)
- ``م`` (U+FEE1 — Meem initial form) instead of standard ``م`` (U+0645)

These presentation forms look identical on screen but have completely
different byte sequences, causing both Ctrl+F and PostgreSQL FTS to fail
when searching with standard Unicode characters.

This migration:
1. Iterates over all existing ``DocumentChunk`` rows.
2. Calls the updated ``PersianNormalizer.normalize_for_fts()`` on each
   chunk's ``content`` (which now includes NFKC normalization).
3. Saves the normalized content, which triggers the
   ``trg_chunk_search_vector`` trigger to regenerate the ``search_vector``
   with standard-Unicode tokens.

After this migration, FTS queries with standard Persian characters will
correctly match chunk content that was originally extracted with Arabic
Presentation Forms.

See also:
- ``documents/services/persian_normalizer.py`` — the updated
  ``normalize_for_fts()`` method with NFKC normalization.
- ``documents/migrations/0009_normalize_chunk_digits.py`` — the previous
  migration that normalized Persian digits (same batch pattern).
"""

from __future__ import annotations

from django.db import migrations


def normalize_presentation_forms(apps, schema_editor):
    """Re-normalize all existing DocumentChunk content with NFKC normalization.

    Iterates in batches of 500 to avoid memory issues with large datasets.
    Each chunk's ``content`` is normalized via the updated
    ``PersianNormalizer.normalize_for_fts`` (which now includes NFKC
    normalization) and saved, which triggers the
    ``trg_chunk_search_vector`` trigger to regenerate the ``search_vector``
    with standard-Unicode tokens.
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
        ("documents", "0010_add_pg_trgm"),
    ]

    operations = [
        migrations.RunPython(
            normalize_presentation_forms,
            reverse_code=migrations.RunPython.noop,
            hints={"target_db": "default"},
        ),
    ]
