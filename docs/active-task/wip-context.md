# WIP Context — Switch Ollama Embedding Model from `nomic-embed-text` to `bge-m3`

## Status: ✅ COMPLETED (2026-05-09)

All changes from the implementation plan [`plans/plan-switch-ollama-embedding-to-bge-m3.md`](plans/plan-switch-ollama-embedding-to-bge-m3.md) have been implemented and verified.

---

## What Changed

### Summary

Switched the Ollama embedding model from `nomic-embed-text` (768-dim) to `bge-m3` (1024-dim). Since this is a fresh project with no existing data, no re-embedding was needed.

### Files Modified

| File | Change |
|------|--------|
| [`src/backend/config/settings.py`](src/backend/config/settings.py:38) | Changed `OLLAMA_EMBEDDING_MODEL` default from `'nomic-embed-text'` to `'bge-m3'` (line 38) |
| [`src/backend/config/settings.py`](src/backend/config/settings.py:39) | Changed `EMBEDDING_DIMENSION` default from `768` to `1024` (line 39) |
| [`src/backend/config/settings.py`](src/backend/config/settings.py:255) | Changed `OLLAMA_EMBEDDING_MODEL` env default from `'nomic-embed-text'` to `'bge-m3'` (line 255) |
| [`src/backend/config/settings.py`](src/backend/config/settings.py:256) | Changed `EMBEDDING_DIMENSION` env default from `768` to `1024` (line 256) |
| [`src/backend/documents/models.py`](src/backend/documents/models.py:122) | Changed `VectorField(dimensions=768)` to `VectorField(dimensions=1024)` |
| [`docker-compose.yml`](docker-compose.yml:104) | Changed `OLLAMA_EMBEDDING_MODEL` default from `nomic-embed-text` to `bge-m3` (backend, celery_worker, celery_beat) |
| [`docker-compose.yml`](docker-compose.yml:107) | Changed `EMBEDDING_DIMENSION` default from `768` to `1024` (backend, celery_worker, celery_beat) |
| [`.env.example`](.env.example:113) | Changed `OLLAMA_EMBEDDING_MODEL=nomic-embed-text` to `bge-m3` |
| [`.env.example`](.env.example:197) | Changed `EMBEDDING_DIMENSION=768` to `1024` |
| [`.env`](.env:56) | Changed `OLLAMA_EMBEDDING_MODEL=e5-small` to `bge-m3` |
| [`.env`](.env:59) | Changed `EMBEDDING_DIMENSION=384` to `1024` and updated comment |
| [`docs/references/database-schema.md`](docs/references/database-schema.md:67) | Updated `embedding` column from `VECTOR(768)` to `VECTOR(1024)` |
| [`docs/references/database-schema.md`](docs/references/database-schema.md:227) | Updated migration notes from `768 (Ollama nomic-embed-text)` to `1024 (Ollama bge-m3)` |

### Files Created

| File | Description |
|------|-------------|
| [`src/backend/documents/migrations/0013_change_embedding_dim_to_1024.py`](src/backend/documents/migrations/0013_change_embedding_dim_to_1024.py) | **NEW** — Migration that drops ivfflat index, alters `embedding` column to `VECTOR(1024)`, and re-creates the index |

### Files Not Modified (Confirmed No Changes Needed)

| File | Reason |
|------|--------|
| [`src/backend/providers/ollama_embedding.py`](src/backend/providers/ollama_embedding.py) | Reads settings dynamically — no hardcoded values |
| [`src/backend/providers/registration.py`](src/backend/providers/registration.py) | Provider registration unchanged (still `ollama`) |
| [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) | Delegates to provider — no hardcoded dimension |
| [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) | Validates dimension against settings dynamically |
| [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) | No hardcoded dimension references |
| [`src/backend/documents/checks.py`](src/backend/documents/checks.py) | pgvector index check — no dimension hardcoded |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | No embedding dimension references found |
| Frontend code | No embedding dimension references |

### Verification

- All migrations applied successfully (0013 + auto-generated 0014 faked)
- Environment variables confirmed: `OLLAMA_EMBEDDING_MODEL=bge-m3`, `EMBEDDING_DIMENSION=1024`
- Containers rebuilt and restarted successfully

### Next Steps

None — task is complete. The system is now configured to use `bge-m3` (1024-dim) for all new embeddings.
