"""
Migration 0013: Change embedding dimension from 768 to 1024.

This migration is required because the Ollama embedding model has been switched
from ``nomic-embed-text`` (768 dimensions) to ``bge-m3`` (1024 dimensions).

Changes:
- Drops the existing ivfflat index (depends on column type)
- Alters the ``embedding`` column from ``VECTOR(768)`` to ``VECTOR(1024)``
- Re-creates the ivfflat index on the new column type

.. note::
    This is a fresh project with no existing data, so no re-embedding is needed.
"""
from django.db import migrations
import pgvector.django.vector


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0012_add_extracted_text_and_extraction_metadata'),
    ]

    operations = [
        # Drop the ivfflat index first (it depends on the column type).
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_chunks_embedding",
            reverse_sql=(
                "CREATE INDEX IF NOT EXISTS idx_chunks_embedding "
                "ON document_chunks "
                "USING ivfflat (embedding vector_cosine_ops)"
            ),
        ),
        # Alter the column dimension from 768 to 1024.
        migrations.AlterField(
            model_name='documentchunk',
            name='embedding',
            field=pgvector.django.vector.VectorField(
                blank=True, dimensions=1024, null=True,
            ),
        ),
        # Re-create the ivfflat index on the new column type.
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_chunks_embedding "
                "ON document_chunks "
                "USING ivfflat (embedding vector_cosine_ops)"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_chunks_embedding",
        ),
    ]
