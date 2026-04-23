"""
Migration 0002: Add storage fields (filename, storage_type) to Document model.

- Adds `filename` (nullable first, then backfilled from `original_filename`, then made non-nullable).
- Adds `storage_type` (default='local', db_index=True).
"""
from django.db import migrations, models


def backfill_filename(apps, schema_editor):
    """Copy original_filename to filename for all existing Document rows."""
    Document = apps.get_model("documents", "Document")
    for doc in Document.objects.iterator(chunk_size=500):
        if doc.filename is None or doc.filename == "":
            doc.filename = doc.original_filename
            doc.save(update_fields=["filename"])


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        # Step 1: Add filename as nullable first
        migrations.AddField(
            model_name="document",
            name="filename",
            field=models.CharField(max_length=255, null=True),
        ),
        # Step 2: Backfill filename from original_filename for existing rows
        migrations.RunPython(
            code=backfill_filename,
            reverse_code=migrations.RunPython.noop,
        ),
        # Step 3: Make filename non-nullable
        migrations.AlterField(
            model_name="document",
            name="filename",
            field=models.CharField(max_length=255, null=False),
        ),
        # Step 4: Add storage_type with default and db_index
        migrations.AddField(
            model_name="document",
            name="storage_type",
            field=models.CharField(
                max_length=20,
                default="local",
                db_index=True,
            ),
        ),
    ]
