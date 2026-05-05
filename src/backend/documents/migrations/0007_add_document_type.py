"""
Migration 0007: Add document_type field to Document model.

Adds a ``document_type`` CharField with choices ``user_upload`` / ``reference_law``
to distinguish regular user uploads from system reference legal documents.
All existing rows default to ``user_upload``.

This field is used by the RAG service to determine whether to apply the
``legal_status: "valid"`` filter during hybrid search.  For ``user_upload``
documents (e.g., English textbooks), no filter is applied, ensuring all
chunks are retrievable regardless of their ``legal_status`` value.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add ``document_type`` to the ``documents`` table."""

    dependencies = [
        ("documents", "0006_add_fts_and_metadata_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("user_upload", "User Upload"),
                    ("reference_law", "Reference Law"),
                ],
                db_index=True,
                default="user_upload",
                help_text="Type of document: 'user_upload' for regular files, "
                "'reference_law' for system reference legal texts.",
                max_length=20,
            ),
        ),
    ]
