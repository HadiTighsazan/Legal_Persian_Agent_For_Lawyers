# WIP Context — E01 Refactoring (Project Scaffolding & DevOps)

## What Was Completed

All 12 refactoring tasks from the E01 refactoring prompt were applied:

### Critical Priority

#### Task 1.1 — Fix CI Test Command
- Changed [`python -m pytest tests/ -v --cov=. --cov-report=xml`](.github/workflows/ci.yml:108) to `python -m pytest -v --cov=. --cov-report=xml`
- This now uses `testpaths` defined in [`pytest.ini`](src/backend/pytest.ini:3-7), covering all test directories (`conversations/tests/`, `documents/tests/`, `users/tests/`, `tests/`)

#### Task 1.2 — Merge Health Check Views
- Deleted [`src/backend/config/views.py`](src/backend/config/views.py) entirely (dead code)
- Rewrote [`src/backend/core/views.py`](src/backend/core/views.py) with the comprehensive health check logic from `config/views.py`:
  - `HealthCheckView` — checks database connection, Redis ping, and Celery (via Redis). Returns 200 if all healthy, 503 if any are down.
  - `ReadyCheckView` — simple readiness check returning `{"status": "ready"}`
  - `LiveCheckView` — simple liveness check returning `{"status": "alive"}`
- Import in [`config/urls.py`](src/backend/config/urls.py:23) already imports from `core.views`, so no change needed

### Medium Priority

#### Task 2.1 — Fix Celery Redis DB Separation
- Changed [`settings.py`](src/backend/config/settings.py:228-229) to read separate `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` env vars with `REDIS_URL` as fallback

#### Task 2.2 — Fix CI Cache Key
- Changed [`cache-dependency-path`](.github/workflows/ci.yml:128) from `package-lock.json` to `package.json`
- Changed [`hashFiles`](.github/workflows/ci.yml:134) from `package-lock.json` to `package.json`

#### Task 2.3 — Add ARG Declarations to Dockerfiles
- [`docker/backend/Dockerfile`](docker/backend/Dockerfile): Added `ARG PIP_INDEX_URL` and `ARG PIP_EXTRA_INDEX_URL` with defaults, used in pip config RUN command
- [`docker/frontend/Dockerfile`](docker/frontend/Dockerfile): Added `ARG NPM_CONFIG_REGISTRY` and `ARG NPM_CONFIG_STRICT_SSL` with defaults, removed the first redundant RUN block (Task 3.2)

#### Task 2.4 — Fix Nginx Health Check Header
- Moved `add_header Content-Type text/plain;` before `return 200 "healthy\n";` in [`nginx.conf`](docker/nginx/nginx.conf:88-92)

### Low Priority

#### Task 3.1 — Replace `datetime.utcnow()`
- All 6 occurrences replaced with `datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')` in [`core/views.py`](src/backend/core/views.py)

#### Task 3.2 — Consolidate Frontend Dockerfile
- Handled in Task 2.3 — removed the first RUN block that set `package-mirror.liara.ir` registry (overwritten by the second RUN)

#### Task 3.3 — Remove Backend Dependency from Worker
- Removed `backend` from [`celery_worker.depends_on`](docker-compose.yml:127-130), added `condition: service_healthy` for postgres and redis

#### Task 3.4 — Sync `celery_beat` Environment Variables
- Added missing env vars to [`celery_beat`](docker-compose.yml:163-183) to match `celery_worker`: `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_EMBEDDING_MODEL`, `CHAT_PROVIDER`, `CHAT_API_KEY`, `CHAT_BASE_URL`, `OPENAI_CHAT_MODEL`, `OPENAI_CHAT_MAX_TOKENS`, `OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_CHAT_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_DIMENSION`
- Also fixed `depends_on` to use `condition: service_healthy` for postgres and redis, removed `backend` dependency

#### Task 3.5 — Add Shared Test Fixtures
- Added shared fixtures to [`conftest.py`](src/backend/conftest.py): `api_client`, `user`, `auth_headers`, `authenticated_client`

#### Task 3.6 — Document Nginx Trailing Slash
- Added comments to [`nginx.conf`](docker/nginx/nginx.conf:95,129) explaining trailing slash behavior for `/api/` (strips prefix) and `/admin/` (preserves prefix)

## Current State of the Code

All 12 refactoring changes are applied and all 449 tests pass. Docker Compose config is valid.

### Files Modified

| File | Changes |
|------|---------|
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Fixed test command (Task 1.1), fixed cache key (Task 2.2) |
| [`src/backend/config/views.py`](src/backend/config/views.py) | **Deleted** — dead code (Task 1.2) |
| [`src/backend/core/views.py`](src/backend/core/views.py) | Rewritten with comprehensive health check logic + `datetime.now(timezone.utc)` (Tasks 1.2, 3.1) |
| [`src/backend/config/settings.py`](src/backend/config/settings.py) | Fixed Celery Redis DB separation (Task 2.1) |
| [`docker/backend/Dockerfile`](docker/backend/Dockerfile) | Added ARG declarations for pip mirrors (Task 2.3) |
| [`docker/frontend/Dockerfile`](docker/frontend/Dockerfile) | Added ARG declarations, removed redundant RUN block (Tasks 2.3, 3.2) |
| [`docker/nginx/nginx.conf`](docker/nginx/nginx.conf) | Fixed health check header order, added trailing slash docs (Tasks 2.4, 3.6) |
| [`docker-compose.yml`](docker-compose.yml) | Removed backend from worker deps, synced celery_beat env vars (Tasks 3.3, 3.4) |
| [`src/backend/conftest.py`](src/backend/conftest.py) | Added shared test fixtures (Task 3.5) |

## Remaining Items

- No remaining items — all 12 refactoring tasks are complete.

## Reference Documentation Updates

- **`docs/references/database-schema.md`**: No changes — no database schema modifications were made.
- **`docs/references/api-registry.md`**: No changes — no API endpoint modifications were made.
