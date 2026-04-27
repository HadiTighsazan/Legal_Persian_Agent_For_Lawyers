"""
Tests for the pgvector index system checks.

Covers:
- :func:`~documents.checks.pgvector_index_check`
"""
from __future__ import annotations

from unittest.mock import patch

from django.core.checks import Error
from django.test import SimpleTestCase, TestCase

from documents.checks import pgvector_index_check


class PgvectorIndexCheckUnitTests(SimpleTestCase):
    """Unit tests for the pgvector index system check (mocked DB)."""

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    @patch("documents.checks.connection")
    def test_index_exists_and_is_ivfflat(self, mock_connection) -> None:
        """Index exists with correct type → no errors."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = (
            "idx_chunks_embedding",
            "CREATE INDEX idx_chunks_embedding ON document_chunks "
            "USING ivfflat (embedding vector_cosine_ops)",
        )

        errors = pgvector_index_check(None)
        self.assertEqual(errors, [])

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    @patch("documents.checks.connection")
    def test_index_missing(self, mock_connection) -> None:
        """Index does not exist → returns E002 error."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = None

        errors = pgvector_index_check(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "documents.E002")

    @patch("documents.checks.connection")
    def test_wrong_index_type(self, mock_connection) -> None:
        """Index exists but is not ivfflat → returns E003 error (not E004)."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = (
            "idx_chunks_embedding",
            "CREATE INDEX idx_chunks_embedding ON document_chunks "
            "USING btree (embedding)",
        )

        errors = pgvector_index_check(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "documents.E003")
        # Defensive: ensure E004 is NOT returned when index type is wrong
        # (the check should short-circuit after detecting wrong type)
        error_ids = {e.id for e in errors}
        self.assertNotIn("documents.E004", error_ids)

    @patch("documents.checks.connection")
    def test_wrong_operator_class(self, mock_connection) -> None:
        """Index uses wrong operator class → returns E004 error."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = (
            "idx_chunks_embedding",
            "CREATE INDEX idx_chunks_embedding ON document_chunks "
            "USING ivfflat (embedding vector_l2_ops)",
        )

        errors = pgvector_index_check(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "documents.E004")

    @patch("documents.checks.connection")
    def test_database_unreachable(self, mock_connection) -> None:
        """Database query fails → returns E001 critical error."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.execute.side_effect = Exception("connection refused")

        errors = pgvector_index_check(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "documents.E001")


class PgvectorIndexCheckIntegrationTests(TestCase):
    """Integration tests for the pgvector index system check (real DB)."""

    databases = {"default"}

    def test_integration_with_real_database(self) -> None:
        """
        Run the check against the actual PostgreSQL database.

        This test requires:
        - A running PostgreSQL instance with pgvector
        - Migration 0004 to have been applied

        It is intentionally **not** skipped — if the DB is available
        (which it is in Docker), this provides real verification.
        """
        errors = pgvector_index_check(None)
        self.assertEqual(
            errors,
            [],
            msg=(
                f"pgvector index check failed with {len(errors)} error(s). "
                f"Run: docker-compose exec backend python manage.py migrate\n"
                f"Errors: {[e.msg for e in errors]}"
            ),
        )
