# WIP Context — OpenRouter Embedding Provider + Database Cleanup

## What Was Just Completed

### Phase 1: Created OpenRouter Embedding Provider

**Files Created:**
- [`src/backend/providers/openrouter_embedding.py`](src/backend/providers/openrouter_embedding.py) — New `OpenRouterEmbeddingProvider` class that uses `openai.OpenAI(api_key=..., base_url=...)` pointed at `https://openrouter.ai/api/v1`. Implements `embed()`, `embed_batch()`, `embed_query()`, and `dimensions` property.

**Files Modified:**
- [`src/backend/config/settings.py`](src/backend/config/settings.py) — Added `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_EMBEDDING_MODEL` settings (both `env()` defaults and assignments).
- [`src/backend/providers/registration.py`](src/backend/providers/registration.py) — Imported and registered `OpenRouterEmbeddingProvider` as `"openrouter"`.
- [`docker-compose.yml`](docker-compose.yml) — Added OpenRouter env vars to `test`, `backend`, `celery_worker`, `celery_beat` services.
- [`.env.example`](.env.example) — Added OpenRouter configuration section.

### Phase 2: Cleaned Up Dirty Database & Fixed Mount Path

**Changes:**
- Fixed chunked_datasets mount path: `C:/Users/starlap/Desktop/chunked_datasets` → `C:/Users/starlap/Desktop/Developer_Tools/chunked_datasets` (both backend and celery_worker services)
- Stopped all containers (`docker-compose down`)
- Removed dirty PostgreSQL volume (`docker volume rm docuchat_postgres_data`)
- Created `.env` with OpenRouter API key and `EMBEDDING_PROVIDER=openrouter`
- Restarted all containers (`docker-compose up -d`)

### Phase 3: Imported and Re-embedded All Chunked Datasets

**Import Summary:**
```
Files processed:     6
Documents created:   3072
Chunks created:      18927
Chunks embedded:     18927
Skipped:             2 (empty text chunks)
```

**All 6 JSON files were processed** (matching the 6 files in `C:\Users\starlap\Desktop\Developer_Tools\chunked_datasets`):

| Folder | File | Embedded |
|--------|------|----------|
| هاب قوانین مصوب | chunks_قانون_مجازات_اسلامی.json | ✅ |
| هاب قوانین مصوب | chunks_قوانین_مهم.json | ✅ |
| هاب رویه های قضایی | chunks_آرای_هیئت_عمومی_دیوان_عدالت_اداری.json | ✅ |
| هاب رویه های قضایی | chunks_آرای_وحدت_رویه.json | ✅ |
| هاب نظریات مشورتی و رویه عملی | chunks_مشروح_نشست_های_قضایی.json | ✅ |
| هاب نظریات مشورتی و رویه عملی | chunks_نظرات_مشورتی.json | ✅ |

**Embeddings generated via OpenRouter API** (`bge-m3` model, 1024-dim vectors) — 0 chunks with missing embeddings.

### Current State

- **Embedding provider:** `openrouter` (bge-m3 via OpenRouter API)
- **Chat provider:** `openai` (uses OpenRouter base URL for chat as well, via `CHAT_API_KEY` and `CHAT_BASE_URL`)
- **Database:** Fresh PostgreSQL with all 18,927 chunks embedded
- **All containers healthy:** postgres, redis, backend, celery_worker, celery_beat, frontend, nginx

## Next Steps

1. Verify the system works by running the backend test suite: `docker-compose exec backend pytest`
2. Or test the RAG pipeline by sending a query via the frontend

## Reference Doc Changes

**No changes to database schema or API endpoints.** The OpenRouter provider follows the same pattern as existing providers and uses existing settings infrastructure (only new env vars added).
