# E04 Refactoring Prompt — Code Mode

## Task

Apply the following refactoring changes to the E04 Document Processing Pipeline. All changes are minor — no architectural changes, no test modifications needed (existing tests should continue to pass).

---

## Change 1: Use Storage Backend in `extract_text_from_pdf`

**File:** `src/backend/documents/tasks/document_processing.py`

**Problem:** Lines 125-128 access the PDF file directly via filesystem path, bypassing the storage backend abstraction. This will break with S3 storage.

**Change:** Replace the direct filesystem path resolution with the storage backend's `open()` method. The storage backend is already imported at line 42 (`from documents.storage import get_storage_backend`).

Replace lines 122-145 (the file resolution + `fitz.open` block):

```python
    try:
        # Resolve the PDF content using the storage backend.
        storage = get_storage_backend()
        pdf_content = storage.open(document.file_path)
        
        # Check PDF magic bytes before attempting to open.
        header = pdf_content.read(4)
        pdf_content.seek(0)
        if header != b"%PDF":
            fail_processing_task(
                processing_task, document, "File is not a valid PDF", logger,
            )
            return ""

        pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
    except fitz.FileDataError as e:
        error_msg = classify_pdf_error(e, document.file_path)
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""
    except Exception as e:
        error_msg = classify_pdf_error(e, document.file_path)
        fail_processing_task(processing_task, document, error_msg, logger)
        return ""
```

**Note:** Remove the now-unused `import os` at line 26 and the `from django.conf import settings` at line 44 if they become unused after this change. Also remove the `_has_pdf_magic_bytes` import from line 37 if it's no longer used elsewhere in this file (it's also used in `error_handler.py` but the import here is from `error_handler` — check if it's still needed).

**Important:** Check if `_has_pdf_magic_bytes` is used anywhere else in `document_processing.py`. If not, remove it from the import at line 36-41. The magic bytes check is now done inline.

---

## Change 2: Consolidate Duplicate Except Blocks in `embed_document`

**File:** `src/backend/documents/tasks/embedding_tasks.py`

**Problem:** Lines 113-138 have two `except` blocks (`EmbeddingBatchError` and `Exception`) with identical failure-handling logic.

**Change:** Consolidate into a single `except Exception` block that catches both. The `EmbeddingBatchError` is a subclass of `Exception`, so a single `except Exception` will catch both. Keep the more specific error message for `EmbeddingBatchError` by checking `isinstance`.

Replace lines 113-138:

```python
    except Exception as e:
        if isinstance(e, EmbeddingBatchError):
            error_message = f"Embedding failed after partial progress: {e}"
        else:
            error_message = f"Embedding failed: {e}"
        
        logger.exception(
            "embed_document: %s (document=%s, task=%s)",
            error_message,
            document_id,
            task_id,
        )
        processing_task.status = "failed"
        processing_task.error_message = error_message
        processing_task.completed_at = timezone.now()
        processing_task.save(update_fields=["status", "error_message", "completed_at"])
```

**Note:** Remove the now-unused `EmbeddingBatchError` import from `providers.base` at line 23 if it's no longer needed. Check if it's used elsewhere in the file first.

---

## Change 3: Use `bulk_update` in `_process_chunk_batch`

**File:** `src/backend/documents/services/embedding_service.py`

**Problem:** Lines 128-132 save each chunk individually inside the loop (N+1 pattern).

**Change:** Collect updated chunks and use `bulk_update()` after each sub-batch.

Replace lines 123-135:

```python
    for batch_start in range(0, total, SUB_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + SUB_BATCH_SIZE]
        texts = [chunk.content for chunk in batch]
        embeddings = batch_generate_embeddings(texts)

        updated_chunks = []
        for chunk, embedding in zip(batch, embeddings):
            if embedding is not None:
                chunk.embedding = embedding
                updated_chunks.append(chunk)
                processed += 1

        if updated_chunks:
            DocumentChunk.objects.bulk_update(updated_chunks, ["embedding"])

        if progress_callback:
            progress_callback(processed)

    return processed
```

---

## Change 4: Skip Chunk ProcessingTask Creation When Document Already Failed

**File:** `src/backend/documents/tasks/document_processing.py`

**Problem:** In `chunk_document`, a `ProcessingTask` with `task_type="chunk"` is created at line 231 before the empty-text check. If the document is already in "failed" status, this creates a misleading "completed" chunk task.

**Change:** Move the early-return check (document already failed) to **before** the `ProcessingTask` creation.

Restructure the beginning of `chunk_document` (after the `Document.DoesNotExist` check at line 226):

```python
    # If the document is already in a terminal failed state, skip entirely.
    if document.processing_status == "failed":
        logger.info(
            "chunk_document: Document %s is already failed — skipping chunking",
            document_id,
        )
        return

    # Create a new ProcessingTask for the chunk step.
    chunk_task = ProcessingTask.objects.create(
        document=document,
        task_type="chunk",
        celery_task_id=self.request.id,
        status="running",
        started_at=timezone.now(),
    )
```

Then simplify the empty-text handling block (lines 240-256) — remove the Bug #2 guard since we already checked for "failed" above:

```python
    # Handle empty text.
    if not extracted_text or not extracted_text.strip():
        logger.info("chunk_document: Document %s has no extracted text — skipping chunking", document_id)
        document.total_chunks = 0
        document.processing_status = "completed"
        document.save(update_fields=["total_chunks", "processing_status"])

        chunk_task.status = "completed"
        chunk_task.completed_at = timezone.now()
        chunk_task.save(update_fields=["status", "completed_at"])
        return
```

And simplify the success block (lines 291-299) — remove the Bug #2 guard:

```python
        # Update document metadata.
        document.total_chunks = len(chunks_to_create)
        document.processing_status = "completed"
        document.save(update_fields=["total_chunks", "processing_status"])
```

**Important:** This change removes the Bug #2 guards. Verify that the existing tests `test_does_not_overwrite_failed_status_on_empty_text` and `test_does_not_overwrite_failed_status_on_successful_chunking` still pass — they should because we now return early before creating the chunk task when the document is already failed.

---

## Verification

After applying all changes, run the existing tests to confirm nothing is broken:

```bash
docker-compose exec backend pytest src/backend/documents/tests/test_tasks.py src/backend/tests/test_processing.py src/backend/documents/tests/test_embedding.py -v
```

All tests should pass without modification.
