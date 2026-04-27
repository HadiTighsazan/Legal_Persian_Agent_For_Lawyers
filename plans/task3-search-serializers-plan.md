# Task 3 — Search Request/Response Serializers — Implementation Plan

## Overview

Add 3 new serializers (`SearchRequestSerializer`, `SearchResultSerializer`, `SearchResponseSerializer`) to [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) and 4 test methods to [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py).

These serializers will be used by the upcoming `DocumentSearchView` (Task 4) to validate incoming search requests and format search results.

---

## Files to Modify

| File | Action |
|---|---|
| [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) | Add 3 new serializer classes at the end of the file |
| [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py) | Add 4 test methods in a new `SearchRequestSerializerTests` class |

---

## Step 1 — Add Serializers to `serializers.py`

### 1.1 `SearchRequestSerializer`

```python
class SearchRequestSerializer(serializers.Serializer):
    """Validate the incoming search request body.

    Fields:
        query (str): Required search query text, max 1000 characters.
        top_k (int): Optional max results (default 10, range 1–50).
        min_score (float): Optional minimum relevance threshold
            (default 0.0, range 0.0–1.0).
    """

    query = serializers.CharField(
        required=True,
        max_length=1000,
        help_text="Natural language search query.",
    )
    top_k = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
        help_text="Maximum number of search results to return (1–50).",
    )
    min_score = serializers.FloatField(
        required=False,
        default=0.0,
        min_value=0.0,
        max_value=1.0,
        help_text="Minimum relevance score threshold (0.0–1.0).",
    )
```

**Key constraints:**
- `query` is required, max 1000 chars
- `top_k` is optional, defaults to 10, clamped to [1, 50]
- `min_score` is optional, defaults to 0.0, clamped to [0.0, 1.0]

### 1.2 `SearchResultSerializer`

```python
class SearchResultSerializer(serializers.Serializer):
    """Serialize a single search result chunk.

    Mirrors the dict returned by
    :func:`~documents.services.search_service.search_chunks`.
    """

    chunk_id = serializers.UUIDField(
        help_text="Unique identifier of the matching chunk.",
    )
    chunk_index = serializers.IntegerField(
        help_text="Sequential index of the chunk within the document.",
    )
    page_start = serializers.IntegerField(
        help_text="Starting page number for this chunk.",
    )
    page_end = serializers.IntegerField(
        help_text="Ending page number for this chunk.",
    )
    content = serializers.CharField(
        help_text="Text content of the chunk.",
    )
    relevance_score = serializers.FloatField(
        help_text="Cosine similarity score (0.0–1.0, higher is more relevant).",
    )
    token_count = serializers.IntegerField(
        allow_null=True,
        help_text="Number of tokens in the chunk, or null if not computed.",
    )
    metadata = serializers.JSONField(
        help_text="Additional metadata associated with the chunk.",
    )
```

**Key constraints:**
- `chunk_id` is a UUIDField (DRF serializes UUIDs to strings)
- `token_count` allows null (matches `DocumentChunkSerializer` pattern)
- `metadata` is a JSONField

### 1.3 `SearchResponseSerializer`

```python
class SearchResponseSerializer(serializers.Serializer):
    """Serialize the full search response.

    Wraps a list of :class:`SearchResultSerializer` instances along with
    the original request parameters and result count.
    """

    results = SearchResultSerializer(
        many=True,
        help_text="List of matching chunks ordered by relevance.",
    )
    query = serializers.CharField(
        help_text="The original search query.",
    )
    top_k = serializers.IntegerField(
        help_text="Maximum number of results requested.",
    )
    min_score = serializers.FloatField(
        help_text="Minimum relevance score threshold used.",
    )
    total_results = serializers.IntegerField(
        help_text="Total number of results returned.",
    )
```

**Key constraints:**
- `results` uses `SearchResultSerializer(many=True)` — nested serialization
- All fields are required (response serializers validate output shape)

### Placement

Add these 3 classes at the **end** of [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py), after the existing `ChunkReEmbedResponseSerializer` class (line 193).

---

## Step 2 — Add Tests to `test_serializers.py`

### 2.1 New Test Class: `SearchRequestSerializerTests`

Add a new test class at the **end** of [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py), after the existing `ChunkReEmbedResponseSerializerTests` class (line 587).

### 2.2 Import the new serializers

Update the import block at line 24–33 to also import:
```python
SearchRequestSerializer,
SearchResultSerializer,
SearchResponseSerializer,
```

### 2.3 Test Methods

| # | Test Method | What It Verifies | Implementation |
|---|---|---|---|
| 1 | `test_search_request_defaults` | Omitting `top_k` and `min_score` gives defaults 10 and 0.0 | Create serializer with only `query`, call `is_valid()`, assert `validated_data["top_k"] == 10` and `validated_data["min_score"] == 0.0` |
| 2 | `test_search_request_top_k_max_validation` | `top_k=51` fails validation | Create serializer with `query` + `top_k=51`, call `is_valid()`, assert `False`, assert `"top_k"` in `errors` |
| 3 | `test_search_request_min_score_range` | `min_score=-0.1` and `min_score=1.1` fail validation | Use `subTest` to test both values; each should fail with `"min_score"` in `errors` |
| 4 | `test_search_request_empty_query` | Empty string fails validation | Create serializer with `query=""`, call `is_valid()`, assert `False`, assert `"query"` in `errors` |

### 2.4 Test Class Structure

```python
# ---------------------------------------------------------------------------
# Tests — SearchRequestSerializer
# ---------------------------------------------------------------------------


class SearchRequestSerializerTests(TestCase):
    """Validate the search request serializer for POST /documents/{id}/search."""

    def test_search_request_defaults(self) -> None:
        """Omitting ``top_k`` and ``min_score`` gives defaults 10 and 0.0."""
        serializer = SearchRequestSerializer(data={"query": "test query"})
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["top_k"], 10)
        self.assertEqual(serializer.validated_data["min_score"], 0.0)

    def test_search_request_top_k_max_validation(self) -> None:
        """``top_k=51`` fails validation (max is 50)."""
        serializer = SearchRequestSerializer(
            data={"query": "test", "top_k": 51}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("top_k", serializer.errors)

    def test_search_request_min_score_range(self) -> None:
        """``min_score`` values outside [0.0, 1.0] fail validation."""
        for score in (-0.1, 1.1):
            with self.subTest(score=score):
                serializer = SearchRequestSerializer(
                    data={"query": "test", "min_score": score}
                )
                self.assertFalse(serializer.is_valid())
                self.assertIn("min_score", serializer.errors)

    def test_search_request_empty_query(self) -> None:
        """Empty string fails validation (``required=True``, ``min_length`` implied)."""
        serializer = SearchRequestSerializer(data={"query": ""})
        self.assertFalse(serializer.is_valid())
        self.assertIn("query", serializer.errors)
```

---

## Step 3 — Verify Tests Pass

Run the tests inside the Docker container:

```bash
docker-compose exec backend pytest documents/tests/test_serializers.py -v --tb=short
```

Expected output: all existing tests pass + 4 new tests pass (no regressions).

---

## Dependencies

- **None.** Task 3 has no dependency on Task 1 (embed_query) or Task 2 (search_chunks). It can be implemented independently.
- Task 4 (Search View) depends on these serializers being available.

---

## Acceptance Criteria

- [ ] `SearchRequestSerializer` validates `query` (required, max 1000), `top_k` (optional, default 10, range 1–50), `min_score` (optional, default 0.0, range 0.0–1.0)
- [ ] `SearchResultSerializer` accepts all 8 fields with correct types (UUIDField, IntegerField, CharField, FloatField, JSONField)
- [ ] `SearchResponseSerializer` nests `SearchResultSerializer(many=True)` and includes `query`, `top_k`, `min_score`, `total_results`
- [ ] All 4 test methods pass
- [ ] No regressions in existing serializer tests
- [ ] All serializers have `help_text` on every field (matching project convention)
