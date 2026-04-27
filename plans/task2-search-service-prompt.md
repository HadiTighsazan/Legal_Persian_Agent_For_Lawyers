# Task 2 — Search Service: `search_chunks()` Implementation Prompt

## Overview

Implement a pure service function `search_chunks()` that performs cosine similarity search against `DocumentChunk` embeddings using pgvector's `CosineDistance` annotation. This is a **standalone service function** with no HTTP dependency — it takes a `document_id`, `query_vector`, `top_k`, and `min_score`, and returns a `list[dict]` of ranked results.

**Epic:** E06 — Semantic Search & Retrieval  
**PRD:** [`docs/active-task/current-prd.md`](docs/active-task/current-prd.md)  
**Implementation Plan:** [`docs/active-task/Implementation-Plan-E06.md`](docs/active-task/Implementation-Plan-E06.md)  
**Dependencies:** None (independent of Task 1)

---

## Files to Create

### 1. [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) — **Create new file**

### 2. [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) — **Create new file** with 5 tests

---

## Implementation Details

### Function Signature

```python
from pgvector.django import CosineDistance

def search_chunks(
    document_id: str,
    query_vector: list[float],
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict]:
    """Search document chunks by cosine similarity to a query vector.

    Args:
        document_id: UUID of the document to search within.
        query_vector: 768-dim embedding vector for the query.
        top_k: Maximum number of results to return (default 10).
        min_score: Minimum relevance score threshold (default 0.0).

    Returns:
        A list of dicts ordered by relevance_score descending.
        Each dict has keys: chunk_id, chunk_index, page_start, page_end,
        content, relevance_score, token_count, metadata.
    """
```

### Logic Steps (in order)

1. **Import** `CosineDistance` from `pgvector.django`
2. **Import** `DocumentChunk` from `documents.models`
3. **Build queryset:**
   - `DocumentChunk.objects.filter(document_id=document_id, embedding__isnull=False)`
4. **Annotate** with cosine distance:
   - `.annotate(distance=CosineDistance("embedding", query_vector))`
5. **Compute relevance score** using expression:
   - Use Django's `F` expressions and `Value` to compute `1 - distance` as `relevance_score`
   - You can use `.annotate(relevance_score=Value(1.0) - F("distance"))` — but note that `CosineDistance` returns an annotation you can reference via `F("distance")`
6. **Filter** by `relevance_score >= min_score`:
   - Since `relevance_score` is an annotation, you can filter on it directly
7. **Order** by `distance ASC` (lowest cosine distance = highest similarity)
8. **Limit** to `top_k` results using slicing `[:top_k]`
9. **Return** `list[dict]` with the specified keys

### Important Notes

- The function must **not** accept an HTTP `request` object — it's a pure service function
- Use **Django ORM** exclusively — no raw SQL
- The `CosineDistance` function from `pgvector.django` returns a float annotation representing cosine distance (0 = identical, 1 = orthogonal, 2 = opposite)
- `relevance_score = 1 - distance` converts cosine distance to cosine similarity
- Results should be ordered by `distance ASC` (ascending), meaning most similar first
- The `chunk_id` in the output dict should be `str(chunk.id)` (stringified UUID)
- The `metadata` field is already a dict from the JSONField

### Return Dict Keys

| Key | Type | Source |
|-----|------|--------|
| `chunk_id` | `str` | `str(chunk.id)` |
| `chunk_index` | `int` | `chunk.chunk_index` |
| `page_start` | `int` | `chunk.page_start` |
| `page_end` | `int` | `chunk.page_end` |
| `content` | `str` | `chunk.content` |
| `relevance_score` | `float` | Computed: `1 - distance` |
| `token_count` | `int` or `None` | `chunk.token_count` |
| `metadata` | `dict` | `chunk.metadata` |

---

## Tests to Add (in [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py))

### Test Setup

Use `django.test.TestCase`. Create a user and a document in `setUp`. Provide a helper to create chunks with known embeddings.

**Key insight for test embeddings:** Since we're using `CosineDistance`, we need embeddings that produce predictable distances. Use these patterns:

- **Identity vector:** `[1.0] + [0.0] * 767` — this is the "query" vector
- **Close vector:** `[0.9] + [0.0] * 767` — cosine distance ≈ 0.1, relevance ≈ 0.9
- **Medium vector:** `[0.5] + [0.0] * 767` — cosine distance ≈ 0.5, relevance ≈ 0.5
- **Far vector:** `[-0.5] + [0.0] * 767` — cosine distance ≈ 1.5, relevance ≈ -0.5
- **Null embedding:** `None` — should be excluded

**Important:** pgvector's `CosineDistance` computes `1 - cosine_similarity`. For vectors `[1,0,0...]` and `[0.9,0,0...]`, the cosine similarity is `0.9/1.0 = 0.9`, so distance = `0.1`. For `[1,0,0...]` and `[0.5,0,0...]`, similarity = `0.5`, distance = `0.5`. For `[1,0,0...]` and `[-0.5,0,0...]`, similarity = `-0.5`, distance = `1.5`.

### Test Cases

| # | Test Method | What It Verifies |
|---|-------------|------------------|
| 1 | `test_search_chunks_returns_top_k` | Seed 5 chunks with known embeddings, set `top_k=3`, assert only 3 results returned |
| 2 | `test_search_chunks_filters_by_min_score` | Create chunks with varying relevance scores, set `min_score=0.7`, assert only chunks with score >= 0.7 returned |
| 3 | `test_search_chunks_excludes_unembedded_chunks` | Create one chunk with embedding and one with `embedding=None`, assert only the embedded chunk appears |
| 4 | `test_search_chunks_orders_by_relevance` | Create chunks with known distances, assert results are ordered by `relevance_score` descending (highest first) |
| 5 | `test_search_chunks_empty_result` | Query with a vector that doesn't match any chunks (or query a document with no chunks), assert returns `[]` |

### Test Implementation Notes

- Use `from django.test import TestCase`
- Use `from documents.models import Document, DocumentChunk`
- Use `from documents.services.search_service import search_chunks`
- Create a `User` using `User.objects.create_user(email="...", password="testpass123")`
- Create a `Document` using `Document.objects.create(...)` with proper defaults
- Create `DocumentChunk` instances with explicit `embedding` values (list of floats)
- The query vector should be `[1.0] + [0.0] * 767` for predictable results
- For `test_search_chunks_empty_result`, use a document with no chunks at all

---

## TDD Flow

### RED Phase
1. Create the test file [`src/backend/documents/tests/test_search_service.py`](src/backend/documents/tests/test_search_service.py) with all 5 test methods
2. Run `docker-compose exec backend pytest documents/tests/test_search_service.py --tb=short`
3. Confirm tests fail with `ImportError` (the service module doesn't exist yet)

### GREEN Phase
1. Create [`src/backend/documents/services/search_service.py`](src/backend/documents/services/search_service.py) with the `search_chunks()` function
2. Run tests again — all 5 should pass

### REFACTOR Phase
1. Review for any code quality issues
2. Ensure docstrings are clear
3. Verify no duplication with existing code

---

## Verification

After implementation, run the full test suite to ensure no regressions:

```bash
docker-compose exec backend pytest --tb=short
```

Expected: All existing tests pass + 5 new tests pass.

---

## Acceptance Criteria

- [ ] `search_chunks()` is a pure function with no HTTP `request` object
- [ ] Uses pgvector `CosineDistance` annotation (not raw SQL)
- [ ] NULL embeddings are excluded from results
- [ ] Results are ordered by `relevance_score` descending (highest first)
- [ ] `top_k` limits the number of results
- [ ] `min_score` filters out low-relevance chunks
- [ ] Empty results return `[]` (not `None`)
- [ ] All 5 tests pass
- [ ] No regressions in existing test suite
