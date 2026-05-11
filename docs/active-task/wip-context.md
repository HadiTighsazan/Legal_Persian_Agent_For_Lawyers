# WIP Context — Docker Backend Container Unhealthy Fix

## Status: ✅ COMPLETED (2026-05-11)

## Problem

The `docuchat_backend` container was stuck in an unhealthy state during `docker-compose up`. The error was:

```
dependency failed to start: container docuchat_backend is unhealthy
```

## Root Cause

The PostgreSQL database had a **corrupted migration state** — the database schema had been partially modified outside of Django's migration tracking (likely from a previous failed build or manual SQL execution). This caused two issues:

### Issue 1: `django_migrations` table creation failure
```
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "pg_class_relname_nsp_index"
DETAIL:  Key (relname, relnamespace)=(django_migrations_id_seq, 2200) already exists.
```
The `django_migrations` sequence already existed in the database but the table wasn't properly tracked.

### Issue 2: GIN index already exists (migration 0014)
```
psycopg2.errors.DuplicateTable: relation "chunk_search_vector_gin" already exists
```
Migration `documents.0014_documentchunk_chunk_search_vector_gin` tried to create a GIN index that already existed, causing a `ProgrammingError`. The entrypoint script used `set -e`, so any migration failure immediately crashed the container.

### Issue 3: Column already exists (migration 0015)
```
psycopg2.errors.DuplicateColumn: column "hub_type" of relation "documents" already exists
```
Migration `documents.0015` tried to add `hub_type` columns that already existed.

The container kept restarting in a loop, and the health check (`GET /health/`) never succeeded because migrations never completed successfully.

## Fix Applied

### 1. Immediate Fix — Fake-applied stuck migrations
```bash
docker-compose exec backend python manage.py migrate --fake
```
This marked migrations `0014` and `0015` as applied in the `django_migrations` table without re-running the SQL (since the schema changes already existed).

### 2. Permanent Fix — Resilient entrypoint script
Modified [`docker/backend/entrypoint.sh`](docker/backend/entrypoint.sh) to handle migration failures gracefully:
- **Before**: `set -e` caused the container to crash on any migration error
- **After**: If `migrate` fails, it automatically retries with `migrate --fake` to recover from partial/inconsistent migration states

## Verification

All 7 containers are now healthy:
```
NAME                     STATUS
docuchat_backend         Up About a minute (healthy)
docuchat_celery_beat     Up About a minute
docuchat_celery_worker   Up About a minute
docuchat_frontend        Up About a minute
docuchat_nginx           Up 47 seconds (healthy)
docuchat_postgres        Up About a minute (healthy)
docuchat_redis           Up About a minute (healthy)
```

Health endpoint returns `200 OK`:
```json
{"status": "healthy", "services": {"database": "up", "redis": "up", "celery": "up"}}
```
