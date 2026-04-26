"""
Migration 0004: Add pgvector embedding support.

- Ensures vector extension exists
- Alters embedding column to VECTOR(1536) via VectorField
- Creates ivfflat index for cosine similarity search
"""
from django.db import migrations, models
import pgvector.django.vector


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0003_add_processing_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector",
            reverse_sql="DROP EXTENSION IF EXISTS vector",
        ),
        migrations.AlterField(
            model_name='documentchunk',
            name='embedding',
            field=pgvector.django.vector.VectorField(blank=True, dimensions=1536, null=True),
        ),
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_chunks_embedding",
        ),
    ]
