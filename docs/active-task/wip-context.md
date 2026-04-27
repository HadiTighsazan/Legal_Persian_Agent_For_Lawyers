# WIP Context — Task 9 of Epic E-05 (Consolidated Embedding Tests)

## Status: ✅ COMPLETED

## What Was Completed

### New File Created

1. **`src/backend/documents/tests/test_embedding.py`** (NEW FILE — 1318 lines) — Consolidated test file containing ALL embedding-related tests moved from three source files into one single source of truth.

### Test Structure (11 top-level TestCase classes, 57 tests total)

#### Embedding Service Unit Tests (24 tests)
| Class | Tests | Description |
|-------|-------|-------------|
| `GenerateEmbeddingTests` | 7 | Tests for `generate_embedding()` — returns 1536-dim vector, empty text returns None, rate limit retry with backoff, rate limit exhausted, API error, auth error, connection error |
| `BatchGenerateEmbeddingsTests` | 5 | Tests for `batch_generate_embeddings()` — returns in order, partial failure (None at correct positions), sub-batch splitting (120 texts → 3 batches of 50/50/20), all empty texts, rate limit retry |
| `GenerateEmbeddingsForDocumentTests` | 6 | Tests for `generate_embeddings_for_document()` — success with 3 chunks, no chunks, all already embedded, document not found, partial failures, batch progress tracking |
| `BatchEmbedChunksTests` | 3 | Tests for `batch_embed_chunks()` — mixed state (2 already embedded, 2 succeed, 1 fails), invalid IDs, skips existing embeddings |
| `ReembedChunkTests` | 3 | Tests for `reembed_chunk()` — overwrites existing embedding, chunk not found, failure returns embedding_updated=False |

#### Embedding View Tests (19 tests)
| Class | Tests | Description |
|-------|-------|-------------|
| `DocumentEmbedViewTests` | 6 | Tests for `DocumentEmbedView` — nonexistent doc (404), other user's doc (403), unauthenticated (401), returns 202 with task_id, creates ProcessingTask, counts unembedded chunks, skips already embedded chunks |
| `ChunkBatchEmbedViewTests` | 4 | Tests for `ChunkBatchEmbedView` — unauthenticated (401), validates chunk IDs (400), successful batch returns 200, **NEW: handles up to 100 chunks** (boundary test) |
| `ChunkReEmbedViewTests` | 4 | Tests for `ChunkReEmbedView` — nonexistent chunk (404), other user's chunk (403), unauthenticated (401), successful re-embed returns 200 |
| `TaskStatusViewTests` | 5 | Tests for `TaskStatusView` — nonexistent task (404), other user's task (403), unauthenticated (401), returns correct state, returns all expected fields |

#### Embedding Celery Task Tests (13 tests)
| Class | Tests | Description |
|-------|-------|-------------|
| `EmbeddingCeleryTaskTests` | 13 | Tests for `embed_document` Celery task — creates embeddings for all chunks, no unembedded chunks, empty document, processing task not found, document not found, partial batch failures, handles OpenAI failure, updates task progress (0→50→100), single batch progress, sets celery_task_id, sets started_at, exactly one batch (50 chunks), uneven batch (75 chunks) |

### Key Design Decisions

- **Flattened structure:** All 11 test classes are top-level `TestCase` subclasses (not nested), because pytest does not discover nested `TestCase` classes.
- **Shared helpers:** `_make_fake_embedding()`, `_mock_openai_response()`, `_auth_header()`, `_create_document()`, `_mock_celery_request()` defined at module level for reuse across all test classes.
- **Naming convention:** All test methods renamed to match the Task 9 spec (e.g., `test_generate_embedding_returns_1536_floats` instead of `test_returns_1536_floats`).
- **One new test:** `test_batch_embed_handles_up_to_100_chunks` added to `ChunkBatchEmbedViewTests` — verifies POST with 100 chunk IDs is accepted.

### Files Modified

1. **`src/backend/documents/tests/test_embedding_service.py`** — **DELETED** (732 lines). All tests moved to `test_embedding.py`.

2. **`src/backend/documents/tests/test_views.py`** — **MODIFIED**. Removed 4 embedding view test classes (DocumentEmbedViewTests, ChunkBatchEmbedViewTests, ChunkReEmbedViewTests, TaskStatusViewTests) and their header comment. Remaining tests: DocumentProcessViewTests, ProcessingTaskRetryViewTests, DocumentProcessingStatusViewTests, DocumentUploadViewSmokeTests, DocumentChunksListViewTests, ProcessingServiceUnitTests.

3. **`src/backend/documents/tests/test_tasks.py`** — **MODIFIED**. Removed EmbedDocumentTaskTests class (13 tests, lines 748-1015). Remaining tests: ExtractTextFromPdfTests, ChunkDocumentTests, ProcessDocumentTests, HandleChainErrorTests.

### Test Results

- **All 57 embedding tests pass** (verified with `docker-compose exec backend pytest -v --tb=short`)
- **Full test suite: 336 passed, 0 failed, 5 warnings** (verified with `docker-compose exec backend pytest -v --tb=short`)
- Warnings are pre-existing (deprecation warnings for STATICFILES_STORAGE, drf_yasg, middleware, and pytest return values)

## Next Steps

- No further steps required for this task.
- Future work could include adding integration tests that verify end-to-end embedding flow with a real Celery worker.
