
---

# PRD: E01 - Project Scaffolding & DevOps

**Epic ID:** E01  
**Title:** Project Scaffolding & DevOps  
**Status:** ⏳ Todo  


---

## Overview

Initialize the complete monorepo structure with Docker Compose orchestration for Django backend, PostgreSQL with pgvector extension, Redis, Celery workers, and Nginx reverse proxy. Configure environment variables, use Iranian/local package mirrors, and prepare CI skeleton.

---

## Tech Stack Reference

- **Frontend:** React, Vite, TailwindCSS, shadcn/ui
- **Backend:** Django, Django REST Framework, PostgreSQL, pgvector, Celery, Redis
- **AI/Document Processing:** LangChain, PyMuPDF, OpenAI API
- **Testing:** Vitest, React Testing Library, Pytest
- **DevOps:** Docker, Nginx, Gunicorn

---

## Database Tables (from `database-schema.md`)

This epic does **not** create new tables but ensures the infrastructure is ready for:

- `users` (id, email, password_hash, full_name, is_active, is_staff)
- `documents` (id, user_id, title, original_filename, status, created_at)
- `conversations` (id, user_id, document_id, title, updated_at)

**Action:** Ensure PostgreSQL container has `pgvector` extension enabled.

---

## API Endpoints (from `api-registry.md`)

This epic does **not** implement endpoints but prepares the Django backend to serve:

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`
- `POST /documents/upload`

**Action:** Ensure Django + DRF + Gunicorn + Nginx stack is ready to handle these routes in future epics.

---

## Micro-Tasks (Execute in Order)

### **MT-01: Initialize Monorepo Structure**

**Goal:** Create the root directory structure and placeholder files.

**Steps:**

1. Create the following directories:
      /
   ├── docs/
   │   ├── active-task/
   │   └── references/
   ├── src/
   │   ├── backend/
   │   └── frontend/
   ├── docker/
   │   ├── backend/
   │   ├── frontend/
   │   └── nginx/
   └── .github/
       └── workflows/
   ```

2. Create placeholder files:
   - `README.md` (root)
   - `.gitignore` (root, include Python, Node, Docker, IDE artifacts)
   - `.env.example` (root, template for environment variables)
   - `docker-compose.yml` (root)

3. **Do NOT** search for files using `list_dir` or `search_files`. Use exact paths per `.clinerules`.

**Acceptance Criteria:**

- Directory structure matches the map above.
- `.gitignore` includes `__pycache__`, `node_modules`, `.env`, `*.pyc`, `.vscode`, `.idea`, `dist/`, `build/`.
- `.env.example` includes placeholders for `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `REDIS_URL`, `DJANGO_SECRET_KEY`, `OPENAI_API_KEY`.

**Reference:** `.clinerules` section 1 (project directory map).

---

### **MT-02: Configure Docker Compose (PostgreSQL + Redis)**

**Goal:** Define `docker-compose.yml` with PostgreSQL (pgvector) and Redis services.

**Steps:**

1. Open `docker-compose.yml`.
2. Define services:
   - **postgres:**
     - Image: `pgvector/pgvector:pg16` (or latest stable)
     - Environment: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` from `.env`
     - Volumes: `postgres_data:/var/lib/postgresql/data`
     - Ports: `5432:5432`
     - Healthcheck: `pg_isready -U ${POSTGRES_USER}`
   - **redis:**
     - Image: `redis:7-alpine`
     - Ports: `6379:6379`
     - Healthcheck: `redis-cli ping`

3. Define volumes:
   ```yaml
   volumes:
     postgres_data:
   ```

**Acceptance Criteria:**

- `docker-compose up postgres redis` starts both services.
- PostgreSQL has `pgvector` extension available (verify with `SELECT * FROM pg_available_extensions WHERE name='vector';`).
- Redis responds to `redis-cli ping`.

**Reference:** `database-schema.md` (requires pgvector for embeddings).

---

### **MT-03: Configure Django Backend Service in Docker**

**Goal:** Add Django backend service to `docker-compose.yml` using Iranian package mirrors.

**Steps:**

1. Create `docker/backend/Dockerfile`:
   - Base image: `python:3.11-slim`
   - Set working directory: `/app`
   - **Use Iranian PyPI mirror:**
     ```dockerfile
     RUN pip config set global.index-url https://mirror-pypi.runflare.com/simple
     ```
     (Alternative: `https://package-mirror.liara.ir/repository/pypi/simple`)
   - Copy `requirements.txt` and install dependencies.
   - Copy `src/backend/` to `/app/`.
   - Expose port `8000`.
   - CMD: `gunicorn config.wsgi:application --bind 0.0.0.0:8000`

2. Create `src/backend/requirements.txt`:
   ```
   Django==5.0.*
   djangorestframework==3.14.*
   psycopg2-binary==2.9.*
   celery==5.3.*
   redis==5.0.*
   gunicorn==21.2.*
   python-dotenv==1.0.*
   djangorestframework-simplejwt==5.3.*
   langchain==0.1.*
   pymupdf==1.23.*
   openai==1.10.*
   pgvector==0.2.*
   ```

3. Add `backend` service to `docker-compose.yml`:
   - Build: `./docker/backend`
   - Depends on: `postgres`, `redis`
   - Environment: `DATABASE_URL`, `REDIS_URL`, `DJANGO_SECRET_KEY`, `OPENAI_API_KEY`
   - Volumes: `./src/backend:/app`
   - Ports: `8000:8000`
   - Command: `gunicorn config.wsgi:application --bind 0.0.0.0:8000 --reload`

**Acceptance Criteria:**

- Dockerfile builds successfully using Iranian PyPI mirror.
- `docker-compose up backend` starts Django on port 8000.
- Django connects to PostgreSQL and Redis (verify in logs).

**Reference:** `.clinerules` section 2 (tech stack), user requirement (Iranian mirrors).

---

### **MT-04: Configure Celery Worker Service in Docker**

**Goal:** Add Celery worker service to `docker-compose.yml`.

**Steps:**

1. Add `celery_worker` service to `docker-compose.yml`:
   - Build: `./docker/backend` (same Dockerfile as backend)
   - Depends on: `postgres`, `redis`, `backend`
   - Environment: same as `backend`
   - Volumes: `./src/backend:/app`
   - Command: `celery -A config worker --loglevel=info`

2. Add `celery_beat` service (optional, for scheduled tasks):
   - Build: `./docker/backend`
   - Depends on: `postgres`, `redis`, `backend`
   - Environment: same as `backend`
   - Volumes: `./src/backend:/app`
   - Command: `celery -A config beat --loglevel=info`

**Acceptance Criteria:**

- `docker-compose up celery_worker` starts Celery worker.
- Worker connects to Redis broker (verify in logs).
- No errors in Celery startup logs.

**Reference:** `.clinerules` section 2 (tech stack includes Celery).

---

### **MT-05: Configure Nginx Reverse Proxy**

**Goal:** Add Nginx service to `docker-compose.yml` to proxy backend and serve frontend static files.

**Steps:**

1. Create `docker/nginx/Dockerfile`:
   - Base image: `nginx:alpine`
   - Copy `nginx.conf` to `/etc/nginx/nginx.conf`

2. Create `docker/nginx/nginx.conf`:
   - Upstream `backend` pointing to `backend:8000`
   - Server block:
     - Listen on port `80`
     - Location `/api/` → proxy to `backend`
     - Location `/admin/` → proxy to `backend`
     - Location `/` → serve static files from `/usr/share/nginx/html` (frontend build)

3. Add `nginx` service to `docker-compose.yml`:
   - Build: `./docker/nginx`
   - Depends on: `backend`
   - Ports: `80:80`
   - Volumes: `./src/frontend/dist:/usr/share/nginx/html:ro`

**Acceptance Criteria:**

- `docker-compose up nginx` starts Nginx on port 80.
- `curl http://localhost/api/` proxies to Django backend.
- Nginx logs show successful proxying.

**Reference:** `.clinerules` section 2 (tech stack includes Nginx).

---

### **MT-06: Configure Frontend Service (Vite + React)**

**Goal:** Add frontend service to `docker-compose.yml` using Iranian npm mirrors.

**Steps:**

1. Create `docker/frontend/Dockerfile`:
   - Base image: `node:20-alpine`
   - Set working directory: `/app`
   - **Use Iranian npm mirror:**
     ```dockerfile
     RUN npm config set registry https://mirror-npm.runflare.com
     ```
     (Alternative: `https://package-mirror.liara.ir/repository/npm/`)
   - Copy `package.json` and `package-lock.json`, run `npm install`.
   - Copy `src/frontend/` to `/app/`.
   - Expose port `5173`.
   - CMD: `npm run dev -- --host`

2. Create `src/frontend/package.json`:
   ```json
   {
     "name": "frontend",
     "version": "1.0.0",
     "scripts": {
       "dev": "vite",
       "build": "vite build",
       "preview": "vite preview",
       "test": "vitest --run"
     },
     "dependencies": {
       "react": "^18.2.0",
       "react-dom": "^18.2.0"
     },
     "devDependencies": {
       "@vitejs/plugin-react": "^4.2.0",
       "vite": "^5.0.0",
       "vitest": "^1.0.0",
       "@testing-library/react": "^14.0.0",
       "tailwindcss": "^3.4.0",
       "typescript": "^5.3.0"
     }
   }
   ```

3. Add `frontend` service to `docker-compose.yml`:
   - Build: `./docker/frontend`
   - Volumes: `./src/frontend:/app`, `/app/node_modules`
   - Ports: `5173:5173`
   - Environment: `VITE_API_BASE_URL=http://localhost/api`

**Acceptance Criteria:**

- Dockerfile builds successfully using Iranian npm mirror.
- `docker-compose up frontend` starts Vite dev server on port 5173.
- Frontend can reach backend via Nginx proxy.

**Reference:** `.clinerules` section 2 (tech stack: React, Vite, TailwindCSS), user requirement (Iranian mirrors).

---

### **MT-07: Environment Configuration & .env Setup**

**Goal:** Finalize `.env.example` and document environment variables.

**Steps:**

1. Update `.env.example` with all required variables:
   ```
   # Database
   POSTGRES_DB=docuchat_db
   POSTGRES_USER=docuchat_user
   POSTGRES_PASSWORD=changeme
   DATABASE_URL=postgresql://docuchat_user:changeme@postgres:5432/docuchat_db

   # Redis
   REDIS_URL=redis://redis:6379/0

   # Django
   DJANGO_SECRET_KEY=changeme-generate-a-secure-key
   DJANGO_DEBUG=True
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

   # OpenAI
   OPENAI_API_KEY=sk-...

   # Frontend
   VITE_API_BASE_URL=http://localhost/api
   ```

2. Add instructions in `README.md`:
   - Copy `.env.example` to `.env`
   - Fill in `DJANGO_SECRET_KEY` (use `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
   - Fill in `OPENAI_API_KEY`

**Acceptance Criteria:**

- `.env.example` includes all variables used in `docker-compose.yml`.
- `README.md` has clear setup instructions.
- No hardcoded secrets in any file.

**Reference:** `.clinerules` section 1 (project directory map), security best practices.

---

### **MT-08: CI Skeleton (GitHub Actions)**

**Goal:** Create a basic CI workflow for linting and testing.

**Steps:**

1. Create `.github/workflows/ci.yml`:
   ```yaml
   name: CI

   on:
     push:
       branches: [main, develop]
     pull_request:
       branches: [main, develop]

   jobs:
     backend-tests:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         - name: Set up Python
           uses: actions/setup-python@v4
           with:
             python-version: '3.11'
         - name: Install dependencies
           run: |
             pip config set global.index-url https://mirror-pypi.runflare.com/simple
             pip install -r src/backend/requirements.txt
             pip install pytest pytest-django
         - name: Run tests
           run: |
             cd src/backend
             pytest

     frontend-tests:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         - name: Set up Node
           uses: actions/setup-node@v3
           with:
             node-version: '20'
         - name: Install dependencies
           run: |
             cd src/frontend
             npm config set registry https://mirror-npm.runflare.com
             npm install
         - name: Run tests
           run: |
             cd src/frontend
             npm run test
   ```

**Acceptance Criteria:**

- CI workflow file is valid YAML.
- Workflow uses Iranian mirrors for both Python and Node.
- Workflow runs on push/PR to `main` and `develop` branches.

**Reference:** `.clinerules` section 2 (tech stack includes Pytest, Vitest), user requirement (Iranian mirrors).

---

### **MT-09: Initialize Django Project Structure**

**Goal:** Create minimal Django project inside `src/backend/`.

**Steps:**

1. Inside `src/backend/`, create:
   ```
   src/backend/
   ├── config/
   │   ├── __init__.py
   │   ├── settings.py
   │   ├── urls.py
   │   ├── wsgi.py
   │   └── celery.py
   ├── manage.py
   └── apps/
       └── __init__.py
   ```

2. In `config/settings.py`:
   - Use `python-dotenv` to load `.env`
   - Configure `DATABASES` using `DATABASE_URL`
   - Configure `CACHES` using `REDIS_URL`
   - Add `rest_framework`, `rest_framework_simplejwt` to `INSTALLED_APPS`
   - Set `SECRET_KEY` from environment
   - Set `DEBUG` from environment
   - Set `ALLOWED_HOSTS` from environment

3. In `config/celery.py`:
   - Initialize Celery app with Redis broker

4. In `manage.py`:
   - Standard Django management script

**Acceptance Criteria:**

- `python manage.py check` runs without errors inside Docker container.
- Django connects to PostgreSQL and Redis.
- `python manage.py migrate` creates default Django tables.

**Reference:** `.clinerules` section 2 (tech stack: Django, DRF), `database-schema.md` (PostgreSQL).

---

### **MT-10: Initialize Frontend Project Structure**

**Goal:** Create minimal Vite + React project inside `src/frontend/`.

**Steps:**

1. Inside `src/frontend/`, create:
   ```
   src/frontend/
   ├── index.html
   ├── vite.config.ts
   ├── tsconfig.json
   ├── tailwind.config.js
   ├── postcss.config.js
   ├── src/
   │   ├── main.tsx
   │   ├── App.tsx
   │   └── index.css
   └── public/
   ```

2. In `vite.config.ts`:
   - Configure React plugin
   - Set server host to `0.0.0.0` for Docker

3. In `tailwind.config.js`:
   - Configure content paths: `./src/**/*.{js,ts,jsx,tsx}`

4. In `src/App.tsx`:
   - Simple "Hello DocuChat" component

**Acceptance Criteria:**

- `npm run dev` starts Vite dev server inside Docker container.
- Browser shows "Hello DocuChat" at `http://localhost:5173`.
- TailwindCSS classes work.

**Reference:** `.clinerules` section 2 (tech stack: React, Vite, TailwindCSS).

---

### **MT-11: Verify Full Stack Integration**

**Goal:** Ensure all services start together and communicate.

**Steps:**

1. Run `docker-compose up --build`.
2. Verify all services are healthy:
   - `postgres` (port 5432)
   - `redis` (port 6379)
   - `backend` (port 8000)
   - `celery_worker` (no port, check logs)
   - `nginx` (port 80)
   - `frontend` (port 5173)

3. Test connectivity:
   - `curl http://localhost/api/admin/` → Django admin login page
   - `curl http://localhost:5173` → Vite dev server response
   - Check Celery worker logs for "ready" message

4. Run Django migrations: `docker-compose exec backend python manage.py migrate`

**Acceptance Criteria:**

- All 6 services start without errors.
- Nginx proxies `/api/` to Django backend.
- Frontend can fetch from backend via Nginx.
- Celery worker is connected to Redis.

**Reference:** `.clinerules` section 2 (full tech stack), `api-registry.md` (backend endpoints).

---

### **MT-12: Update Reference Documentation**

**Goal:** Ensure `wip-context.md` is updated and reference docs are synced.

**Steps:**

1. Create/update `docs/active-task/wip-context.md`:
   - Summary: "Epic E01 completed. All services running."
   - Current state: "Docker Compose stack is operational. Django and Vite projects initialized."
   - Next step: "Ready for Epic E02 (User Authentication & Authorization)."

2. Verify `docs/references/database-schema.md` and `docs/references/api-registry.md` are unchanged (no new tables/endpoints in this epic).

3. Update root `README.md` with:
   - Quick start instructions
   - Service URLs
   - Development workflow

**Acceptance Criteria:**

- `wip-context.md` exists and is up-to-date.
- `README.md` has clear setup and usage instructions.
- No reference docs were modified (this epic is infrastructure only).

**Reference:** `.clinerules` section 5 (WIP & state management), section 6 (reference documentation rule).

---

## Final Acceptance Criteria (Epic-Level)

- [ ] Monorepo structure matches `.clinerules` directory map.
- [ ] `docker-compose up` starts all 6 services (postgres, redis, backend, celery_worker, nginx, frontend).
- [ ] All Dockerfiles use Iranian package mirrors (PyPI: `https://mirror-pypi.runflare.com/simple`, npm: `https://mirror-npm.runflare.com`).
- [ ] PostgreSQL has `pgvector` extension enabled.
- [ ] Django connects to PostgreSQL and Redis.
- [ ] Celery worker connects to Redis broker.
- [ ] Nginx proxies `/api/` and `/admin/` to Django backend.
- [ ] Frontend Vite dev server runs on port 5173.
- [ ] `.env.example` includes all required environment variables.
- [ ] CI workflow (`.github/workflows/ci.yml`) is present and uses Iranian mirrors.
- [ ] `docs/active-task/wip-context.md` is updated with completion status.
- [ ] `README.md` has setup instructions.

---

## Notes for AI Coding Assistant (Cline)

- **Do NOT use `list_dir` or `search_files`** unless absolutely necessary. Use exact paths from `.clinerules`.
- **Follow TDD flow** (RED → GREEN → REFACTOR) for any code that will be tested in future epics.
- **Update `wip-context.md`** after completing each micro-task.
- **Use Iranian mirrors** for all package installations (PyPI, npm).
- **Do NOT modify** `docs/references/database-schema.md` or `docs/references/api-registry.md` in this epic (no schema/API changes).
- **Stop and report** if any micro-task fails. Do not proceed to the next task.

---

**End of PRD for Epic E01**