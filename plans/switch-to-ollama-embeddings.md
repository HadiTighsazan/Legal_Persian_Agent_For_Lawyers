# Plan: Switch Embedding Provider from OpenAI to Ollama (nomic-embed-text)

## Overview

Replace the OpenAI `text-embedding-3-small` API calls with local Ollama `nomic-embed-text` model calls. This is a **development-only** change — the architecture supports swapping back to OpenAI by changing a single setting.

## Key Changes Summary

| Area | Change |
|------|--------|
| [`src/backend/config/settings.py`](src/backend/config/settings.py) | Add `OLLAMA_BASE_URL` setting (default `http://localhost:11434`) |
| [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) | Replace OpenAI client with Ollama HTTP client; update model name, dimensions, error handling |
| [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py) | Update mocks from `openai` to `requests.post` / `httpx` |
| [`docker-compose.yml`](docker-compose.yml) | Add Ollama service; pass `OLLAMA_BASE_URL` env var to backend & celery |
| [`.env.example`](.env.example) | Add `OLLAMA_BASE_URL` and `EMBEDDING_PROVIDER` variables |
| [`docs/references/database-schema.md`](docs/references/database-schema.md) | Update embedding model reference from `text-embedding-3-small` to `nomic-embed-text` |
| [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Update after implementation |

---

## Detailed Steps

### Step 1: Add Ollama Configuration to Django Settings

**File:** [`src/backend/config/settings.py`](src/backend/config/settings.py)

Add after the existing `OPENAI_API_KEY` line (line 231):

```python
# Ollama Configuration (development embedding provider)
OLLAMA_BASE_URL = env('OLLAMA_BASE_URL', default='http://localhost:11434')
EMBEDDING_PROVIDER = env('EMBEDDING_PROVIDER', default='ollama')  # 'ollama' | 'openai'
```

Also add the env casting at the top (around line 28):
```python
OLLAMA_BASE_URL=(str, 'http://localhost:11434'),
EMBEDDING_PROVIDER=(str, 'ollama'),
```

---

### Step 2: Rewrite Embedding Service to Use Ollama

**File:** [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py)

#### What changes:

1. **Remove** `import openai` — replace with `import requests` (or `httpx`)
2. **Change constants:**
   - `EMBEDDING_MODEL` → `"nomic-embed-text"` (Ollama model name)
   - `EMBEDDING_DIMENSIONS` → `768` (nomic-embed-text outputs 768-dim vectors)
3. **Replace `_get_openai_client()`** with `_get_ollama_client()` that returns the base URL
4. **Rewrite `generate_embedding()`** to call Ollama's API:
   ```python
   def generate_embedding(text: str) -> list[float] | None:
       if not text or not text.strip():
           return None
       
       url = f"{OLLAMA_BASE_URL}/api/embeddings"
       payload = {"model": EMBEDDING_MODEL, "prompt": text}
       
       for attempt in range(_MAX_RETRIES):
           try:
               response = requests.post(url, json=payload, timeout=30)
               response.raise_for_status()
               embedding = response.json()["embedding"]
               logger.info(...)
               return embedding
           except requests.exceptions.RequestException as e:
               # retry logic similar to existing pattern
   ```
5. **Rewrite `batch_generate_embeddings()`** — since Ollama doesn't have a native batch API, iterate over texts and call `generate_embedding()` for each (or check if Ollama's `/api/embed` endpoint supports batch input)
6. **Keep all other functions** (`generate_embeddings_for_document`, `batch_embed_chunks`, `reembed_chunk`) **unchanged** — they only call the above two functions.

#### ⚠️ Important: Ollama Embedding API Details

Ollama provides two endpoints:
- `POST /api/embeddings` — single text, returns `{"embedding": [...]}`
- `POST /api/embed` — batch input via `{"model": "...", "input": ["text1", "text2"]}`, returns `{"embeddings": [[...], [...]]}`

**Recommendation:** Use `/api/embed` for batch calls (more efficient) and `/api/embeddings` for single calls.

#### ⚠️ Dimension Change: 1536 → 768

`nomic-embed-text` outputs **768-dimensional** vectors, while the current `VectorField` is defined as `VECTOR(1536)`. This means:

**Option A (Recommended for dev):** Keep `VECTOR(1536)` in the database but **truncate/pad** won't work. Instead, we need to either:
- Change the `VectorField(dimensions=768)` and create a new migration
- Or use a different Ollama model that outputs 1536-dim vectors

**Better Option:** Use `nomic-embed-text` with the `dimensions` parameter if supported, or switch to a model like `mxbai-embed-large` (1024) or `snowflake-arctic-embed` (1024). But the simplest approach:

**Use `nomic-embed-text` with 768 dimensions and create a migration to alter the column.**

---

### Step 3: Update the Database Column Dimension

**File:** [`src/backend/documents/models.py`](src/backend/documents/models.py)

Change line 91:
```python
embedding = VectorField(dimensions=768, null=True, blank=True)
```

**Create migration:** `src/backend/documents/migrations/0005_change_embedding_dim_to_768.py`

```python
from django.db import migrations
import pgvector.django.vector

class Migration(migrations.Migration):
    dependencies = [
        ('documents', '0004_alter_documentchunk_embedding'),
    ]
    operations = [
        # Drop the ivfflat index first (it depends on the column type)
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_chunks_embedding",
            reverse_sql="CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops)",
        ),
        # Alter the column dimension
        migrations.AlterField(
            model_name='documentchunk',
            name='embedding',
            field=pgvector.django.vector.VectorField(blank=True, dimensions=768, null=True),
        ),
        # Re-create the index
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops)",
            reverse_sql="DROP INDEX IF EXISTS idx_chunks_embedding",
        ),
    ]
```

---

### Step 4: Update Tests

**File:** [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py)

Key changes:
1. **Remove** `import openai` — no longer needed
2. **Replace all `@patch("documents.services.embedding_service._get_openai_client")`** with `@patch("documents.services.embedding_service.requests.post")` (or `httpx.post`)
3. **Update mock responses** to match Ollama's JSON response format: `{"embedding": [...]}` instead of OpenAI's object structure
4. **Update dimension assertions** from `1536` to `768`
5. **Update the `_make_fake_embedding()`** helper to use 768 dimensions
6. **Update the `_mock_openai_response()`** helper to return Ollama-style responses
7. **Remove rate limit tests** that specifically test `openai.RateLimitError` — replace with generic `requests.exceptions.RequestException` retry tests
8. **Update the `EMBEDDING_MODEL` assertion** in `test_generate_embedding_returns_1536_floats` from `"text-embedding-3-small"` to `"nomic-embed-text"`

---

### Step 5: Add Ollama Service to Docker Compose

**File:** [`docker-compose.yml`](docker-compose.yml)

Add a new service after the `redis` service (around line 33):

```yaml
  # Ollama LLM Service (for local embeddings in development)
  ollama:
    image: ollama/ollama:latest
    container_name: docuchat_ollama
    restart: unless-stopped
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - docuchat_network
```

Also add the volume:
```yaml
volumes:
  ollama_data:
    name: docuchat_ollama_data
```

And pass `OLLAMA_BASE_URL` to the `backend` and `celery_worker` services:
```yaml
OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://ollama:11434}
```

---

### Step 6: Update Environment Variables

**File:** [`.env.example`](.env.example)

Add after the OpenAI section (around line 68):

```ini
# ============================================
# Ollama Configuration (Development Embeddings)
# ============================================

# Ollama Base URL (used when EMBEDDING_PROVIDER=ollama)
OLLAMA_BASE_URL=http://ollama:11434

# Embedding Provider (ollama for dev, openai for production)
EMBEDDING_PROVIDER=ollama
```

---

### Step 7: Update Reference Documentation

**File:** [`docs/references/database-schema.md`](docs/references/database-schema.md)

- Update the `embedding` column dimension from `VECTOR(1536)` to `VECTOR(768)`
- Update the embedding model reference from `text-embedding-3-small` to `nomic-embed-text`

**File:** [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md)

- Document the completed switch to Ollama embeddings

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph "Docker Containers"
        O[Ollama Service<br/>port 11434]
        B[Django Backend]
        C[Celery Worker]
    end

    subgraph "Embedding Flow"
        V[DocumentEmbedView] -->|POST /documents/{id}/embed| T[embed_document Celery Task]
        T --> S[EmbeddingService]
        S -->|POST /api/embed| O
        O -->|768-dim vector| S
        S -->|save| DB[(PostgreSQL<br/>pgvector)]
    end

    B -.->|OLLAMA_BASE_URL| O
    C -.->|OLLAMA_BASE_URL| O
```

---

## Execution Order

| # | Task | Files | Type |
|---|------|-------|------|
| 1 | Add Ollama settings to Django | `config/settings.py` | Modify |
| 2 | Rewrite embedding service for Ollama | `documents/services/embedding_service.py` | Modify |
| 3 | Create migration for 768-dim vector | `documents/models.py`, new migration `0005` | Modify/Create |
| 4 | Update tests | `documents/tests/test_embedding.py` | Modify |
| 5 | Add Ollama service to Docker Compose | `docker-compose.yml` | Modify |
| 6 | Update `.env.example` | `.env.example` | Modify |
| 7 | Update reference docs | `database-schema.md`, `wip-context.md` | Modify |

---

## Edge Cases & Risks

| Risk | Mitigation |
|------|-----------|
| Ollama not running when backend starts | Backend should handle connection errors gracefully (already has retry logic) |
| Dimension mismatch (768 vs 1536) | Migration handles column alteration; existing data will need re-embedding |
| Ollama model not pulled | Add an `entrypoint` or `command` to `ollama pull nomic-embed-text` on startup, or document as manual step |
| Batch performance (Ollama has no native batch) | Use `/api/embed` endpoint which accepts `input` array — more efficient than looping |
| Existing embeddings in DB with 1536 dims | Run `reembed_all.py` script after migration to regenerate all embeddings at 768 dims |
