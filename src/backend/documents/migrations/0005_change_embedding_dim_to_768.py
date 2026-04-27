"""
Migration 0005: Change embedding dimension from 1536 to 768.

This migration is required because the embedding provider has been switched
from OpenAI ``text-embedding-3-small`` (1536 dimensions) to Ollama
``nomic-embed-text`` (768 dimensions).

Changes:
- Drops the existing ivfflat index (depends on column type)
- Alters the ``embedding`` column from ``VECTOR(1536)`` to ``VECTOR(768)``
- Re-creates the ivfflat index on the new column type

.. note::
    Existing embeddings stored at 1536 dimensions will be invalid after this
    migration.  Run ``scripts/reembed_all.py`` to regenerate all embeddings
    at 768 dimensions.
"""
from django.db import migrations
import pgvector.django.vector


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0004_alter_documentchunk_embedding'),
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
        # Alter the column dimension from 1536 to 768.
        migrations.AlterField(
            model_name='documentchunk',
            name='embedding',
            field=pgvector.django.vector.VectorField(
                blank=True, dimensions=768, null=True,
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
