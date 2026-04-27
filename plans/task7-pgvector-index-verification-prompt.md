# Task 7: pgvector Index Verification

## Objective

Create a Django system check (or test) that verifies the `idx_chunks_embedding` ivfflat index exists on the `document_chunks` table in PostgreSQL. This is a **verification-only** task — the index was already created in [Migration 0004](src/backend/documents/migrations/0004_alter_documentchunk_embedding.py), but we need a programmatic way to confirm it exists and is of the correct type (`ivfflat`).

---

## Context

### What Already Exists

1. **Migration [`0004_alter_documentchunk_embedding.py`](src/backend/documents/migrations/0004_alter_documentchunk_embedding.py)** — Already creates:
   - `CREATE EXTENSION IF NOT EXISTS vector`
   - `ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536)`
   - `CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops)`

2. **Model [`DocumentChunk`](src/backend/documents/models.py:80)** — Uses `VectorField(dimensions=1536, null=True, blank=True)` for the `embedding` column.

3. **Database table** — `document_chunks` with `embedding VECTOR(1536)`.

### What Needs to Be Built

A **Django system check** (registered via `SystemCheckError`) or a **standalone test** that:

1. Connects to the PostgreSQL database
2. Queries `pg_indexes` to find `idx_chunks_embedding`
3. Asserts:
   - The index **exists**
   - The index type is **`ivfflat`**
   - The index uses **`vector_cosine_ops`** operator class

---

## Design Decision: System Check vs. Test

| Approach | Pros | Cons |
|----------|------|------|
| **Django System Check** (`checks.py`) | Runs on every `runserver` / `migrate` / `check`; catches missing index early | Requires database access during startup; may fail if DB not ready |
| **Django Test** (`tests/`) | Standard TDD flow; runs in CI; no startup impact | Only runs when tests are executed |
| **Management Command** (`management/commands/`) | Can be run on-demand; useful for DevOps | Another file to maintain |

**Recommendation:** Create **both** a Django system check (for early warning) AND a test (for CI verification). The system check is lightweight and follows Django best practices for infrastructure verification.

---

## Implementation Plan

### Step 1: Create [`src/backend/documents/checks.py`](src/backend/documents/checks.py) — Django System Check

Create a new file with a system check that queries `pg_indexes`:

```python
"""
System checks for the documents app.

Verifies critical database infrastructure:
- pgvector extension exists
- idx_chunks_embedding ivfflat index exists on document_chunks.embedding
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
                msg=f"Index idx_chunks_embedding has wrong type (expected ivfflat)",
                hint=f"Current definition: {index_def}",
                id="documents.E003",
            )
        )

    # Verify the operator class is vector_cosine_ops
    if "vector_cosine_ops" not in index_def:
        errors.append(
            Error(
                msg=f"Index idx_chunks_embedding uses wrong operator class (expected vector_cosine_ops)",
                hint=f"Current definition: {index_def}",
                id="documents.E004",
            )
        )

    return errors
```

**Key design points:**
- Uses `@register()` decorator so Django auto-discovers the check (no `AppConfig` changes needed since `django.core.checks` auto-discovers `checks.py` in each app)
- Returns `Critical` if the database is unreachable (infrastructure issue)
- Returns `Error` if the index is missing or has wrong type
- Uses `connection.cursor()` — works with any PostgreSQL connection (including Docker)
- Idempotent and safe to run repeatedly

### Step 2: Create Test — [`src/backend/documents/tests/test_pgvector_checks.py`](src/backend/documents/tests/test_pgvector_checks.py)

Create a test file that verifies the system check behaves correctly:

```python
"""
Tests for the pgvector index system checks.

Covers:
- :func:`~documents.checks.pgvector_index_check`
"""
from __future__ import annotations

from unittest.mock import patch

from django.core.checks import Error
from django.test import TestCase, override_settings

from documents.checks import pgvector_index_check


class PgvectorIndexCheckTests(TestCase):
    """Tests for the pgvector index system check."""

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
        """Index exists but is not ivfflat → returns E003 error."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = (
            "idx_chunks_embedding",
            "CREATE INDEX idx_chunks_embedding ON document_chunks "
            "USING btree (embedding)",
        )

        errors = pgvector_index_check(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "documents.E003")

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

    # ------------------------------------------------------------------
    # Integration test (requires real DB)
    # ------------------------------------------------------------------

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
```

**Key design points:**
- **Unit tests** (4 tests) — Mock `connection.cursor()` to test each error path without a real DB
- **Integration test** (1 test) — Runs against the real PostgreSQL database (available in Docker)
- Follows existing test patterns: uses `TestCase`, `from __future__ import annotations`, type hints
- Tests all 4 error IDs: `E001` (DB unreachable), `E002` (index missing), `E003` (wrong type), `E004` (wrong operator class)

### Step 3: Update [`docs/references/database-schema.md`](docs/references/database-schema.md)

Add a note about the system check in the migration notes section (around line 203):

```markdown
### System Check: pgvector Index Verification (Task 7)
- **File:** `src/backend/documents/checks.py`
- **Check ID:** `documents.E001`–`E004`
- **Purpose:** Verifies `idx_chunks_embedding` ivfflat index exists on `document_chunks.embedding`
- **Trigger:** Runs automatically on `python manage.py check`, `runserver`, `migrate`
- **Test file:** `src/backend/documents/tests/test_pgvector_checks.py`
```

### Step 4: Update [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md)

Record completion status.

---

## Execution Steps (in order)

1. **Create** [`src/backend/documents/checks.py`](src/backend/documents/checks.py) — Django system check with `@register()` decorator
2. **Create** [`src/backend/documents/tests/test_pgvector_checks.py`](src/backend/documents/tests/test_pgvector_checks.py) — Unit tests + integration test
3. **Run unit tests** to verify mock-based tests pass:
   ```bash
   docker-compose exec backend python -m pytest documents/tests/test_pgvector_checks.py -v -k "not integration"
   ```
4. **Run integration test** to verify against real DB:
   ```bash
   docker-compose exec backend python -m pytest documents/tests/test_pgvector_checks.py -v -k "integration"
   ```
5. **Run system check** manually to verify it works:
   ```bash
   docker-compose exec backend python manage.py check
   ```
6. **Update** [`docs/references/database-schema.md`](docs/references/database-schema.md) with system check note
7. **Update** [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) with completion status

---

## Verification / Acceptance Criteria

- ✅ [`src/backend/documents/checks.py`](src/backend/documents/checks.py) exists with `@register()` system check
- ✅ System check queries `pg_indexes` for `idx_chunks_embedding`
- ✅ Returns `documents.E002` error if index is missing
- ✅ Returns `documents.E003` error if index type is not `ivfflat`
- ✅ Returns `documents.E004` error if operator class is not `vector_cosine_ops`
- ✅ Returns `documents.E001` critical error if database is unreachable
- ✅ [`src/backend/documents/tests/test_pgvector_checks.py`](src/backend/documents/tests/test_pgvector_checks.py) exists with 4 unit tests + 1 integration test
- ✅ All unit tests pass (mocked)
- ✅ Integration test passes against real PostgreSQL
- ✅ `python manage.py check` runs without errors
- ✅ [`docs/references/database-schema.md`](docs/references/database-schema.md) updated with system check note
- ✅ [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) updated

---

## Rollback

If the system check causes issues (e.g., false positives during startup when DB isn't ready):

1. Remove or comment out the check in [`src/backend/documents/checks.py`](src/backend/documents/checks.py)
2. Django will auto-discover the removal on next restart

---

## Notes

- The `@register()` decorator without arguments registers the check as a **general check** (runs on every `check`, `runserver`, `migrate`, etc.)
- The check uses `connection.cursor()` which works within Django's database connection pooling
- The check is **idempotent** — safe to run repeatedly
- The `pg_indexes` system catalog is available in all PostgreSQL versions supported by Django 4.2
- No new dependencies required — uses only `django.db.connection` (stdlib)
