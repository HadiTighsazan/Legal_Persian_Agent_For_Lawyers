
---

# Project Epics — Document Q&A System

| ID | Title | Description | Status |
|----|-------|-------------|--------|
| E01 | Project Scaffolding & DevOps | Initialize monorepo, Docker Compose setup (Django, PostgreSQL+pgvector, Redis, Celery, Nginx), environment config, CI skeleton | ⏳ Todo |
| E02 | Authentication & User Management | JWT-based register/login/refresh/logout, user model, profile endpoints, middleware guards | ⏳ Todo |
| E03 | Document Upload & Storage | File upload endpoint, S3/local storage abstraction, document metadata model, file validation (type, size) | ⏳ Todo |
| E04 | Document Processing Pipeline | Celery tasks for text extraction (PyMuPDF), chunking strategy, processing_tasks status tracking, error handling | ⏳ Todo |
| E05 | Embedding & Vector Storage | OpenAI embedding generation per chunk, pgvector storage, batch processing, re-embedding support | ⏳ Todo |
| E06 | Semantic Search & Retrieval | Vector similarity search endpoint, relevance scoring, top-k retrieval, metadata filtering | ⏳ Todo |
| E07 | Conversation & Q&A Engine | LangChain RAG chain, conversation/message models, context injection, citation tracking, hallucination mitigation | ⏳ Todo |
| E08 | Frontend — Auth & Layout | React + Vite + TailwindCSS + shadcn/ui setup, auth pages (login/register), protected routes, layout shell | ⏳ Todo |
| E09 | Frontend — Document Management | Upload UI, document list/detail views, processing status polling, delete flow | ⏳ Todo |
| E10 | Frontend — Chat Interface | Conversation UI, message streaming, source citation display, loading/error states | ⏳ Todo |
| E11 | Testing & Quality Assurance | Pytest for backend (TDD per `.clinerules`), Vitest + React Testing Library for frontend, coverage thresholds | ⏳ Todo |
| E12 | Production Hardening | Rate limiting, API key management, Nginx config, Gunicorn tuning, health checks, logging, security headers | ⏳ Todo |

---

