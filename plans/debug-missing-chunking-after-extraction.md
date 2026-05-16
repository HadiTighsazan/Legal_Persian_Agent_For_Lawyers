# Debug Plan: Missing Chunking/Embedding After Successful Text Extraction

## Problem Summary

After uploading a Persian legal PDF (70 pages, 114,593 characters), the text extraction pipeline completes successfully, but **no chunking or embedding tasks are executed**. The logs show:

```
✅ Extraction complete (20 seconds)
✅ 81 tables extracted
✅ 114,593 characters from 70 pages
❌ No chunking or embedding logs
```

## Architecture Overview

The processing pipeline is orchestrated via a Celery chain in [`process_document`](src/backend/documents/services/processing_service.py:244-248):

```python
chain_obj = chain(
    extract_text_from_pdf.s(document_id),   # Step 1: Extract text → returns str
    chunk_document.s(document_id),           # Step 2: Chunk text → returns None
    embed_document.si(document_id, str(embed_task.id)),  # Step 3: Embed chunks
)
```

The chain is submitted via [`chain_obj.apply_async(link_error=[error_callback])`](src/backend/documents/services/processing_service.py:257).

## Root Cause Analysis

### Hypothesis 1 (Most Likely): `extract_text_from_pdf` Returns Empty String on Success Path

Looking at [`extract_text_from_pdf`](src/backend/documents/tasks/document_processing.py:731), the function stores `extracted_text` on `document.extracted_text` (line 1125) AND returns it (line 1163). However, there are **5 early return paths** that return `""` (empty string):

| Line | Condition | Logged? |
|------|-----------|---------|
| 770 | Document not found | Yes |
| 819 | Not a valid PDF | Yes |
| 825 | File data error | Yes |
| 836 | Unhandled exception | Yes |
| 850 | 0 pages | Yes |

If any of these paths are triggered, `chunk_document` receives `""` and handles it at line 1228 by marking the task as failed. But the user would see error logs, not success logs.

**However**, there's a subtle issue: the `finally` block at line 1164 runs `pdf_document.close()`. If this raises an exception, the `return extracted_text` at line 1163 is **aborted** and the exception propagates. This would cause the task to fail silently (the success log at line 1158 was already written, but the return value is lost).

### Hypothesis 2: Celery Chain Execution Failure

The chain might not be executing the second task due to:

1. **Worker crash after extraction**: The `extract_text_from_pdf` task uses PyMuPDF which can be memory-intensive. If the worker process crashes after completing extraction but before the chain continues, `chunk_document` would never be called.

2. **Redis result backend issue**: The extracted text (114,593 chars ≈ 115KB) is stored in Redis as the task result. If Redis has memory limits or the result expires before the chain continues, the chain might fail.

3. **Celery chain internal error**: The chain itself might have an internal error that prevents it from continuing to the next task.

### Hypothesis 3: Missing `chunk` ProcessingTask

In [`process_document`](src/backend/documents/services/processing_service.py:221-231), only `extract` and `embed` ProcessingTask records are created. The `chunk` ProcessingTask is created **inside** [`chunk_document`](src/backend/documents/tasks/document_processing.py:1219-1225) itself. This is by design, but if `chunk_document` is never called, no `chunk` task record exists, and the monitoring page would show no chunk task.

### Hypothesis 4: Document Status Already Set to "completed"

If the document's `processing_status` was already set to `"completed"` (e.g., from a previous failed attempt that was partially processed), `process_document` would return `None` at line 219 and the chain would not be submitted. But the user says extraction logs are visible, so the chain was submitted.

## Debugging Steps

### Step 1: Check Celery Worker Logs

The most important diagnostic step. Check the Celery worker container logs for errors:

```bash
docker-compose logs celery_worker --tail=100
```

Look for:
- Any traceback or error after the extraction completion
- Messages about task failures or worker crashes
- Redis connection errors
- Memory errors

### Step 2: Check Redis for Stored Task Results

Check if the extraction task result is stored in Redis:

```bash
docker-compose exec redis redis-cli
# List all keys
KEYS *
# Check result backend keys (usually in DB 1)
SELECT 1
KEYS *
# Get the task result
GET celery-task-meta-<task_id>
```

### Step 3: Add Defensive Logging to `extract_text_from_pdf`

Add logging right before the return statement to confirm the return value:

In [`extract_text_from_pdf`](src/backend/documents/tasks/document_processing.py:1163), add:
```python
logger.info(
    "extract_text_from_pdf: Returning %d chars for document %s",
    len(extracted_text), document_id,
)
return extracted_text
```

### Step 4: Add Logging to the Chain's Error Callback

The chain has a `link_error` callback [`_handle_chain_error`](src/backend/documents/tasks/document_processing.py:1378). Check if this callback is being triggered. Add more detailed logging to it.

### Step 5: Verify the Chain is Actually Submitted

Add logging in [`process_document`](src/backend/documents/services/processing_service.py:257) to confirm the chain is submitted and the result ID is returned:

```python
logger.info(
    "process_document: Chain submitted for document %s (celery_task_id=%s)",
    document_id, result.id,
)
```

This log already exists at line 263. Check if it appears in the backend logs.

### Step 6: Test with a Small Document

Upload a small PDF (1-2 pages) and verify the full pipeline works. This helps isolate whether the issue is related to document size.

### Step 7: Direct Test of `chunk_document`

Manually call `chunk_document` with the extracted text to verify it works independently:

```bash
docker-compose exec backend python -c "
from documents.tasks.document_processing import chunk_document
from celery import current_app
# This won't work directly since chunk_document is a Celery task
# Instead, test the PersianLegalChunker directly
from documents.services.persian_legal_chunker import PersianLegalChunker
chunker = PersianLegalChunker()
text = open('/tmp/test_text.txt', 'r').read()  # or use a test string
chunks = chunker.chunk_text(text)
print(f'Generated {len(chunks)} chunks')
for c in chunks:
    print(f'  Chunk: {c.token_count} tokens, pages={c.pages}')
"
```

### Step 8: Check Document Status in Database

Check the document's `processing_status` and `status` fields after extraction:

```bash
docker-compose exec backend python -c "
import django; import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from documents.models import Document
doc = Document.objects.last()
print(f'Document: {doc.id}')
print(f'  processing_status: {doc.processing_status}')
print(f'  status: {doc.status}')
print(f'  extracted_text_length: {doc.extracted_text_length}')
print(f'  total_chunks: {doc.total_chunks}')
print(f'  processing_error: {doc.processing_error}')
from tasks.models import ProcessingTask
tasks = ProcessingTask.objects.filter(document=doc).order_by('created_at')
for t in tasks:
    print(f'  Task: {t.task_type} status={t.status} error={t.error_message}')
"
```

## Proposed Fixes

### Fix 1: Ensure `extract_text_from_pdf` Always Returns Valid Text

In [`extract_text_from_pdf`](src/backend/documents/tasks/document_processing.py), ensure the function never returns `""` on a success path. Add a guard:

```python
# After line 1161, before return
if not extracted_text:
    logger.error(
        "extract_text_from_pdf: extracted_text is empty after successful extraction "
        "for document %s — this should not happen",
        document_id,
    )
    extracted_text = document.extracted_text or ""
```

### Fix 2: Add Chain-Level Monitoring

Add a monitoring task that checks if the chain is progressing correctly. For example, add a periodic task that checks if `chunk_document` has been called within a reasonable time after `extract_text_from_pdf` completes.

### Fix 3: Improve Error Handling in `finally` Block

Wrap the `pdf_document.close()` in a try-except to prevent it from aborting the return:

```python
finally:
    try:
        pdf_document.close()
    except Exception as e:
        logger.warning(
            "extract_text_from_pdf: Error closing PDF for document %s: %s",
            document_id, e,
        )
```

### Fix 4: Add Timeout Monitoring

Add a Celery task timeout monitor that checks if tasks are stuck. The current time limit is 30 minutes (`CELERY_TASK_TIME_LIMIT`), which should be sufficient for a 70-page document.

## Execution Order

1. **Step 1**: Check Celery worker logs (quickest diagnostic)
2. **Step 2**: Check document status in database
3. **Step 3**: Apply Fix 3 (protect `finally` block) — low risk, high impact
4. **Step 4**: Apply Fix 1 (guard return value) — defensive measure
5. **Step 5**: Test with small document
6. **Step 6**: If still broken, add detailed logging and re-test
