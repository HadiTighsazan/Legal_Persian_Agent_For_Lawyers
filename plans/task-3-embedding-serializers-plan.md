# Task 3: Add Embedding Serializers

**Epic:** E-05 — Embedding & Vector Storage  
**File to modify:** [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py)  
**Dependencies:** Task 2 (Embedding Service) — ✅ Completed  
**Enables:** Task 4 (Embedding Views)

---

## Objective

Add 4 new serializers to [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) that will be used by the embedding-related API views (Task 4). These serializers follow the existing patterns in the file (DRF `Serializer` classes with `help_text` on every field).

---

## Serializers to Add

### 1. `DocumentEmbedResponseSerializer`

**Purpose:** Response serializer for `POST /documents/{id}/embed` — returns task metadata immediately (202 Accepted).

```python
class DocumentEmbedResponseSerializer(serializers.Serializer):
    """Response serializer for POST /documents/{id}/embed.

    Returns task metadata immediately after triggering the embedding
    Celery task for all un-embedded chunks of a document.
    """

    task_id = serializers.UUIDField(
        help_text="UUID of the Celery task processing the embedding.",
    )
    task_type = serializers.CharField(
        default="embed",
        help_text="Type of processing task (always 'embed').",
    )
    status = serializers.CharField(
        default="pending",
        help_text="Initial status of the embedding task.",
    )
    document_id = serializers.UUIDField(
        help_text="UUID of the document being embedded.",
    )
    total_chunks = serializers.IntegerField(
        help_text="Number of chunks queued for embedding.",
    )
```

### 2. `ChunkBatchEmbedRequestSerializer`

**Purpose:** Request serializer for `POST /chunks/batch-embed` — validates the incoming list of chunk UUIDs.

```python
class ChunkBatchEmbedRequestSerializer(serializers.Serializer):
    """Validate the incoming chunk_ids list for batch embedding.

    Accepts a list of UUIDs identifying which chunks to embed.
    """

    chunk_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of chunk UUIDs to embed.",
    )
```

### 3. `ChunkBatchEmbedResponseSerializer`

**Purpose:** Response serializer for `POST /chunks/batch-embed` — returns counts of processed/skipped/failed chunks.

```python
class ChunkBatchEmbedResponseSerializer(serializers.Serializer):
    """Response serializer for POST /chunks/batch-embed.

    Provides a summary of the batch embedding operation.
    """

    processed = serializers.IntegerField(
        help_text="Number of chunks successfully embedded.",
    )
    skipped = serializers.IntegerField(
        help_text="Number of chunks skipped (already had embeddings).",
    )
    failed = serializers.IntegerField(
        help_text="Number of chunks that failed to embed.",
    )
```

### 4. `ChunkReEmbedResponseSerializer`

**Purpose:** Response serializer for `POST /chunks/{chunk_id}/re-embed` — returns the chunk ID and whether the embedding was updated.

```python
class ChunkReEmbedResponseSerializer(serializers.Serializer):
    """Response serializer for POST /chunks/{chunk_id}/re-embed.

    Indicates whether the chunk's embedding was successfully regenerated.
    """

    chunk_id = serializers.UUIDField(
        help_text="UUID of the chunk that was re-embedded.",
    )
    embedding_updated = serializers.BooleanField(
        help_text="Whether the embedding was successfully updated.",
    )
```

---

## Implementation Details

### File to Modify

[`src/backend/documents/serializers.py`](src/backend/documents/serializers.py)

### Where to Insert

Add the 4 new serializer classes **after** the existing [`DocumentChunkSerializer`](src/backend/documents/serializers.py:99) class (line 124), maintaining the existing docstring style and field-level `help_text` convention.

### Style Guidelines (from existing code)

- Every field **must** have a `help_text` parameter (enforced by existing tests like [`test_help_text_on_all_fields`](src/backend/documents/tests/test_serializers.py:131))
- Docstrings follow the existing pattern: class-level docstring describing the serializer's purpose
- Use `serializers.Serializer` (not `ModelSerializer`) since these are not tied to a single model
- Use `default` parameter for fields like `task_type` and `status` that have fixed initial values

### No Model Changes Required

These serializers are pure data validators — they don't map to models directly. The `DocumentEmbedResponseSerializer` receives data constructed in the view, not from a model instance.

---

## Test Plan

Add tests in [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py) following the existing patterns:

### `DocumentEmbedResponseSerializerTests`

| Test | Description |
|------|-------------|
| `test_valid_data_passes` | All required fields present passes validation |
| `test_serializes_output` | Output dict has correct types (UUID to str, etc.) |
| `test_default_task_type` | `task_type` defaults to `"embed"` |
| `test_default_status` | `status` defaults to `"pending"` |
| `test_missing_task_id_returns_error` | Omitting `task_id` fails validation |
| `test_missing_document_id_returns_error` | Omitting `document_id` fails validation |
| `test_missing_total_chunks_returns_error` | Omitting `total_chunks` fails validation |
| `test_help_text_on_all_fields` | Every field has descriptive `help_text` |

### `ChunkBatchEmbedRequestSerializerTests`

| Test | Description |
|------|-------------|
| `test_valid_chunk_ids_passes` | List of valid UUIDs passes |
| `test_empty_list_passes` | Empty list is valid (view handles it) |
| `test_invalid_uuid_fails` | Non-UUID string in list fails |
| `test_missing_chunk_ids_returns_error` | Omitting `chunk_ids` fails |
| `test_help_text_on_all_fields` | Every field has descriptive `help_text` |

### `ChunkBatchEmbedResponseSerializerTests`

| Test | Description |
|------|-------------|
| `test_valid_data_passes` | All fields present passes |
| `test_serializes_output` | Output has correct integer values |
| `test_zero_counts_are_valid` | All zeros is valid |
| `test_missing_processed_returns_error` | Omitting `processed` fails |
| `test_missing_skipped_returns_error` | Omitting `skipped` fails |
| `test_missing_failed_returns_error` | Omitting `failed` fails |
| `test_help_text_on_all_fields` | Every field has descriptive `help_text` |

### `ChunkReEmbedResponseSerializerTests`

| Test | Description |
|------|-------------|
| `test_valid_data_passes` | All fields present passes |
| `test_serializes_output` | Output has correct types |
| `test_embedding_updated_true` | Boolean `True` is valid |
| `test_embedding_updated_false` | Boolean `False` is valid |
| `test_missing_chunk_id_returns_error` | Omitting `chunk_id` fails |
| `test_missing_embedding_updated_returns_error` | Omitting `embedding_updated` fails |
| `test_help_text_on_all_fields` | Every field has descriptive `help_text` |

---

## Files to Modify

| File | Action |
|------|--------|
| [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) | Add 4 new serializer classes |
| [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py) | Add 4 new test classes (~28 test methods) |
| [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Update after completion |

---

## Execution Steps (for Code Mode)

1. **Read** [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) to confirm current content
2. **Add** the 4 new serializer classes after `DocumentChunkSerializer` (line 124)
3. **Read** [`src/backend/documents/tests/test_serializers.py`](src/backend/documents/tests/test_serializers.py) to confirm current content
4. **Add** the 4 new test classes at the end of the test file
5. **Run tests** to verify:
   ```
   docker-compose exec backend python -m pytest documents/tests/test_serializers.py -v
   ```
6. **Update** [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) with completion status
