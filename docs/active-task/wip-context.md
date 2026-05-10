# WIP Context — Fix Backend Crash & Nginx Not Starting (Duplicate Index Migration)

## Status: ✅ COMPLETED (2026-05-10)

## Problem Summary

User reported that the backend container was unhealthy (restarting loop) and nginx never started.

### Root Cause: Duplicate GIN Index Creation in Two Migrations

Migration [`0006_add_fts_and_metadata_fields.py`](src/backend/documents/migrations/0006_add_fts_and_metadata_fields.py:135) already creates the GIN index `chunk_search_vector_gin` via `RunSQL` with `CREATE INDEX IF NOT EXISTS`.

Migration [`0014_documentchunk_chunk_search_vector_gin.py`](src/backend/documents/migrations/0014_documentchunk_chunk_search_vector_gin.py:14) (auto-generated later) tried to create the **same index** again using Django's `migrations.AddIndex` operation, which calls `CREATE INDEX` (without `IF NOT EXISTS`).

Since the index already existed from migration 0006, PostgreSQL threw:
```
psycopg2.errors.DuplicateTable: relation "chunk_search_vector_gin" already exists
```

This caused the entire `python manage.py migrate` command to fail in the entrypoint, which meant:
1. Backend container crashed on startup → restart loop → never healthy
2. Nginx depends on `backend: condition: service_healthy` → never started

### Error Chain

1. `entrypoint.sh` runs `python manage.py migrate --noinput`
2. Migration 0014 tries `CREATE INDEX chunk_search_vector_gin ...` (no `IF NOT EXISTS`)
3. Index already exists from migration 0006 → `DuplicateTable` error
4. `migrate` command fails → entrypoint exits with error
5. Backend container restarts → loop
6. Nginx healthcheck on backend never passes → nginx stays down

## What Changed

### Files Modified

| File | Change |
|------|--------|
| [`src/backend/documents/migrations/0014_documentchunk_chunk_search_vector_gin.py`](src/backend/documents/migrations/0014_documentchunk_chunk_search_vector_gin.py) | Changed `migrations.AddIndex` to `migrations.RunSQL` with `CREATE INDEX IF NOT EXISTS` (same safe pattern used in migration 0006). |

## Verification

- `docker-compose ps` shows all 7 containers **Up and Healthy**:
  - `docuchat_backend` — healthy
  - `docuchat_celery_worker` — up
  - `docuchat_celery_beat` — up
  - `docuchat_nginx` — healthy (ports 80, 443)
  - `docuchat_frontend` — up (port 5173)
  - `docuchat_postgres` — healthy
  - `docuchat_redis` — healthy

## Next Step

User should verify the application works by accessing it in the browser.
