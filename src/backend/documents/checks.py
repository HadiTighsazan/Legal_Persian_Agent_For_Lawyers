"""
System checks for the documents app.

Verifies critical database infrastructure:
- pgvector extension exists
- ``idx_chunks_embedding`` ivfflat index exists on ``document_chunks.embedding``
"""
from __future__ import annotations

from django.core.checks import Critical, Error, register
from django.db import connection


@register()
def pgvector_index_check(app_configs, **kwargs) -> list[Error]:
    """
    Check that the ivfflat index ``idx_chunks_embedding`` exists on
    ``document_chunks.embedding``.

    This index is required for efficient cosine-similarity search via pgvector.
    It should have been created by migration ``0004_alter_documentchunk_embedding``.
    """
    errors: list[Error] = []

    try:
        with connection.cursor() as cursor:
            # Query pg_indexes to verify the index exists and is ivfflat
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'document_chunks'
                  AND indexname = 'idx_chunks_embedding'
                """
            )
            row = cursor.fetchone()
    except Exception as exc:
        errors.append(
            Critical(
                msg="Unable to query pg_indexes for idx_chunks_embedding",
                hint=f"Database query failed: {exc}",
                id="documents.E001",
            )
        )
        return errors

    if row is None:
        errors.append(
            Error(
                msg="Missing pgvector index idx_chunks_embedding on document_chunks.embedding",
                hint=(
                    "Run migration 0004_alter_documentchunk_embedding: "
                    "python manage.py migrate documents 0004"
                ),
                id="documents.E002",
            )
        )
        return errors

    index_name, index_def = row

    # Verify the index type is ivfflat
    if "ivfflat" not in index_def:
        errors.append(
            Error(
                msg="Index idx_chunks_embedding has wrong type (expected ivfflat)",
                hint=f"Current definition: {index_def}",
                id="documents.E003",
            )
        )
        return errors

    # Verify the operator class is vector_cosine_ops
    if "vector_cosine_ops" not in index_def:
        errors.append(
            Error(
                msg="Index idx_chunks_embedding uses wrong operator class (expected vector_cosine_ops)",
                hint=f"Current definition: {index_def}",
                id="documents.E004",
            )
        )

    return errors
