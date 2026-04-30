# E01 Refactoring Prompt — Project Scaffolding & DevOps

## Context

This prompt contains 12 refactoring tasks for Epic E01 (Project Scaffolding & DevOps) of the DocuChat project. All tests currently pass. The goal is to fix code quality issues, eliminate dead code, and fix CI configuration gaps.

**Important:** After completing all tasks, run the full test suite to verify nothing is broken:
```bash
docker-compose --profile test run --rm test
```

Also verify the CI configuration is valid by running:
```bash
docker-compose config
```

---

## Task 1.1 — Fix CI Test Command (Critical)

**File:** [`.github/workflows/ci.yml:108`](../.github/workflows/ci.yml:108)

**Problem:** The CI runs `python -m pytest tests/` which only covers `src/backend/tests/`. It misses all tests in `conversations/tests/`, `documents/tests/`, and `users/tests/`.

**Fix:** Change the pytest command to use `pytest.ini`'s configured test paths. Replace:
```yaml
python -m pytest tests/ -v --cov=. --cov-report=xml
```
with:
```yaml
python -m pytest -v --cov=. --cov-report=xml
```

This will use the `testpaths` defined in [`pytest.ini`](../src/backend/pytest.ini:3-7).

---

## Task 1.2 — Merge Health Check Views (Critical)

**Files:** [`src/backend/config/views.py`](../src/backend/config/views.py), [`src/backend/core/views.py`](../src/backend/core/views.py), [`src/backend/config/urls.py`](../src/backend/config/urls.py)

**Problem:** There are two duplicate implementations of `HealthCheckView`, `ReadyCheckView`, and `LiveCheckView`. The version in `config/views.py` has comprehensive health check logic (checks DB + Redis + Celery) but is dead code — `config/urls.py` imports from `core.views` instead.

**Fix:**
1. Delete [`src/backend/config/views.py`](../src/backend/config/views.py) entirely.
2. Replace the content of [`src/backend/core/views.py`](../src/backend/core/views.py) with the comprehensive health check logic from `config/views.py` (the version that checks DB, Redis, and Celery).
3. Update the import in [`src/backend/config/urls.py`](../src/backend/config/urls.py:23) if needed (it already imports from `core.views`, so it should continue to work).

The final `core/views.py` should contain:
- `HealthCheckView` — checks database connection, Redis ping, and Celery (via Redis). Returns 200 if all healthy, 503 if any are down.
- `ReadyCheckView` — simple readiness check returning `{"status": "ready"}`.
- `LiveCheckView` — simple liveness check returning `{"status": "alive"}`.

**Important:** Replace all `datetime.utcnow()` calls with `datetime.now(timezone.utc)` (see Task 3.1).

---

## Task 2.1 — Fix Celery Redis DB Separation (Medium)

**File:** [`src/backend/config/settings.py:228-229`](../src/backend/config/settings.py:228)

**Problem:** Both `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` read from the same `REDIS_URL` environment variable. If `REDIS_URL` is set to `redis://redis:6379/0`, both will point to the same Redis database, causing potential key collisions.

Additionally, `docker-compose.yml` defines `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` env vars, but `settings.py` ignores them.

**Fix:** Change settings.py to read separate env vars with `REDIS_URL` as fallback:

```python
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default=env('REDIS_URL', default='redis://localhost:6379/0'))
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default=env('REDIS_URL', default='redis://localhost:6379/1'))
```

This way:
- If `CELERY_BROKER_URL` is set (e.g., in docker-compose.yml), it's used directly.
- If not, it falls back to `REDIS_URL`.
- If neither is set, the default is used.

---

## Task 2.2 — Fix CI Cache Key (Medium)

**File:** [`.github/workflows/ci.yml:128`](../.github/workflows/ci.yml:128)

**Problem:** `cache-dependency-path: src/frontend/package-lock.json` references a file that may not exist (the frontend Dockerfile explicitly removes it).

**Fix:** Change to use `package.json` instead:
```yaml
cache-dependency-path: src/frontend/package.json
```

---

## Task 2.3 — Add ARG Declarations to Dockerfiles (Medium)

**Files:** [`docker/backend/Dockerfile`](../docker/backend/Dockerfile), [`docker/frontend/Dockerfile`](../docker/frontend/Dockerfile)

**Problem:** The CI passes `--build-arg PIP_INDEX_URL` and `--build-arg NPM_CONFIG_REGISTRY` to Docker builds, but the Dockerfiles have no `ARG` declarations, so the build args are silently ignored.

**Fix for backend Dockerfile:** Add ARG declarations before the pip config RUN command and use them:

```dockerfile
ARG PIP_INDEX_URL=https://package-mirror.liara.ir/repository/pypi/simple
ARG PIP_EXTRA_INDEX_URL=https://pypi.org/simple

RUN pip config set global.index-url ${PIP_INDEX_URL} && \
    pip config set global.extra-index-url ${PIP_EXTRA_INDEX_URL} && \
    pip config set global.trusted-host package-mirror.liara.ir && \
    pip config set global.trusted-host pypi.org && \
    pip config set global.trusted-host files.pythonhosted.org && \
    pip config set global.timeout 60 && \
    pip config set global.retries 5
```

**Fix for frontend Dockerfile:** Add ARG declarations and use them:

```dockerfile
ARG NPM_CONFIG_REGISTRY=https://mirror2.chabokan.net/npm
ARG NPM_CONFIG_STRICT_SSL=false

RUN npm config set registry ${NPM_CONFIG_REGISTRY} && \
    npm config set strict-ssl ${NPM_CONFIG_STRICT_SSL} && \
    rm -f package-lock.json && \
    npm install --no-audit --no-fund
```

Also remove the first RUN block (lines 8-9) that sets a different registry — it's overwritten by the second RUN.

---

## Task 2.4 — Fix Nginx Health Check Header (Medium)

**File:** [`docker/nginx/nginx.conf:88-92`](../docker/nginx/nginx.conf:88)

**Problem:** `return` executes before `add_header`, so `Content-Type` is never set.

**Fix:** Move `add_header` before `return`:

```nginx
location /health/ {
    access_log off;
    add_header Content-Type text/plain;
    return 200 "healthy\n";
}
```

---

## Task 3.1 — Replace `datetime.utcnow()` (Low)

**Files:** [`src/backend/core/views.py`](../src/backend/core/views.py) (after merge from Task 1.2)

**Problem:** `datetime.utcnow()` is deprecated in Python 3.12+.

**Fix:** Replace all occurrences with `datetime.now(timezone.utc)`:
```python
from datetime import datetime, timezone
# ...
'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
```

This applies to all 6 locations across the health check views.

---

## Task 3.2 — Consolidate Frontend Dockerfile (Low)

**File:** [`docker/frontend/Dockerfile:8-20`](../docker/frontend/Dockerfile:8)

**Problem:** The first RUN sets registry to `package-mirror.liara.ir`, then the second RUN overrides it to `mirror2.chabokan.net`. The first layer is wasted.

**Fix:** This is already handled in Task 2.3 above — remove the first RUN block entirely and keep only the consolidated second RUN with ARG support.

---

## Task 3.3 — Remove Backend Dependency from Worker (Low)

**File:** [`docker-compose.yml:130`](../docker-compose.yml:130)

**Problem:** `celery_worker` depends on `backend`, but the worker only needs PostgreSQL and Redis.

**Fix:** Remove `backend` from `celery_worker.depends_on`:

```yaml
celery_worker:
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

---

## Task 3.4 — Sync `celery_beat` Environment Variables (Low)

**File:** [`docker-compose.yml:163-183`](../docker-compose.yml:163)

**Problem:** `celery_beat` is missing many env vars that `celery_worker` has.

**Fix:** Add the missing environment variables to `celery_beat` to match `celery_worker`:

```yaml
celery_beat:
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      DJANGO_SECRET_KEY: ${DJANGO_SECRET_KEY}
      DJANGO_DEBUG: ${DJANGO_DEBUG:-True}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY}
      GEMINI_EMBEDDING_MODEL: ${GEMINI_EMBEDDING_MODEL:-gemini-embedding-001}
      CHAT_PROVIDER: ${CHAT_PROVIDER:-openai}
      CHAT_API_KEY: ${CHAT_API_KEY}
      CHAT_BASE_URL: ${CHAT_BASE_URL:-https://api.openai.com/v1}
      OPENAI_CHAT_MODEL: ${OPENAI_CHAT_MODEL:-deepseek-chat}
      OPENAI_CHAT_MAX_TOKENS: ${OPENAI_CHAT_MAX_TOKENS:-4096}
      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://host.docker.internal:11434}
      OLLAMA_EMBEDDING_MODEL: ${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}
      OLLAMA_CHAT_MODEL: ${OLLAMA_CHAT_MODEL:-llama3}
      EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER:-ollama}
      EMBEDDING_DIMENSION: ${EMBEDDING_DIMENSION:-768}
      CELERY_BROKER_URL: ${CELERY_BROKER_URL:-redis://redis:6379/0}
      CELERY_RESULT_BACKEND: ${CELERY_RESULT_BACKEND:-redis://redis:6379/1}
```

---

## Task 3.5 — Add Shared Test Fixtures (Low)

**File:** [`src/backend/conftest.py`](../src/backend/conftest.py)

**Problem:** The root `conftest.py` only sets `DJANGO_SETTINGS_MODULE`. No shared fixtures exist, so each test module duplicates `api_client`, `user`, `auth_headers` setup.

**Fix:** Add commonly used fixtures:

```python
"""
Root conftest for pytest-django configuration.

Provides:
- Django settings module declaration (fallback)
- Shared fixtures for all test modules
"""
from __future__ import annotations

import os

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from users.jwt_utils import create_tokens_for_user

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

User = get_user_model()


@pytest.fixture
def api_client() -> APIClient:
    """Return an unauthenticated API client."""
    return APIClient()


@pytest.fixture
def user(db) -> User:
    """Create and return a test user."""
    return User.objects.create_user(
        email="testuser@example.com",
        password="testpass123",
        full_name="Test User",
    )


@pytest.fixture
def auth_headers(user) -> dict[str, str]:
    """Return Authorization headers for the test user."""
    tokens = create_tokens_for_user(user)
    return {
        "HTTP_AUTHORIZATION": f"Bearer {tokens['accessToken']}",
    }


@pytest.fixture
def authenticated_client(api_client, auth_headers) -> APIClient:
    """Return an authenticated API client."""
    api_client.credentials(**auth_headers)
    return api_client
```

---

## Task 3.6 — Document Nginx Trailing Slash (Low)

**File:** [`docker/nginx/nginx.conf:98,130`](../docker/nginx/nginx.conf:98)

**Problem:** The trailing slash behavior difference between `/api/` and `/admin/` proxy_pass is undocumented.

**Fix:** Add comments:

```nginx
# API endpoints - proxy to Django backend
# Trailing slash on proxy_pass strips /api prefix:
#   /api/health/ -> http://backend/health/
location /api/ {
    ...
    proxy_pass http://backend/;
    ...
}

# Admin interface
# No trailing slash preserves /admin prefix:
#   /admin/ -> http://backend/admin/
location /admin/ {
    ...
    proxy_pass http://backend;
    ...
}
```

---

## Summary of Changes

| # | Task | Priority | Files Modified |
|---|------|----------|----------------|
| 1.1 | Fix CI test command | Critical | `.github/workflows/ci.yml` |
| 1.2 | Merge health check views | Critical | `config/views.py` (delete), `core/views.py` (rewrite) |
| 2.1 | Fix Celery Redis DB separation | Medium | `config/settings.py` |
| 2.2 | Fix CI cache key | Medium | `.github/workflows/ci.yml` |
| 2.3 | Add ARG declarations to Dockerfiles | Medium | `docker/backend/Dockerfile`, `docker/frontend/Dockerfile` |
| 2.4 | Fix Nginx health check header | Medium | `docker/nginx/nginx.conf` |
| 3.1 | Replace `datetime.utcnow()` | Low | `core/views.py` |
| 3.2 | Consolidate frontend Dockerfile | Low | `docker/frontend/Dockerfile` (handled in 2.3) |
| 3.3 | Remove backend dependency from worker | Low | `docker-compose.yml` |
| 3.4 | Sync celery_beat env vars | Low | `docker-compose.yml` |
| 3.5 | Add shared test fixtures | Low | `conftest.py` |
| 3.6 | Document Nginx trailing slash | Low | `docker/nginx/nginx.conf` |

## Verification Steps

After applying all changes:

1. **Run all tests:**
   ```bash
   docker-compose --profile test run --rm test
   ```

2. **Verify Docker Compose config is valid:**
   ```bash
   docker-compose config
   ```

3. **Verify the health endpoint works:**
   ```bash
   curl http://localhost:8000/health/
   ```
   Should return JSON with `status`, `timestamp`, `services` (database, redis, celery), and `version`.

4. **Update WIP context:**
   Update [`docs/active-task/wip-context.md`](../docs/active-task/wip-context.md) with:
   - What was completed (all 12 tasks)
   - Current state of the code
   - Any remaining items
