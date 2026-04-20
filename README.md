# DocuChat - AI Document Assistant

An AI-powered document chat assistant that allows you to upload documents, ask questions, and get intelligent answers based on the document content.

## Tech Stack

- **Frontend**: React, Vite, TypeScript, TailwindCSS, shadcn/ui
- **Backend**: Django, Django REST Framework, PostgreSQL, pgvector, Celery, Redis
- **AI & Document Processing**: LangChain, PyMuPDF, OpenAI API
- **DevOps**: Docker, Nginx, Gunicorn
- **Testing**: Vitest, React Testing Library, Pytest

## Current Status (Epic E01 - Complete ✅)

**Epic E01: Project Scaffolding & DevOps** has been successfully completed. All infrastructure services are running and communicating:

### ✅ **Completed Infrastructure:**
1. **7 Services Running**: PostgreSQL, Redis, Django Backend, Celery Worker, Celery Beat, Nginx, Frontend
2. **Full Stack Integration**: Frontend connects to backend through Nginx proxy
3. **Database Ready**: PostgreSQL with pgvector extension for vector embeddings
4. **Background Processing**: Celery + Redis configured for async tasks
5. **API Routing**: Nginx routes `/api/` to Django backend

### 🔧 **Working Endpoints:**
- `GET /api/health/` - Health check (returns JSON status)
- `GET /health/` - Nginx health check (returns "healthy")
- `GET /admin/` - Django admin interface (redirects to login)

### ⚠️ **Known Issues:**
- Swagger (`/swagger/`) and ReDoc (`/redoc/`) endpoints return 500 (need DRF configuration)
- Business logic endpoints not yet implemented (Epic E02)

### 🚀 **Ready for Epic E02:**
The infrastructure is complete and ready for business logic implementation (authentication, document upload, RAG queries, etc.).

## Prerequisites

- Docker & Docker Compose
- Git
- OpenAI API Key (for AI features)

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd rag-project
   ```

2. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and fill in:
   - `DJANGO_SECRET_KEY`: Generate with:
     ```bash
     python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
     ```
   - `OPENAI_API_KEY`: Your OpenAI API key
   - Other variables as needed

3. **Start the services**
   ```bash
   docker-compose up --build
   ```

4. **Access the application**
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8000/api/v1
   - Django Admin: http://localhost:8000/admin
   - Nginx Proxy: http://localhost

## Service URLs (Epic E01 - Complete ✅)

| Service | Port | URL | Description | Status |
|---------|------|-----|-------------|--------|
| PostgreSQL | 5432 | `postgres:5432` | Database with pgvector extension | ✅ Running |
| Redis | 6379 | `redis:6379` | Cache and Celery broker | ✅ Running |
| Django Backend | 8000 | http://localhost:8000 | REST API (direct access) | ✅ Running |
| Celery Worker | - | - | Background task processing | ✅ Running |
| Celery Beat | - | - | Scheduled tasks | ✅ Running |
| Nginx | 80 | http://localhost | Reverse proxy with API routing | ✅ Running |
| Vite Dev Server | 5173 | http://localhost:5173 | Frontend development server | ✅ Running |

**Note:** Nginx routes `/api/` to Django backend. Use `http://localhost/api/health/` for API calls through proxy.

## Development Workflow

### Backend Development
```bash
# Access backend container
docker-compose exec backend bash

# Run Django commands
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000

# Run tests
pytest
```

### Frontend Development
```bash
# Access frontend container
docker-compose exec frontend sh

# Install dependencies
npm install

# Run development server
npm run dev

# Run tests
npm run test
```

## Project Structure

```
/
├── docs/                    # Documentation
│   ├── active-task/        # Current task PRDs and WIP context
│   └── references/         # Database schema, API registry
├── src/                    # Source code
│   ├── backend/           # Django backend
│   └── frontend/          # React frontend
├── docker/                # Docker configurations
│   ├── backend/          # Backend Dockerfile
│   ├── frontend/         # Frontend Dockerfile
│   └── nginx/            # Nginx configuration
├── .github/workflows/     # CI/CD pipelines
├── docker-compose.yml     # Service orchestration
├── .env.example          # Environment template
└── README.md             # This file
```

## API Documentation

See `docs/references/api-registry.md` for complete API endpoint documentation.

## Database Schema

See `docs/references/database-schema.md` for database table definitions and relationships.

## Troubleshooting

### Common Issues

1. **Port conflicts**: Ensure ports 5432, 6379, 8000, 80, and 5173 are available
2. **Docker build failures**: Check internet connectivity and package mirror availability
3. **Database connection errors**: Wait for PostgreSQL to fully initialize (may take 30+ seconds on first run)
4. **Missing environment variables**: Ensure `.env` file exists and all required variables are set

### Logs
```bash
# View all service logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f postgres
```

### Reset Development Environment
```bash
# Stop and remove containers, volumes, and networks
docker-compose down -v

# Rebuild and start fresh
docker-compose up --build
```

## Contributing

1. Follow the TDD workflow (RED → GREEN → REFACTOR)
2. Update reference documentation when modifying database schema or APIs
3. Update `docs/active-task/wip-context.md` after completing tasks
4. Use Iranian package mirrors for all installations

## License

[Add license information here]