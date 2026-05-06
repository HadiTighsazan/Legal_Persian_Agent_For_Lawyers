"""
Migration 0010: Enable pg_trgm extension and add trigram GIN index on content.

Adds trigram-based similarity search support for fuzzy matching of Persian
legal text.  The ``pg_trgm`` extension enables the ``similarity()`` function
and the ``%`` operator, which break text into 3-character sliding windows
(trigrams) for comparison.

**Why this matters for Persian legal text:**

- **OCR errors**: Persian PDFs often have OCR artifacts like ``مقـاله``
  instead of ``ماده`` — trigrams handle partial matches gracefully.
- **Spelling variations**: Persian has multiple acceptable spellings
  (e.g., ``آزادی`` vs ``ازادی``).
- **Tatweel remnants**: Even after normalisation, some Tatweel artifacts
  may remain — trigrams bridge these gaps.
- **Compound word variations**: ``می‌شود`` vs ``میشود`` vs ``می شود``.

The GIN index on ``content`` using ``gin_trgm_ops`` enables fast trigram
similarity lookups.  Without this index, ``similarity()`` would require a
full table scan.

See also:
- ``documents/services/search_service.py`` — the ``trigram_search()`` function.
- PostgreSQL docs: https://www.postgresql.org/docs/current/pgtrgm.html
"""

from __future__ import annotations

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0009_normalize_chunk_digits"),
    ]

    operations = [
        # Enable the pg_trgm extension (idempotent — IF NOT EXISTS internally).
        TrigramExtension(),
        # Create a GIN index on content using gin_trgm_ops for fast trigram
        # similarity searches.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm "
                "ON document_chunks USING gin (content gin_trgm_ops);"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS idx_chunks_content_trgm;"
            ),
        ),
    ]
