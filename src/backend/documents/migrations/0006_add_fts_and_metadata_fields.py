"""
Migration 0006: Add FTS search vector and denormalized metadata fields.

Adds support for hybrid search (vector + keyword) by introducing:

1. ``search_vector`` — A PostgreSQL ``SearchVectorField`` that stores the
   full-text search vector for keyword matching. Populated automatically by
   a DB trigger on INSERT/UPDATE of ``content``.

2. Denormalized metadata columns (``law_name``, ``legal_status``,
   ``approval_date``, ``legal_type``) for efficient SQL-level filtering
   without JSONB extraction overhead.

3. A GIN index on ``search_vector`` for fast FTS lookups.

4. A database function ``update_chunk_search_vector()`` and a trigger
   ``trg_chunk_search_vector`` that automatically updates the search vector
   whenever ``content`` is inserted or updated.

The trigger uses PostgreSQL's ``to_tsvector('simple', ...)`` configuration
(rather than ``'persian'``) because:

- The ``simple`` config tokenizes on whitespace/punctuation and lowercases,
  which is ideal for exact legal term matching (e.g., ``"ماده"``, ``"قانون"``).
- Persian legal texts contain many Arabic-origin terms that the ``persian``
  stemmer might over-stem, losing precision for article-number lookups.
- Number normalization (Persian/Arabic digits → English) is handled at the
  application layer by :meth:`PersianNormalizer.normalize_for_fts` before
  the content reaches the trigger.

Changes:
- Add ``search_vector`` column (``tsvector``) to ``document_chunks``
- Add ``law_name`` column (``varchar(500)``) to ``document_chunks``
- Add ``legal_status`` column (``varchar(50)``) to ``document_chunks``
- Add ``approval_date`` column (``date``) to ``document_chunks``
- Add ``legal_type`` column (``varchar(50)``) to ``document_chunks``
- Create GIN index ``chunk_search_vector_gin`` on ``search_vector``
- Create function ``update_chunk_search_vector()``
- Create trigger ``trg_chunk_search_vector``
"""
import django.contrib.postgres.search
from django.db import migrations, models


# ---------------------------------------------------------------------------
# SQL for the FTS trigger function
# ---------------------------------------------------------------------------

CREATE_FTS_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION update_chunk_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('simple', COALESCE(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DROP_FTS_FUNCTION_SQL = """
DROP FUNCTION IF EXISTS update_chunk_search_vector() CASCADE;
"""

# ---------------------------------------------------------------------------
# SQL for the trigger
# ---------------------------------------------------------------------------

CREATE_TRIGGER_SQL = """
CREATE TRIGGER trg_chunk_search_vector
    BEFORE INSERT OR UPDATE OF content
    ON document_chunks
    FOR EACH ROW
    EXECUTE FUNCTION update_chunk_search_vector();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_chunk_search_vector ON document_chunks;
"""

# ---------------------------------------------------------------------------
# SQL to backfill search_vector for existing rows
# ---------------------------------------------------------------------------

BACKFILL_SQL = """
UPDATE document_chunks
SET search_vector = to_tsvector('simple', COALESCE(content, ''))
WHERE search_vector IS NULL;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0005_change_embedding_dim_to_768'),
    ]

    operations = [
        # ---- Add denormalized metadata columns ----
        migrations.AddField(
            model_name='documentchunk',
            name='law_name',
            field=models.CharField(
                max_length=500, null=True, blank=True, db_index=True,
            ),
        ),
        migrations.AddField(
            model_name='documentchunk',
            name='legal_status',
            field=models.CharField(
                max_length=50, null=True, blank=True, db_index=True,
            ),
        ),
        migrations.AddField(
            model_name='documentchunk',
            name='approval_date',
            field=models.DateField(
                null=True, blank=True, db_index=True,
            ),
        ),
        migrations.AddField(
            model_name='documentchunk',
            name='legal_type',
            field=models.CharField(
                max_length=50, null=True, blank=True, db_index=True,
            ),
        ),
        # ---- Add search_vector column ----
        migrations.AddField(
            model_name='documentchunk',
            name='search_vector',
            field=django.contrib.postgres.search.SearchVectorField(
                null=True, blank=True, editable=False,
            ),
        ),
        # ---- Create GIN index on search_vector ----
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS chunk_search_vector_gin "
                "ON document_chunks USING GIN (search_vector)"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS chunk_search_vector_gin"
            ),
        ),
        # ---- Create FTS trigger function ----
        migrations.RunSQL(
            sql=CREATE_FTS_FUNCTION_SQL,
            reverse_sql=DROP_FTS_FUNCTION_SQL,
        ),
        # ---- Create trigger on document_chunks ----
        migrations.RunSQL(
            sql=CREATE_TRIGGER_SQL,
            reverse_sql=DROP_TRIGGER_SQL,
        ),
        # ---- Backfill search_vector for existing rows ----
        migrations.RunSQL(
            sql=BACKFILL_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
