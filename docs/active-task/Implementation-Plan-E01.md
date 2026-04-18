# Implementation Plan for Epic E01: Project Scaffolding & DevOps

Based on my analysis of the PRD (`docs/active-task/E01-prd.md`), database schema (`docs/references/database-schema.md`), and API registry (`docs/references/api-registry.md`), I've created a detailed implementation plan for Epic E01. This epic focuses on setting up the complete infrastructure without implementing business logic.

## Key Insights from Reference Documents:

### Database Schema:
- **7 core tables**: `users`, `documents`, `document_chunks`, `conversations`, `messages`, `processing_tasks`, `api_keys`
- **PostgreSQL extensions required**: `uuid-ossp` and `vector` (pgvector)
- **Embedding dimension**: 1536 (OpenAI text-embedding-3-small)
- **All IDs are UUIDs**, timestamps in UTC

### API Registry:
- **Comprehensive API** with 20+ endpoints across authentication, documents, conversations, search, tasks, user profile, and API keys
- **JWT authentication** with refresh tokens
- **Rate limiting** configured
- **File uploads** limited to 500MB (PDF only initially)

## Implementation Plan (12 Micro-Tasks):

### **Phase 1: Infrastructure Setup (MT-01 to MT-05)**
1. **MT-01: Initialize Monorepo Structure** - Create directory tree and placeholder files
2. **MT-02: Configure Docker Compose (PostgreSQL + Redis)** - Set up database and cache services with pgvector
3. **MT-03: Configure Django Backend Service** - Create Dockerfile with Iranian PyPI mirror and requirements
4. **MT-04: Configure Celery Worker Service** - Add Celery worker and beat services
5. **MT-05: Configure Nginx Reverse Proxy** - Set up Nginx to proxy backend and serve frontend

### **Phase 2: Frontend & Environment (MT-06 to MT-08)**
6. **MT-06: Configure Frontend Service** - Create Vite/React Dockerfile with Iranian npm mirror
7. **MT-07: Environment Configuration** - Finalize `.env.example` with all required variables
8. **MT-08: CI Skeleton** - Create GitHub Actions workflow with Iranian mirrors

### **Phase 3: Project Initialization (MT-09 to MT-10)**
9. **MT-09: Initialize Django Project Structure** - Create minimal Django project with settings, celery config
10. **MT-10: Initialize Frontend Project Structure** - Create Vite + React project with TailwindCSS

### **Phase 4: Verification & Documentation (MT-11 to MT-12)**
11. **MT-11: Verify Full Stack Integration** - Test all 6 services together
12. **MT-12: Update Reference Documentation** - Update WIP context and README

## Critical Technical Decisions:

### 1. **Package Mirrors (Iranian Compliance):**
- **PyPI**: `https://mirror-pypi.runflare.com/simple` (primary), `https://package-mirror.liara.ir/repository/pypi/simple` (fallback)
- **npm**: `https://mirror-npm.runflare.com` (primary), `https://package-mirror.liara.ir/repository/npm/` (fallback)

### 2. **Docker Images:**
- **PostgreSQL**: `pgvector/pgvector:pg16` (includes pgvector extension)
- **Redis**: `redis:7-alpine`
- **Backend**: `python:3.11-slim`
- **Frontend**: `node:20-alpine`
- **Nginx**: `nginx:alpine`

### 3. **Service Ports:**
- PostgreSQL: 5432
- Redis: 6379
- Django Backend: 8000
- Nginx: 80
- Vite Dev Server: 5173

### 4. **Environment Variables Required:**
- Database: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`
- Redis: `REDIS_URL`
- Django: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- OpenAI: `OPENAI_API_KEY`
- Frontend: `VITE_API_BASE_URL`

## Risk Mitigation:

1. **Package Mirror Reliability**: Include fallback mirrors in documentation
2. **pgvector Compatibility**: Use official pgvector image to ensure extension availability
3. **Service Dependencies**: Configure proper health checks and dependency ordering in docker-compose
4. **Secret Management**: `.env.example` with clear instructions for generating secure keys

## Questions for Clarification:

1. **Database Initialization**: Should we include initial SQL to create the extensions (`uuid-ossp`, `vector`) in the PostgreSQL service setup, or rely on Django migrations?
2. **Development vs Production**: Should we create separate docker-compose files for development and production, or use environment variables?
3. **Volume Management**: For development, we're mounting source code as volumes. For production, should we copy code into images instead?
4. **Testing Strategy**: The CI workflow runs tests. Should we also include linting (flake8 for Python, ESLint for TypeScript) in the initial setup?

## Next Steps:

Once you approve this plan, I'll need you to **toggle to Act Mode** so I can begin implementing the micro-tasks in sequence. I'll follow the TDD flow (RED → GREEN → REFACTOR) for any code that will be tested and update `docs/active-task/wip-context.md` after each micro-task.

**Are you satisfied with this implementation plan? Would you like me to adjust any aspects before we proceed?**