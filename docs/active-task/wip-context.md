# WIP Context — Fix Auth Login/Register "Internal Server Error"

## What Was Just Completed

**Fixed the "Internal Server Error" on `/auth/login/` and `/auth/register/` endpoints.**

### Root Cause

After Docker infrastructure changes (multi-stage builds, image optimization), the backend Dockerfile was rewritten and no longer included a `migrate` step. The container started Gunicorn directly without ensuring database tables exist. When `register_view` or `login_view` tried to access the `users` table (which didn't exist), Django raised a `ProgrammingError`, caught by the generic `except Exception` block, returning `{"error":"Internal server error"}`.

### Changes Made

#### 1. `docker/backend/entrypoint.sh` (New File)
- Startup script that runs before Gunicorn
- Executes `python manage.py migrate --noinput` to ensure all database tables exist
- Executes `python manage.py collectstatic --noinput` to collect static files
- Supports command passthrough: if arguments are provided (e.g., Celery worker/beat commands), it executes them instead of Gunicorn
- Placed at `/entrypoint.sh` (outside `/app`) to survive the volume mount at `./src/backend:/app`

#### 2. `docker/backend/Dockerfile` (Modified)
- Added `COPY docker/backend/entrypoint.sh /entrypoint.sh` and `RUN chmod +x /entrypoint.sh`
- Changed `CMD` to `ENTRYPOINT ["/entrypoint.sh"]` so migrations run before Gunicorn starts

#### 3. `docker-compose.yml` (Modified)
- Removed `command: gunicorn ...` override from the `backend` service (now handled by the entrypoint's default behavior)
- Celery worker and beat services keep their `command` overrides, which are passed as arguments to the entrypoint

## Current State of Code

- `docker/backend/entrypoint.sh` — runs migrations, collects static files, then starts Gunicorn (or passes through to Celery commands)
- `docker/backend/Dockerfile` — uses `ENTRYPOINT ["/entrypoint.sh"]` instead of `CMD`
- `docker-compose.yml` — backend service no longer has a `command` override
- All 7 containers are running and healthy:
  - `docuchat_backend` — healthy, port 8000
  - `docuchat_celery_worker` — running
  - `docuchat_celery_beat` — running
  - `docuchat_frontend` — running, port 5173
  - `docuchat_nginx` — healthy, ports 80/443
  - `docuchat_postgres` — healthy
  - `docuchat_redis` — healthy

## Verification Results

- ✅ **Register endpoint** (`POST /auth/register/`): Returns 200 with JWT tokens
- ✅ **Login endpoint** (`POST /auth/login/`): Returns 200 with JWT tokens
- ✅ **Backend healthcheck**: Passing
- ✅ **All containers**: Up and healthy

## Next Steps

1. Open `http://localhost:5173` in the browser and manually verify:
   - Register a new user
   - Login with the registered user
   - Verify no "Internal server error" appears
2. If frontend verification passes, the fix is complete
