# WIP Context — Task 8 of Epic E-05 (Re-embed Script)

## Status: ✅ COMPLETED

## What Was Completed

### New Files Created

1. **`src/backend/scripts/__init__.py`** (NEW FILE) — Empty init file to make `scripts` a Python package.

2. **`src/backend/scripts/reembed_all.py`** (NEW FILE) — Standalone Django script that clears all chunk embeddings and re-triggers the `embed_document` Celery task for every document.

### Script Logic

The script follows this flow:

1. **Count total chunks** — `DocumentChunk.objects.count()`. If 0, logs "No chunks found" and exits cleanly.
2. **Clear all embeddings** — Single `UPDATE` query via `DocumentChunk.objects.update(embedding=None)`. Logs "Cleared embeddings for X chunks".
3. **Collect unique document IDs** — Uses `DocumentChunk.objects.values_list("document_id", flat=True).iterator(chunk_size=500)` to stream results in memory-efficient batches. Logs progress every 500 chunks (e.g., "Scanning chunks... 500/50000 (1%)").
4. **Queue embed_document per document** — For each unique document ID:
   - Verifies the Document still exists (catches `Document.DoesNotExist`)
   - Creates a `ProcessingTask` with `task_type="embed"`, `status="pending"`
   - Calls `embed_document.delay(doc_id, str(processing_task.id))`
   - Logs "Queued re-embed for document {doc_id} (task={task_id})"
   - Catches any exception, logs it, increments `failed_count`, continues
5. **Summary** — Logs "Re-embedding complete: X documents queued, Y failed (Z total chunks)". Exits with code 1 if any failures, else 0.

### Key Design Decisions

- **Standalone script (not a management command):** The PRD specifies `scripts/reembed_all.py`. It runs outside the Django request/response cycle as an admin utility.
- **Django setup:** Calls `django.setup()` after setting `DJANGO_SETTINGS_MODULE` so Django ORM is available.
- **Memory efficiency:** Uses `.iterator(chunk_size=500)` to stream chunk IDs rather than loading all into memory.
- **Reuses existing infrastructure:** Delegates actual embedding to the existing `embed_document` Celery task, avoiding duplication of embedding logic.
- **Error resilience:** Catches `Document.DoesNotExist` (document deleted between scan and queue) and generic exceptions per document, continuing to process remaining documents.

### Logging Configuration
- Logger name: `"reembed_all"`
- Level: `INFO`
- Handler: `StreamHandler(sys.stdout)`
- Format: `"[reembed_all] %(message)s"`

## Usage

```bash
docker-compose exec backend python scripts/reembed_all.py
```

## Verification

After running, verify:
1. Logs show the expected progress and summary
2. `docker-compose exec db psql -U docuchat -d docuchat -c "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL;"` returns the total chunk count
3. Celery worker logs show `embed_document` tasks being executed

## Edge Cases Handled
- **No chunks exist:** Script logs "No chunks found" and exits cleanly (exit 0)
- **Document deleted between scan and queue:** Catches `Document.DoesNotExist` and logs a warning
- **Celery unavailable:** `embed_document.delay()` raises an exception; script catches it and logs the error
- **Very large dataset (100k+ chunks):** Uses `iterator()` to stream results, so memory stays constant

## Next Steps

- Run the script against a development database to verify behavior
- Monitor Celery worker logs to confirm tasks are dispatched and executed
- Optionally add a `--dry-run` flag for safe preview mode
