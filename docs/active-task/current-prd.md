# PRD: Epic E06 — Semantic Search & Retrieval

**Status:** Ready for Implementation  
**Epic ID:** E06  
**Dependencies:** E05 (Embedding & Vector Storage) ✅ Done  
**Estimated Micro-Tasks:** 6  
**Output Path:** `docs/active-task/current-prd.md`

---

## Overview

This epic implements the semantic search layer that sits between the embedding pipeline (E05) and the Q&A engine (E07). The assistant must build a vector similarity search endpoint, a relevance scoring mechanism, top-k retrieval logic, and metadata filtering — all backed by pgvector's `ivfflat` index on `document_chunks.embedding`.

No new database tables are required. All work is on existing tables: `document_chunks`, `documents`, `processing_tasks`.

---

## Architectural Constraints (Non-Negotiable)

- All views must use `IsAuthenticated` DRF permission class.
- All ownership checks: `chunk.document.user != request.user` → 403.
- Error responses must follow the standard format: `{"error": "error_code", "message": "..."}`.
- All timestamps in ISO 8601 / UTC.
- Embedding model: `nomic-embed-text` via Ollama, vector dimension `VECTOR(768)` (as per `document_chunks.embedding`).
- Similarity metric: **cosine similarity** using pgvector's `<=>` operator.
- TDD: write tests first (pytest), then implementation.
- No new pip packages unless absolutely required; if needed, add to `requirements.txt`.

---

## Database — No Schema Changes Required

The following existing columns are used:

| Table | Column | Usage |
|---|---|---|
| `document_chunks` | `embedding VECTOR(768)` | Cosine similarity search via `<=>` |
| `document_chunks` | `content TEXT` | Returned in results |
| `document_chunks` | `page_start`, `page_end` | Metadata filter & response |
| `document_chunks` | `chunk_index INTEGER` | Ordering |
| `document_chunks` | `metadata JSONB` | Optional filter target |
| `document_chunks` | `token_count INTEGER` | Returned in results |
| `documents` | `user_id UUID` | Ownership check |
| `documents` | `processing_status VARCHAR` | Guard: must be `completed` |

**Index already exists:**
```sql
idx_chunks_embedding ON document_chunks USING ivfflat (embedding)
```

---

## API Contract

### New Endpoint — POST /documents/{document_id}/search

This endpoint is already declared in `api-registry.md` under **Search & Retrieval**. The implementation must match this contract exactly.

**Request:**
```json
{
  "query": "machine learning algorithms",
  "top_k": 10,
  "min_score": 0.7
}
```

**Response `200 OK`:**
```json
{
  "results": [
    {
      "chunk_id": "uuid",
      "chunk_index": 0,
      "page_start": 120,
      "page_end": 122,
      "content": "Machine learning algorithms are...",
      "relevance_score": 0.93,
      "token_count": 50,
      "metadata": {}
    }
  ],
  "query": "machine learning algorithms",
  "top_k": 10,
  "min_score": 0.7,
  "total_results": 3
}
```

**Error cases:**
- `400` — missing `query`, `top_k` < 1 or > 50, `min_score` not in [0.0, 1.0], invalid JSON
- `403` — document belongs to another user
- `404` — document does not exist
- `422` — document `processing_status` is not `completed` (no embeddings available)

---

## Micro-Tasks

---

### Task 1 — Embedding Service: Query Vectorization

**File:** `src/backend/documents/embedding_service.py` (extend existing file)  
**Goal:** Add a `embed_query(text: str) -> list[float]` function that converts a raw search string into a 768-dim vector using the same Ollama model used for chunk embedding.

**Steps:**
1. In `embedding_service.py`, add function `embed_query(text: str) -> list[float]`.
2. Reuse the existing Ollama client / model config (`nomic-embed-text`, same base URL).
3. The function must raise `EmbeddingError` (or equivalent existing exception) on failure.
4. Return a plain Python `list[float]` of length 768.

**Tests (`tests/test_embedding_service.py`):**
- `test_embed_query_returns_768_floats` — mock Ollama, assert len == 768
- `test_embed_query_raises_on_ollama_failure` — mock failure, assert exception raised

**Acceptance Criteria:**
- [ ] `embed_query("hello world")` returns a list of 768 floats.
- [ ] Exception is raised cleanly when Ollama is unreachable.
- [ ] No new model or API key introduced — reuses existing Ollama config.

---

### Task 2 — Search Service: Vector Similarity Query

**File:** `src/backend/documents/search_service.py` (new file)  
**Goal:** Implement the core search logic as a pure service function, separate from the view.

**Function signature:**
```python
def search_chunks(
    document_id: str,
    query_vector: list[float],
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict]:
```

**Steps:**
1. Create `src/backend/documents/search_service.py`.
2. Use Django ORM + pgvector's `CosineDistance` annotation (from `pgvector.django`) to query `DocumentChunk`.
3. Filter: `document_id=document_id`, `embedding__isnull=False`.
4. Annotate with `distance = CosineDistance("embedding", query_vector)`.
5. Compute `relevance_score = 1 - distance` (cosine similarity from distance).
6. Filter annotated queryset: `relevance_score >= min_score`.
7. Order by `distance ASC` (lowest distance = highest similarity).
8. Limit to `top_k` results.
9. Return list of dicts with keys: `chunk_id`, `chunk_index`, `page_start`, `page_end`, `content`, `relevance_score`, `token_count`, `metadata`.

**Tests (`tests/test_search_service.py`):**
- `test_search_chunks_returns_top_k` — seed 5 chunks with known embeddings, assert only top_k returned
- `test_search_chunks_filters_by_min_score` — assert chunks below threshold excluded
- `test_search_chunks_excludes_unembedded_chunks` — chunk with `embedding=NULL` must not appear
- `test_search_chunks_orders_by_relevance` — assert results descending by `relevance_score`
- `test_search_chunks_empty_result` — no matching chunks returns `[]`

**Acceptance Criteria:**
- [ ] Service is decoupled from HTTP layer (no `request` object).
- [ ] Uses pgvector `CosineDistance`, not raw SQL.
- [ ] NULL embeddings are excluded.
- [ ] Results are ordered highest relevance first.

---

### Task 3 — Request/Response Serializers

**File:** `src/backend/documents/serializers.py` (extend existing)  
**Goal:** Add serializers for the search endpoint request validation and response formatting.

**Add `SearchRequestSerializer`:**
```python
fields: query (str, required, max_length=1000),
        top_k (int, optional, default=10, min=1, max=50),
        min_score (float, optional, default=0.0, min=0.0, max=1.0)
```

**Add `SearchResultSerializer`:**
```python
fields: chunk_id (UUIDField),
        chunk_index (IntegerField),
        page_start (IntegerField),
        page_end (IntegerField),
        content (CharField),
        relevance_score (FloatField),
        token_count (IntegerField, allow_null=True),
        metadata (JSONField)
```

**Add `SearchResponseSerializer`:**
```python
fields: results (SearchResultSerializer, many=True),
        query (str),
        top_k (int),
        min_score (float),
        total_results (int)
```

**Tests (`tests/test_serializers.py` — extend existing):**
- `test_search_request_defaults` — omitting `top_k` and `min_score` gives defaults 10 and 0.0
- `test_search_request_top_k_max_validation` — `top_k=51` fails validation
- `test_search_request_min_score_range` — `min_score=-0.1` and `min_score=1.1` fail validation
- `test_search_request_empty_query` — empty string fails validation

**Acceptance Criteria:**
- [ ] `top_k` clamped to [1, 50].
- [ ] `min_score` clamped to [0.0, 1.0].
- [ ] All fields have correct types and defaults.

---

### Task 4 — Search View

**File:** `src/backend/documents/views.py` (extend existing)  
**Goal:** Implement `DocumentSearchView` and wire it to the URL.

**Steps:**
1. Create `DocumentSearchView(APIView)` in `views.py`.
2. `permission_classes = [IsAuthenticated]`
3. `POST` handler:
   a. Fetch `Document` by `document_id`; 404 if not found.
   b. Check `document.user != request.user`; 403 if mismatch.
   c. Check `document.processing_status != 'completed'`; return 422 with `{"error": "document_not_ready", "message": "Document processing is not complete. Embeddings may not be available."}`.
   d. Validate request body with `SearchRequestSerializer`; 400 on failure.
   e. Call `embed_query(validated_data['query'])` to get query vector.
   f. Call `search_chunks(document_id, query_vector, top_k, min_score)`.
   g. Serialize response with `SearchResponseSerializer`.
   h. Return `200 OK`.
4. Register URL in `src/backend/documents/urls.py`:
   ```python
   path("<uuid:document_id>/search/", DocumentSearchView.as_view(), name="document-search")
   ```
5. Confirm the URL is included in `config/urls.py` under the `documents/` prefix (it should already be if following existing pattern).

**Tests (`tests/test_views.py` — extend existing):**
- `test_search_requires_auth` — unauthenticated request returns 401
- `test_search_document_not_found` — wrong UUID returns 404
- `test_search_document_wrong_user` — other user's document returns 403
- `test_search_document_not_completed` — `processing_status='processing'` returns 422
- `test_search_valid_request` — mock `embed_query` + `search_chunks`, assert 200 with correct shape
- `test_search_invalid_top_k` — `top_k=0` returns 400
- `test_search_empty_results` — valid request with no matches returns 200 with empty `results`

**Acceptance Criteria:**
- [ ] Endpoint is `POST /documents/{document_id}/search/`.
- [ ] All error codes match the table above.
- [ ] 422 returned (not 400) for non-completed documents.
- [ ] Response shape matches `SearchResponseSerializer` exactly.

---

### Task 5 — Performance: ivfflat Index Probe Tuning

**File:** `src/backend/documents/search_service.py`  
**Goal:** Set `ivfflat.probes` per-query to balance recall vs. speed, and document the tradeoff.

**Steps:**
1. Before executing the similarity query, run:
   ```python
   from django.db import connection
   with connection.cursor() as cursor:
       cursor.execute("SET ivfflat.probes = %s", [probes])
   ```
2. Default `probes = 10`. Make it configurable via Django settings: `VECTOR_SEARCH_PROBES = env.int("VECTOR_SEARCH_PROBES", default=10)`.
3. Add `VECTOR_SEARCH_PROBES` to `settings.py` and `.env.example`.
4. Add a comment in `search_service.py` explaining: higher probes = better recall, higher latency; recommended range 1–100.

**Tests:**
- `test_search_service_sets_probes` — mock `connection.cursor`, assert `SET ivfflat.probes` is called with correct value.

**Acceptance Criteria:**
- [ ] `ivfflat.probes` is set before every search query.
- [ ] Value is read from `settings.VECTOR_SEARCH_PROBES`.
- [ ] Env var `VECTOR_SEARCH_PROBES` is documented in `.env.example`.

---

### Task 6 — Integration Test & API Registry Update

**Files:**  
- `src/backend/documents/tests/test_search_integration.py` (new)  
- `docs/api-registry.md` (update implementation status)

**Goal:** End-to-end integration test against a real test DB with pgvector, and mark the endpoint as implemented in the registry.

**Steps:**

1. Create `test_search_integration.py` with `@pytest.mark.django_db`:
   - Seed one user, one document (`processing_status='completed'`), and 3 chunks with known real embedding vectors (you can use small fixed numpy arrays cast to list).
   - Call `POST /documents/{doc_id}/search/` with a query string.
   - Mock only `embed_query` (return one of the known vectors).
   - Assert response is 200, `total_results` >= 1, first result has highest `relevance_score`.

2. In `api-registry.md`, update the `POST /documents/{document_id}/search` entry:
   - Add `**Status:** ✅ Implemented`
   - Add `**Implementation Date:** <today>`
   - Add `**View:** DocumentSearchView`
   - Add implementation notes matching actual code behavior.

**Acceptance Criteria:**
- [ ] Integration test passes against test DB with pgvector extension.
- [ ] `api-registry.md` is updated with correct implementation status and notes.
- [ ] All unit tests from Tasks 1–5 pass (`pytest --tb=short`).
- [ ] No regression in existing test suite.

---

## Task Execution Order

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6
  ↑           ↑         ↑         ↑
embed_query  search   serial   view
(service)   (service) (layer)  (HTTP)
```

Tasks 1 and 2 have no dependencies on each other and can be done in parallel, but Task 4 depends on both being complete.

---

## File Change Summary

| File | Action |
|---|---|
| `src/backend/documents/embedding_service.py` | Extend: add `embed_query()` |
| `src/backend/documents/search_service.py` | Create new |
| `src/backend/documents/serializers.py` | Extend: add 3 serializers |
| `src/backend/documents/views.py` | Extend: add `DocumentSearchView` |
| `src/backend/documents/urls.py` | Extend: register search URL |
| `src/backend/config/settings.py` | Extend: add `VECTOR_SEARCH_PROBES` |
| `.env.example` | Extend: add `VECTOR_SEARCH_PROBES=10` |
| `src/backend/documents/tests/test_embedding_service.py` | Extend: add 2 tests |
| `src/backend/documents/tests/test_search_service.py` | Create new: 5 tests |
| `src/backend/documents/tests/test_serializers.py` | Extend: add 4 tests |
| `src/backend/documents/tests/test_views.py` | Extend: add 7 tests |
| `src/backend/documents/tests/test_search_integration.py` | Create new: 1 integration test |
| `docs/api-registry.md` | Update: mark endpoint implemented |

---

## Definition of Done (Epic E06)

- [ ] All 19+ tests pass with `pytest`.
- [ ] `POST /documents/{document_id}/search/` returns correct results against pgvector.
- [ ] Ownership and auth guards enforced on the endpoint.
- [ ] `422` returned for non-completed documents.
- [ ] `ivfflat.probes` is configurable via env var.
- [ ] `api-registry.md` updated.
- [ ] No raw SQL — all queries via Django ORM + pgvector Django extension.
- [ ] No breaking changes to existing endpoints.