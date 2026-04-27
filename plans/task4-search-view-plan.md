# Task 4 — Search View + URL Registration

## Overview

Add a `DocumentSearchView` that performs semantic search within a document's chunks. The endpoint accepts a POST request with a query string, calls `embed_query()` to vectorize it, then `search_chunks()` to find relevant chunks, and returns the results.

## Files to Modify

| File | Change |
|---|---|
| [`src/backend/documents/views.py`](src/backend/documents/views.py) | Add `DocumentSearchView` class |
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | Register the search URL pattern |
| [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) | Add `DocumentSearchViewTests` class with 7 test methods |

## Prerequisites (already exist)

- [`SearchRequestSerializer`](src/backend/documents/serializers.py:195) — validates `query` (required, max 1000 chars), `top_k` (optional, default 10, 1–50), `min_score` (optional, default 0.0, 0.0–1.0)
- [`SearchResponseSerializer`](src/backend/documents/serializers.py:260) — serializes `results`, `query`, `top_k`, `min_score`, `total_results`
- [`SearchResultSerializer`](src/backend/documents/serializers.py:226) — serializes individual chunk results
- [`embed_query()`](src/backend/documents/services/embedding_service.py:151) — converts query text to 768-dim vector, raises `EmbeddingError` on failure
- [`search_chunks()`](src/backend/documents/services/search_service.py:28) — performs pgvector cosine similarity search
- [`Document` model](src/backend/documents/models.py:13) — has `id`, `user` (FK), `processing_status` field
- Root URL config at [`src/backend/config/urls.py`](src/backend/config/urls.py:56) already includes `path('documents/', include('documents.urls'))`

## Step 1 — Add `DocumentSearchView` to `views.py`

### Location

Add after the existing views (e.g., after `DocumentChunksListView` or at the end of the file, before the file ends).

### Imports to Add

```python
from documents.serializers import (
    # ... existing imports ...
    SearchRequestSerializer,    # ADD
    SearchResponseSerializer,   # ADD
)
from documents.services.embedding_service import (
    # ... existing imports ...
    embed_query,                # ADD (if not already imported)
    EmbeddingError,             # ADD
)
from documents.services.search_service import (
    search_chunks,              # ADD
)
```

### View Implementation

```python
class DocumentSearchView(APIView):
    """Semantic search within a document's chunks.

    Endpoint: POST /documents/<uuid:document_id>/search/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, document_id: str) -> Response:
        # 1. Fetch document (404 if not found)
        try:
            document = Document.objects.get(id=document_id)
        except Document.DoesNotExist:
            return Response(
                {"error": "not_found", "message": "Document not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2. Ownership check (403 if mismatch)
        if document.user != request.user:
            return Response(
                {
                    "error": "permission_denied",
                    "message": "You do not have permission to search this document.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 3. Processing status check (422 if not 'completed')
        if document.processing_status != "completed":
            return Response(
                {
                    "error": "document_not_ready",
                    "message": "Document processing is not complete yet.",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # 4. Validate request body with SearchRequestSerializer (400 on failure)
        serializer = SearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query: str = serializer.validated_data["query"]
        top_k: int = serializer.validated_data["top_k"]
        min_score: float = serializer.validated_data["min_score"]

        # 5. Call embed_query() to get query vector
        try:
            query_vector = embed_query(query)
        except EmbeddingError:
            logger.exception("Embedding failed for query on document %s", document_id)
            return Response(
                {"error": "embedding_failed", "message": "Failed to generate query embedding."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 6. Call search_chunks() to get results
        results = search_chunks(
            document_id=str(document.id),
            query_vector=query_vector,
            top_k=top_k,
            min_score=min_score,
        )

        # 7. Serialize response with SearchResponseSerializer
        response_data = {
            "results": results,
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "total_results": len(results),
        }
        response_serializer = SearchResponseSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        # 8. Return 200 OK
        return Response(response_serializer.validated_data, status=status.HTTP_200_OK)
```

### Error Handling Matrix

| Condition | HTTP Status | Error Code |
|---|---|---|
| Document not found | 404 | `not_found` |
| Wrong user | 403 | `permission_denied` |
| Document not completed | 422 | `document_not_ready` |
| Invalid request body | 400 | DRF validation errors |
| Embedding failure | 500 | `embedding_failed` |

## Step 2 — Register URL in `urls.py`

Add the import and URL pattern.

### Import to Add

```python
from documents.views import (
    # ... existing imports ...
    DocumentSearchView,   # ADD
)
```

### URL Pattern to Add

Insert inside `urlpatterns` list (order doesn't matter, but logically place it near other document-specific routes):

```python
path(
    "<uuid:document_id>/search/",
    DocumentSearchView.as_view(),
    name="document-search",
),
```

## Step 3 — Add Tests in `test_views.py`

### New Test Class

```python
class DocumentSearchViewTests(TestCase):
    """Tests for the :class:`DocumentSearchView` endpoint."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="search-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-search@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user, processing_status="completed")
        self.url = reverse(
            "documents:document-search",
            kwargs={"document_id": self.document.id},
        )
```

### Test Methods

| # | Method | What It Verifies |
|---|---|---|
| 1 | `test_search_requires_auth` | POST without auth → 401 |
| 2 | `test_search_document_not_found` | POST to non-existent UUID → 404 with `not_found` |
| 3 | `test_search_document_wrong_user` | POST as other user → 403 with `permission_denied` |
| 4 | `test_search_document_not_completed` | Document with `processing_status='processing'` → 422 with `document_not_ready` |
| 5 | `test_search_valid_request` | Mock `embed_query` + `search_chunks`, assert 200 with correct response shape |
| 6 | `test_search_invalid_top_k` | `top_k=0` → 400 (DRF validation) |
| 7 | `test_search_empty_results` | Mock returns empty list → 200 with `results=[]` and `total_results=0` |

### Detailed Test Implementations

#### 1. `test_search_requires_auth`

```python
def test_search_requires_auth(self) -> None:
    """POST without auth should return 401."""
    response = self.client.post(self.url, {"query": "test"}, format="json")
    self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
```

#### 2. `test_search_document_not_found`

```python
def test_search_document_not_found(self) -> None:
    """POST to a non-existent document ID should return 404."""
    url = reverse(
        "documents:document-search",
        kwargs={"document_id": uuid.uuid4()},
    )
    response = self.client.post(
        url, {"query": "test"}, format="json", **_auth_header(self.user)
    )
    self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    self.assertEqual(response.data["error"], "not_found")
```

#### 3. `test_search_document_wrong_user`

```python
def test_search_document_wrong_user(self) -> None:
    """POST to another user's document should return 403."""
    response = self.client.post(
        self.url, {"query": "test"}, format="json", **_auth_header(self.other_user)
    )
    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    self.assertEqual(response.data["error"], "permission_denied")
```

#### 4. `test_search_document_not_completed`

```python
def test_search_document_not_completed(self) -> None:
    """POST for a document with processing_status != 'completed' should return 422."""
    doc = _create_document(self.user, processing_status="processing")
    url = reverse("documents:document-search", kwargs={"document_id": doc.id})
    response = self.client.post(
        url, {"query": "test"}, format="json", **_auth_header(self.user)
    )
    self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    self.assertEqual(response.data["error"], "document_not_ready")
```

#### 5. `test_search_valid_request`

```python
@patch("documents.views.embed_query")
@patch("documents.views.search_chunks")
def test_search_valid_request(
    self,
    mock_search_chunks: MagicMock,
    mock_embed_query: MagicMock,
) -> None:
    """Valid request should return 200 with correctly shaped response."""
    mock_embed_query.return_value = [0.1] * 768
    mock_search_chunks.return_value = [
        {
            "chunk_id": str(uuid.uuid4()),
            "chunk_index": 0,
            "page_start": 1,
            "page_end": 1,
            "content": "Relevant chunk content",
            "relevance_score": 0.95,
            "token_count": 50,
            "metadata": {"source": "test"},
        },
    ]

    response = self.client.post(
        self.url,
        {"query": "test query", "top_k": 5, "min_score": 0.5},
        format="json",
        **_auth_header(self.user),
    )
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    data = response.json()
    self.assertIn("results", data)
    self.assertIn("query", data)
    self.assertIn("top_k", data)
    self.assertIn("min_score", data)
    self.assertIn("total_results", data)
    self.assertEqual(data["query"], "test query")
    self.assertEqual(data["top_k"], 5)
    self.assertEqual(data["min_score"], 0.5)
    self.assertEqual(data["total_results"], 1)

    result = data["results"][0]
    self.assertIn("chunk_id", result)
    self.assertIn("chunk_index", result)
    self.assertIn("page_start", result)
    self.assertIn("page_end", result)
    self.assertIn("content", result)
    self.assertIn("relevance_score", result)
    self.assertIn("token_count", result)
    self.assertIn("metadata", result)

    mock_embed_query.assert_called_once_with("test query")
    mock_search_chunks.assert_called_once_with(
        document_id=str(self.document.id),
        query_vector=[0.1] * 768,
        top_k=5,
        min_score=0.5,
    )
```

#### 6. `test_search_invalid_top_k`

```python
def test_search_invalid_top_k(self) -> None:
    """top_k=0 should return 400 (DRF validation)."""
    response = self.client.post(
        self.url,
        {"query": "test", "top_k": 0},
        format="json",
        **_auth_header(self.user),
    )
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
```

#### 7. `test_search_empty_results`

```python
@patch("documents.views.embed_query")
@patch("documents.views.search_chunks")
def test_search_empty_results(
    self,
    mock_search_chunks: MagicMock,
    mock_embed_query: MagicMock,
) -> None:
    """Valid request with no matches should return 200 with empty results."""
    mock_embed_query.return_value = [0.2] * 768
    mock_search_chunks.return_value = []

    response = self.client.post(
        self.url,
        {"query": "nothing"},
        format="json",
        **_auth_header(self.user),
    )
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    data = response.json()
    self.assertEqual(data["results"], [])
    self.assertEqual(data["total_results"], 0)
    self.assertEqual(data["query"], "nothing")
```

## Execution Order

1. **RED** — Write all 7 test methods first (they will fail)
2. **GREEN** — Implement `DocumentSearchView` in `views.py`
3. **GREEN** — Register URL in `urls.py`
4. **REFACTOR** — Run tests, verify all pass, clean up

## Verification

```bash
docker-compose exec backend pytest documents/tests/test_views.py::DocumentSearchViewTests -v
```

Expected output: 7 passed, 0 failed.

## Post-Implementation

Update [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) with:
- What was completed (Search view, URL, tests)
- Current state (all tests passing)
- Next step (next task in the epic)

Update [`docs/references/api-registry.md`](docs/references/api-registry.md) with the new endpoint:
- `POST /documents/<uuid:document_id>/search/` — `DocumentSearchView`
