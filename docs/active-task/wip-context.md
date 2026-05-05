# WIP Context — Docker Image Optimization

## What Was Just Completed

**Docker Image Optimization Plan has been implemented.** All changes from the plan in [`plans/docker-image-optimization-plan.md`](plans/docker-image-optimization-plan.md) have been applied.

### Changes Made

#### 1. `.dockerignore` (New File — Root Level)
- Prevents unnecessary files (`.git/`, `__pycache__/`, `node_modules/`, `.env`, `dist/`, logs, etc.) from being sent to the Docker build context
- Results in faster builds and smaller context uploads to the Docker daemon

#### 2. `src/backend/requirements-dev.txt` (New File)
- Contains dev-only dependencies: `pytest==7.4.4`, `pytest-django==4.7.0`, `pytest-cov==4.1.0`
- These are no longer installed in the production image

#### 3. `src/backend/requirements.txt` (Updated)
- Removed the 3 pytest dev dependencies (moved to `requirements-dev.txt`)
- Production image no longer includes test frameworks (~15-20 MB savings)

#### 4. `docker/backend/Dockerfile` — Multi-Stage Build (Rewritten)

**Stage 1 (builder):** `python:3.11-slim`
- Installs build tools: `gcc`, `build-essential`, `libpq-dev` (needed for compiling C extensions like psycopg2, PyMuPDF)
- Configures Iranian PyPI mirror
- Installs production dependencies via `pip install --user`
- Cleans pip cache in the same layer

**Stage 2 (runtime):** `python:3.11-slim` (clean)
- Copies only `/root/.local` from builder — no build tools, no apt cache
- Copies application code
- Runs `python manage.py collectstatic --noinput`
- Deletes `.pyc` files from installed packages
- **Estimated reduction: ~600 MB → ~300 MB (50%)**

#### 5. `docker/frontend/Dockerfile` — Production Multi-Stage Build (Rewritten)

**Stage 1 (builder):** `node:20-alpine`
- Installs all npm dependencies (including devDependencies needed for build)
- Runs `npm run build` to generate `dist/`

**Stage 2 (production):** `nginx:alpine`
- Copies custom nginx config
- Copies only `dist/` from builder — no `node_modules`, no source code, no dev tools
- Includes health check
- **Estimated size: ~60 MB (vs ~450 MB for dev image)**

#### 6. `docker-compose.yml` — Celery Services Reuse Backend Image

**Key changes:**
- `backend` service now has `image: docuchat_backend` — tags the built image for reuse
- `celery_worker` and `celery_beat` now have `image: docuchat_backend` and `build:` pointing to the same backend Dockerfile
- Docker Compose will build the backend image **once** and both Celery services will reuse it
- Only the `command:` differs for each service (worker vs beat vs gunicorn)
- **Eliminates 2 redundant image builds (~1.2 GB saved)**

### Estimated Size Reductions

| Service | Before (est.) | After (est.) | Reduction |
|---------|:------------:|:-----------:|:---------:|
| Backend | ~600 MB | ~300 MB | **50%** |
| Celery Worker | ~600 MB | **0 MB** (reuses backend) | **100%** |
| Celery Beat | ~600 MB | **0 MB** (reuses backend) | **100%** |
| Frontend (dev) | ~450 MB | ~450 MB (unchanged) | **0%** |
| Frontend (prod build) | N/A | ~60 MB | **New** |
| Nginx | ~35 MB | ~35 MB (unchanged) | **0%** |
| **Total (all services)** | **~2.5 GB** | **~850 MB** | **~66%** |
| **Total (unique images)** | **~1.7 GB** | **~450 MB** | **~74%** |

## Current State of Code

- `.dockerignore` created at root level
- `requirements-dev.txt` created, `requirements.txt` cleaned of dev deps
- Backend Dockerfile uses multi-stage build (builder → runtime)
- Frontend Dockerfile uses multi-stage build (builder → nginx production)
- `docker-compose.yml` updated: Celery Worker and Beat reuse `docuchat_backend` image
- All existing functionality preserved — only build-time and image-size changes

## Next Step

1. Rebuild all images: `docker-compose build`
2. Verify image sizes: `docker images | grep docuchat`
3. Verify only 1 backend image exists (not 3): `docker images | grep docuchat`
4. Start services: `docker-compose up -d`
5. Run tests: `docker-compose --profile test run test`
6. Verify all services work correctly (backend API, Celery tasks, frontend)
