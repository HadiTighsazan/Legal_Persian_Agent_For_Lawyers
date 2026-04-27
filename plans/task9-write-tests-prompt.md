# Task 9: Write Tests — `test_embedding.py`

## Objective

Create a new test file [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py) that consolidates **all embedding-related tests** currently scattered across three existing files:

| Existing File | Tests to Move |
|---|---|
| [`src/backend/documents/tests/test_embedding_service.py`](src/backend/documents/tests/test_embedding_service.py) | All embedding service unit tests |
| [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) | `DocumentEmbedViewTests`, `ChunkBatchEmbedViewTests`, `ChunkReEmbedViewTests`, `TaskStatusViewTests` |
| [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py) | `EmbedDocumentTaskTests` |

Additionally, **add one new test** that is currently missing: `test_batch_embed_handles_up_to_100_chunks` in the view tests section.

---

## Why Consolidate?

- **Single source of truth** for all embedding test logic.
- **Easier to find and run** embedding-related tests (`pytest documents/tests/test_embedding.py`).
- **Avoids duplication** — the existing tests in `test_embedding_service.py`, `test_views.py`, and `test_tasks.py` already cover embedding functionality; we are **moving** them, not rewriting them.

---

## TDD Workflow (RED → GREEN → REFACTOR)

For **each** test category below:

1. **RED** — Write the test method (it will fail initially because the test file doesn't exist yet, or the test references functions/classes that aren't imported).
2. **GREEN** — Write the minimum code to make the test pass (imports, helper functions, etc.).
3. **REFACTOR** — Clean up: ensure consistent naming, remove duplication, verify all tests pass.

---

## Test File Structure

The file should be organized into **3 test classes** (mirroring the 3 categories):

```python
"""
Tests for embedding functionality.

Consolidates all embedding-related tests from:
- documents.services.embedding_service (unit tests)
- documents.views (view tests)
- documents.tasks.embedding_tasks (Celery task tests)
"""

from __future__ import annotations

import uuid
from unittest.mock import ANY, MagicMock, patch

import openai
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from documents.models import Document, DocumentChunk
from documents.services.embedding_service import (
    SUB_BATCH_SIZE,
    batch_embed_chunks,
    batch_generate_embeddings,
    generate_embedding,
    generate_embeddings_for_document,
    reembed_chunk,
)
from tasks.models import ProcessingTask
from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_embedding(dim: int = 1536) -> list[float]:
    """Return a fake embedding vector of *dim* floats (all 0.1)."""
    return [0.1] * dim


def _mock_openai_response(
    texts: list[str],
    dim: int = 1536,
) -> MagicMock:
    """Build a mock OpenAI embeddings response for the given *texts*.

    Each text gets a unique embedding where the first element equals the
    index of the text in the list (to verify ordering).
    """
    mock_data = []
    for idx, _text in enumerate(texts):
        embedding = [float(idx + 1)] + [0.0] * (dim - 1)
        mock_item = MagicMock()
        mock_item.embedding = embedding
        mock_data.append(mock_item)

    mock_response = MagicMock()
    mock_response.data = mock_data
    return mock_response


def _auth_header(user: User) -> dict[str, str]:
    """Return an Authorization header dict for the given user."""
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    return {"HTTP_AUTHORIZATION": f"Bearer {refresh.access_token}"}


def _create_document(
    user: User,
    processing_status: str = "pending",
    **kwargs,
) -> Document:
    """Create a Document with sensible defaults for testing."""
    return Document.objects.create(
        user=user,
        title=kwargs.get("title", "Test Document"),
        filename=kwargs.get("filename", "test.pdf"),
        original_filename=kwargs.get("original_filename", "test.pdf"),
        file_path=kwargs.get("file_path", "/tmp/test.pdf"),
        file_size=kwargs.get("file_size", 1000),
        mime_type=kwargs.get("mime_type", "application/pdf"),
        processing_status=processing_status,
    )


def _mock_celery_request(task_func, celery_task_id: str = "test-celery-id"):
    """Context manager that patches the Celery task ``request`` property."""
    from unittest.mock import PropertyMock
    return patch(
        "celery.app.task.Task.request",
        new_callable=PropertyMock,
        return_value=MagicMock(id=celery_task_id),
    )
```

---

## Category 1: EmbeddingService Unit Tests

**Class name:** `EmbeddingServiceTests(TestCase)`

Move all tests from [`test_embedding_service.py`](src/backend/documents/tests/test_embedding_service.py) into this class. Keep the exact same test logic, but rename the test methods to match the Task 9 spec:

| Existing Name | New Name (Task 9 spec) |
|---|---|
| `test_generate_embedding_success` | `test_generate_embedding_returns_1536_floats` |
| `test_generate_embedding_empty_text` | `test_generate_embedding_empty_text_returns_none` |
| `test_generate_embedding_rate_limit_retry` | `test_generate_embedding_handles_rate_limit` |
| `test_batch_generate_embeddings_success` | `test_batch_generate_embeddings_returns_in_order` |
| `test_batch_generate_embeddings_mixed_failures` | `test_batch_generate_embeddings_handles_partial_failure` |
| `test_batch_embed_chunks_all_already_embedded` | `test_batch_embed_chunks_skips_existing_embeddings` |
| `test_reembed_chunk_success` | `test_reembed_chunk_overwrites_existing_embedding` |

**Keep these additional tests** (they are valuable but not in the spec):
- `test_generate_embedding_rate_limit_exhausted`
- `test_generate_embedding_api_error`
- `test_generate_embedding_authentication_error`
- `test_generate_embedding_connection_error`
- `test_batch_generate_embeddings_sub_batch_splitting`
- `test_batch_generate_embeddings_all_empty`
- `test_batch_generate_embeddings_rate_limit_retry`
- `test_generate_embeddings_for_document_success`
- `test_generate_embeddings_for_document_no_chunks`
- `test_generate_embeddings_for_document_all_already_embedded`
- `test_generate_embeddings_for_document_not_found`
- `test_generate_embeddings_for_document_partial_failures`
- `test_generate_embeddings_for_document_batch_progress`
- `test_batch_embed_chunks_mixed_state`
- `test_batch_embed_chunks_invalid_ids`
- `test_reembed_chunk_not_found`
- `test_reembed_chunk_failure`

**Sub-class organization** (keep the existing sub-classes from `test_embedding_service.py`):
- `class GenerateEmbeddingTests(TestCase)` — nested inside `EmbeddingServiceTests`
- `class BatchGenerateEmbeddingsTests(TestCase)`
- `class GenerateEmbeddingsForDocumentTests(TestCase)`
- `class BatchEmbedChunksTests(TestCase)`
- `class ReembedChunkTests(TestCase)`

---

## Category 2: View Tests

**Class name:** `EmbeddingViewTests(TestCase)`

Move these view test classes from [`test_views.py`](src/backend/documents/tests/test_views.py):

| Existing Class | New Name |
|---|---|
| `DocumentEmbedViewTests` | Keep as nested class |
| `ChunkBatchEmbedViewTests` | Keep as nested class |
| `ChunkReEmbedViewTests` | Keep as nested class |
| `TaskStatusViewTests` | Keep as nested class |

**Rename test methods** to match the Task 9 spec:

| Existing Name | New Name |
|---|---|
| `test_successful_embed_returns_202` | `test_document_embed_returns_202_with_task_id` |
| `test_nonexistent_document_returns_404` (in DocumentEmbedViewTests) | `test_document_embed_nonexistent_document_returns_404` |
| `test_other_users_document_returns_403` (in DocumentEmbedViewTests) | `test_document_embed_other_users_document_returns_403` |
| `test_unauthenticated_request_returns_401` (in DocumentEmbedViewTests) | `test_document_embed_unauthenticated_returns_401` |
| `test_invalid_chunk_ids_returns_400` | `test_batch_embed_validates_chunk_ids` |
| `test_nonexistent_chunk_returns_404` (in ChunkReEmbedViewTests) | `test_reembed_nonexistent_chunk_returns_404` |
| `test_other_users_chunk_returns_403` (in ChunkReEmbedViewTests) | `test_reembed_other_users_chunk_returns_403` |
| `test_returns_task_status` | `test_task_status_returns_correct_state` |
| `test_nonexistent_task_returns_404` (in TaskStatusViewTests) | `test_task_status_nonexistent_task_returns_404` |

### NEW Test: `test_batch_embed_handles_up_to_100_chunks`

This is the **only genuinely new test** in Task 9. Add it to the `ChunkBatchEmbedViewTests` nested class:

```python
def test_batch_embed_handles_up_to_100_chunks(self) -> None:
    """POST with 100 chunk IDs should be accepted (boundary test)."""
    chunk_ids = [uuid.uuid4() for _ in range(100)]

    with patch("documents.views.batch_embed_chunks") as mock_batch:
        mock_batch.return_value = {"processed": 100, "skipped": 0, "failed": 0}

        response = self.client.post(
            self.url,
            {"chunk_ids": [str(cid) for cid in chunk_ids]},
            **_auth_header(self.user),
            format="json",
        )

    self.assertEqual(response.status_code, status.HTTP_200_OK)
    data = response.json()
    self.assertEqual(data["processed"], 100)
```

**Note:** The serializer uses `ListField(child=UUIDField())` which accepts any number of UUIDs. There is no explicit 100-chunk limit in the serializer — this test verifies that 100 is handled correctly (boundary/acceptance test).

---

## Category 3: Celery Task Tests

**Class name:** `EmbeddingCeleryTaskTests(TestCase)`

Move the `EmbedDocumentTaskTests` class from [`test_tasks.py`](src/backend/documents/tests/test_tasks.py) into this class.

**Rename test methods** to match the Task 9 spec:

| Existing Name | New Name |
|---|---|
| `test_successful_embedding` | `test_embed_document_creates_embeddings_for_all_chunks` |
| `test_single_batch_progress` (or `test_progress_updates`) | `test_embed_document_updates_task_progress` |
| `test_successful_embedding` (the completion assertions) | `test_embed_document_marks_task_completed` |
| `test_task_marked_failed_on_error` | `test_embed_document_handles_openai_failure` |

**Keep these additional tests** (valuable but not in spec):
- `test_no_unembedded_chunks`
- `test_empty_document_no_chunks`
- `test_processing_task_not_found`
- `test_document_not_found`
- `test_partial_batch_failures`
- `test_sets_celery_task_id`
- `test_sets_started_at`
- `test_exactly_one_batch`
- `test_uneven_batch`

---

## Implementation Steps

### Step 1: RED — Create the test file

Create [`src/backend/documents/tests/test_embedding.py`](src/backend/documents/tests/test_embedding.py) with all the test classes and methods listed above. At this point, the file will contain only test code — no implementation changes needed since all the functions/classes already exist.

### Step 2: GREEN — Run tests and fix any import/name issues

```bash
docker-compose exec backend pytest documents/tests/test_embedding.py -v
```

Fix any import errors, missing helper functions, or naming mismatches until all tests pass.

### Step 3: REFACTOR — Clean up

1. Ensure all test method names match the Task 9 spec exactly.
2. Verify no duplicate tests exist between the old files and the new file.
3. Run the full test suite to ensure nothing is broken:
   ```bash
   docker-compose exec backend pytest -v
   ```
4. Update [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) with:
   - What was completed
   - Current state of the code
   - Next steps

### Step 4: (Optional) Remove old tests

After confirming the new file passes all tests, you may optionally remove the embedding-related tests from the old files to avoid duplication:

- From [`test_embedding_service.py`](src/backend/documents/tests/test_embedding_service.py) — remove all tests (the entire file can be deleted since it only contains embedding service tests).
- From [`test_views.py`](src/backend/documents/tests/test_views.py) — remove `DocumentEmbedViewTests`, `ChunkBatchEmbedViewTests`, `ChunkReEmbedViewTests`, `TaskStatusViewTests`.
- From [`test_tasks.py`](src/backend/documents/tests/test_tasks.py) — remove `EmbedDocumentTaskTests`.

**Important:** Only remove after confirming the new file passes all tests.

---

## Verification Checklist

After implementation, verify:

- [ ] `docker-compose exec backend pytest documents/tests/test_embedding.py -v` passes all tests
- [ ] `docker-compose exec backend pytest -v` passes (full suite)
- [ ] All test method names match the Task 9 spec
- [ ] The new test `test_batch_embed_handles_up_to_100_chunks` is present and passes
- [ ] No duplicate test names across old and new files
- [ ] `docs/active-task/wip-context.md` is updated

---

## Reference Files

| File | Purpose |
|---|---|
| [`src/backend/documents/services/embedding_service.py`](src/backend/documents/services/embedding_service.py) | The embedding service functions being tested |
| [`src/backend/documents/views.py`](src/backend/documents/views.py) | The view classes being tested (lines 426–603) |
| [`src/backend/documents/tasks/embedding_tasks.py`](src/backend/documents/tasks/embedding_tasks.py) | The Celery task being tested |
| [`src/backend/documents/models.py`](src/backend/documents/models.py) | Document and DocumentChunk models |
| [`src/backend/tasks/models.py`](src/backend/tasks/models.py) | ProcessingTask model |
| [`src/backend/documents/serializers.py`](src/backend/documents/serializers.py) | Serializers used by the views |
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | URL patterns for reverse() lookups |
| [`src/backend/documents/tests/test_embedding_service.py`](src/backend/documents/tests/test_embedding_service.py) | Existing embedding service tests (source to move from) |
| [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py) | Existing view tests (source to move from) |
| [`src/backend/documents/tests/test_tasks.py`](src/backend/documents/tests/test_tasks.py) | Existing task tests (source to move from) |
