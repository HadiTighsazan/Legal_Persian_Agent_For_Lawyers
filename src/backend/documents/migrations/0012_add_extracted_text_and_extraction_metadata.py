"""
Migration 0012: Add extracted_text, extraction_method, and garbled_score fields.

Adds three new fields to the ``documents`` table for the monitoring page:

- ``extracted_text`` (TextField) — Stores the full extracted PDF text for
  debugging and visualization on the monitoring page.
- ``extraction_method`` (CharField, max 20) — Records which extraction method
  succeeded: ``pymupdf``, ``pdfplumber``, or ``tesseract``.
- ``garbled_score`` (FloatField, nullable) — The garbled detection ratio
  (0.0–1.0) computed by ``_is_persian_text_garbled()``.

These fields are populated by the extraction pipeline task and are used
exclusively by the developer monitoring page at ``/monitoring/:documentId``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add extracted_text, extraction_method, and garbled_score to documents."""

    dependencies = [
        ("documents", "0011_normalize_presentation_forms"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="extracted_text",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="document",
            name="extraction_method",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="document",
            name="garbled_score",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
