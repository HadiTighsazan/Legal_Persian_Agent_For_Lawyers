# Plan: Switch Embedding Provider from Ollama to Google Gemini API

## Overview

Replace the current Ollama-based embedding service (`nomic-embed-text`, 768-dim) with Google Gemini API (`text-embedding-004`, 768-dim) using the provided API key. This offloads computation from the laptop to Google's servers, making testing and development faster and lighter.

## Key Changes Required

### 1. Environment & Settings (`src/backend/config/settings.py`)
- Add new env var: `GOOGLE_API_KEY` (default: `''`)
- Add new env var: `GEMINI_EMBEDDING_MODEL` (default: `'text-embedding-004'`)
- Remove or keep `OLLAMA_BASE_URL` as optional (no longer required)
- Change `EMBEDDING_PROVIDER` default from `'ollama'` to `'google'`
- Update `EMBEDDING_DIMENSIONS` constant reference (currently 768 — Gemini `text-embedding-004` also returns 768, so **no migration needed**)

### 2. Embedding Service (`src/backend/documents/services/embedding_service.py`)
This is the core change. Replace all Ollama API calls with Google Gemini API calls.

**Gemini Embedding API Details:**
- Endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents?key={API_KEY}`
- Single embedding: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={API_KEY}`
- Request body for batch:
  ```json
  {
    "requests": [
      { "model": "models/text-embedding-004", "content": { "parts": [{ "text": "..." }] } },
      ...
    ]
  }
  ```
- Response: `{ "embeddings": [{ "values": [0.1, 0.2, ...] }, ...] }`
- Each embedding has `values` (list of floats) and optionally `statistics`
- Rate limit: 1500 requests per minute (free tier), 100 requests per batch

**Changes to make:**
- Replace `_get_ollama_base_url()` with `_get_gemini_base_url()` and `_get_gemini_api_key()`
- Replace `EMBEDDING_MODEL = "nomic-embed-text"` with `EMBEDDING_MODEL = settings.GEMINI_EMBEDDING_MODEL`
- Rewrite `generate_embedding()` to call Gemini `embedContent` endpoint
- Rewrite `batch_generate_embeddings()` to call Gemini `batchEmbedContents` endpoint (max 100 per batch)
- Rewrite `embed_query()` similarly
- Keep `EMBEDDING_DIMENSIONS = 768` (same as before — no migration needed)
- Keep `SUB_BATCH_SIZE` but change from 50 to 100 (Gemini allows up to 100 per batch)
- Keep retry logic but adapt for Gemini error responses

### 3. `.env.example` Update
- Add `GOOGLE_API_KEY=AIzaSyAUpCi6VZUFgvftRCVI-nq2k_i6gRbsLTU`
- Add `GEMINI_EMBEDDING_MODEL=text-embedding-004`
- Update `EMBEDDING_PROVIDER=google`
- Remove or comment out `OLLAMA_BASE_URL` and `OLLAMA_EMBEDDING_MODEL`

### 4. `docker-compose.yml` Update
- Add `GOOGLE_API_KEY: ${GOOGLE_API_KEY}` to `backend` and `celery_worker` services
- Remove or keep `OLLAMA_BASE_URL` as optional

### 5. Tests (`src/backend/documents/tests/test_embedding.py`)
- Update all mock responses from Ollama format to Gemini format
- Update mock URL assertions from Ollama to Gemini endpoints
- Update mock request body assertions
- Update `_make_fake_embedding()` — stays the same (still 768-dim)
- Update `_mock_ollama_embed_response()` → rename to `_mock_gemini_embed_response()`
- Update `_mock_ollama_single_response()` → rename to `_mock_gemini_single_response()`
- Update all `@patch` paths from `documents.services.embedding_service.requests.post` (stays the same since we still use `requests`)
- Update test assertions for the new API request/response format

### 6. Search Service (`src/backend/documents/services/search_service.py`)
- **No changes needed** — it only uses the embedding vector (768-dim), not the provider

### 7. Re-embed Script (`src/backend/scripts/reembed_all.py`)
- **No changes needed** — it just triggers the Celery task

### 8. Migration
- **No migration needed** — Gemini `text-embedding-004` also returns 768-dim vectors, same as `nomic-embed-text`

## Detailed Implementation Steps

### Step 1: Update Settings
In `src/backend/config/settings.py`:
- Add `GOOGLE_API_KEY = env('GOOGLE_API_KEY', default='')` near the existing `OPENAI_API_KEY`
- Add `GEMINI_EMBEDDING_MODEL = env('GEMINI_EMBEDDING_MODEL', default='text-embedding-004')`
- Change `EMBEDDING_PROVIDER` default from `'ollama'` to `'google'`
- Keep `OLLAMA_BASE_URL` for backward compatibility but mark as deprecated

### Step 2: Rewrite Embedding Service
Replace the entire `src/backend/documents/services/embedding_service.py`:

**New constants:**
```python
EMBEDDING_MODEL: str = "text-embedding-004"
EMBEDDING_DIMENSIONS: int = 768
SUB_BATCH_SIZE: int = 100  # Gemini allows up to 100 per batch
_MAX_RETRIES: int = 3
_TIMEOUT_SECONDS: int = 60
```

**New helper functions:**
```python
def _get_gemini_api_key() -> str:
    key = settings.GOOGLE_API_KEY
    if not key:
        raise EmbeddingError("GOOGLE_API_KEY is not configured")
    return key

def _get_gemini_base_url() -> str:
    return "https://generativelanguage.googleapis.com/v1beta"
```

**`generate_embedding(text)` → Gemini `embedContent`:**
```python
url = f"{base_url}/models/{EMBEDDING_MODEL}:embedContent?key={api_key}"
payload = {
    "model": f"models/{EMBEDDING_MODEL}",
    "content": {"parts": [{"text": text}]}
}
response = requests.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
embedding = response.json()["embedding"]["values"]
```

**`batch_generate_embeddings(texts)` → Gemini `batchEmbedContents`:**
```python
url = f"{base_url}/models/{EMBEDDING_MODEL}:batchEmbedContents?key={api_key}"
requests_payload = [
    {
        "model": f"models/{EMBEDDING_MODEL}",
        "content": {"parts": [{"text": t}]}
    }
    for t in valid_texts
]
payload = {"requests": requests_payload}
response = requests.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
embeddings = [item["values"] for item in response.json()["embeddings"]]
```

**`embed_query(text)` → Same as `generate_embedding` but raises on failure.**

### Step 3: Update `.env.example`
Add the new variables and update defaults.

### Step 4: Update `docker-compose.yml`
Add `GOOGLE_API_KEY` environment variable to `backend` and `celery_worker` services.

### Step 5: Update Tests
Rewrite all mock responses and assertions to match Gemini API format.

### Step 6: Run Tests
```bash
docker-compose exec backend pytest documents/tests/test_embedding.py -v
```

## Gemini API Response Format Reference

### Single Embedding (`embedContent`)
**Request:**
```json
POST https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key=API_KEY
{
  "model": "models/text-embedding-004",
  "content": { "parts": [{ "text": "Hello world" }] }
}
```

**Response:**
```json
{
  "embedding": {
    "values": [0.1, 0.2, ...],
    "statistics": { "truncated": false, "token_count": 3 }
  }
}
```

### Batch Embedding (`batchEmbedContents`)
**Request:**
```json
POST https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents?key=API_KEY
{
  "requests": [
    { "model": "models/text-embedding-004", "content": { "parts": [{ "text": "First" }] } },
    { "model": "models/text-embedding-004", "content": { "parts": [{ "text": "Second" }] } }
  ]
}
```

**Response:**
```json
{
  "embeddings": [
    { "values": [0.1, 0.2, ...] },
    { "values": [0.3, 0.4, ...] }
  ]
}
```

## Files to Modify (Summary)

| File | Action |
|------|--------|
| `src/backend/config/settings.py` | Add `GOOGLE_API_KEY`, `GEMINI_EMBEDDING_MODEL`, change `EMBEDDING_PROVIDER` default |
| `src/backend/documents/services/embedding_service.py` | Rewrite all functions to use Gemini API |
| `.env.example` | Add Google API vars, update defaults |
| `docker-compose.yml` | Add `GOOGLE_API_KEY` env to backend & celery_worker |
| `src/backend/documents/tests/test_embedding.py` | Update all mocks & assertions for Gemini format |

## Files NOT Modified (No Changes Needed)

| File | Reason |
|------|--------|
| `src/backend/documents/models.py` | `VectorField(dimensions=768)` stays the same |
| `src/backend/documents/services/search_service.py` | Only uses vectors, not provider |
| `src/backend/documents/migrations/*` | No schema change needed |
| `src/backend/scripts/reembed_all.py` | Only triggers Celery tasks |
| `src/backend/documents/tasks/embedding_tasks.py` | Only calls `batch_generate_embeddings` — no provider logic |
| `src/backend/requirements.txt` | Already has `requests` and `openai` — Gemini uses REST, no new deps needed |

## Mermaid Diagram: Data Flow After Change

```mermaid
flowchart LR
    A[Document Upload] --> B[Chunking Service]
    B --> C[DocumentChunk created<br/>embedding=NULL]
    C --> D[Celery Task: embed_document]
    D --> E[embedding_service.py<br/>batch_generate_embeddings]
    E --> F[Google Gemini API<br/>batchEmbedContents]
    F --> G[768-dim vector returned]
    G --> H[Save to DocumentChunk.embedding]
    H --> I[Search: pgvector CosineDistance]
```

## Risk Assessment

1. **API Key Exposure**: The key is stored in `.env` and passed as env var — standard practice. No risk.
2. **Rate Limiting**: Free tier of Gemini API allows 1500 requests/min. With batch size of 100, this is ~15 batches/min = very comfortable.
3. **Cost**: Gemini `text-embedding-004` is free for up to 50,000 requests/day on the free tier.
4. **Downtime**: If Google API is unreachable, retry logic handles it. No local fallback needed for dev.
5. **Dimension Mismatch**: Both models output 768-dim — no migration or re-embedding needed for existing data.
