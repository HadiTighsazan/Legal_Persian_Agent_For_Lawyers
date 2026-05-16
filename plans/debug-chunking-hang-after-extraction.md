# Debug Plan: Chunking Pipeline Hangs After Text Extraction

## Problem Summary

After uploading a Persian legal PDF (especially files larger than 1-2 pages), the text extraction step completes successfully, but the pipeline **hangs indefinitely** at the chunking stage. No chunking or embedding logs appear after extraction completes.

The user reports:
- 1-2 page files **sometimes** work correctly
- Larger files consistently hang after extraction
- The container startup logs show `collectstatic` failing, but this is a separate issue

## Root Cause Analysis

### PRIMARY ROOT CAUSE: Infinite Loop in `_split_large_section`

**Location:** [`PersianLegalChunker._split_large_section()`](src/backend/documents/services/persian_legal_chunker.py:825-886)

**The Bug:**

```python
while i < len(sentences):
    # ... accumulate sentences into chunk_sentences ...
    
    if not chunk_sentences:
        # Single sentence exceeds max_tokens — keep it anyway
        chunk_sentences = [sentences[i]]
        j = i + 1

    # ...
    
    if overlap_sentences > 0 and j < len(sentences):
        i = j - overlap_sentences   # <-- BUG: when j = i+1 and overlap_sentences = 1
    else:                            #      i = (i+1) - 1 = i  →  i never advances!
        i = j
```

**Trigger Condition:**
When `overlap_sentences >= 1` (default is `1`), and a single sentence exceeds `max_chunk_tokens` (default `400`), the inner `while` loop at line 857 breaks immediately because the first sentence already exceeds the limit. This causes:

1. `chunk_sentences` is empty → enters the `if not chunk_sentences` branch
2. Sets `j = i + 1`
3. Then `i = j - overlap_sentences = (i + 1) - 1 = i` → **i doesn't change!**
4. The outer `while` loop never terminates → **infinite loop**

**Why 1-2 page files sometimes work:**
Small files may not have any single sentence exceeding 400 tokens, so the bug is never triggered. Larger Persian legal documents often have long, dense paragraphs (especially in legal rulings) that easily exceed 400 tokens as a single sentence.

### SECONDARY ISSUE: `_merge_small_chunks` First-Pass Grouping Logic

**Location:** [`PersianLegalChunker._merge_small_chunks()`](src/backend/documents/services/persian_legal_chunker.py:749-819)

**The Issue:**

```python
if current_tokens + sentence_tokens <= min_tokens * 2:
    # Still accumulating
```

The threshold `min_tokens * 2` (default `300`) is used for the initial grouping pass. This means groups can grow up to 300 tokens before being split. Combined with the second-pass merge logic, this can create groups that are significantly larger than `max_chunk_tokens` (400), which then get passed to `_split_large_section` — potentially triggering the infinite loop more frequently.

### TERTIARY ISSUE: `collectstatic` Failure in `entrypoint.sh`

**Location:** [`docker/backend/entrypoint.sh`](docker/backend/entrypoint.sh:19-20)

The user's logs show `collectstatic` crashing with a `whitenoise` traceback. This is a **container startup issue**, not directly related to the chunking hang. However, if the backend container fails to start properly, the Celery worker may also be affected.

## Debugging Steps

### Step 1: Verify the Infinite Loop Hypothesis

Run a direct test of `PersianLegalChunker` with a long sentence:

```bash
docker-compose exec backend python -c "
from documents.services.persian_legal_chunker import PersianLegalChunker

chunker = PersianLegalChunker(
    min_chunk_tokens=150,
    max_chunk_tokens=400,
    overlap_sentences=1,
)

# Create a single sentence that exceeds max_chunk_tokens
long_sentence = 'این یک جمله بسیار طولانی است که باید بیش از چهارصد توکن باشد ' * 100
text = f'[PAGE 1]\nماده ۱:\n{long_sentence}\n[PAGE 2]\nتبصره ۱:\nاین یک جمله کوتاه است.'

print('Starting chunk_text...')
import time
start = time.time()
try:
    chunks = chunker.chunk_text(text)
    print(f'Success: {len(chunks)} chunks in {time.time()-start:.2f}s')
except Exception as e:
    print(f'Error: {e}')
    print(f'Time elapsed: {time.time()-start:.2f}s')
"
```

If this hangs (runs for >30 seconds), the infinite loop is confirmed.

### Step 2: Check Celery Worker Logs

```bash
docker-compose logs celery_worker --tail=100
```

Look for:
- Any traceback after extraction completion
- Memory errors or worker crashes
- Tasks stuck in "running" state

### Step 3: Check Document Status in Database

```bash
docker-compose exec backend python -c "
import django; import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from documents.models import Document
from tasks.models import ProcessingTask

doc = Document.objects.last()
print(f'Document: {doc.id}')
print(f'  processing_status: {doc.processing_status}')
print(f'  status: {doc.status}')
print(f'  extracted_text_length: {doc.extracted_text_length}')
print(f'  total_chunks: {doc.total_chunks}')
print(f'  processing_error: {doc.processing_error}')

tasks = ProcessingTask.objects.filter(document=doc).order_by('created_at')
for t in tasks:
    print(f'  Task: {t.task_type} status={t.status} error={t.error_message}')
"
```

## Proposed Fixes

### Fix 1 (CRITICAL): Prevent Infinite Loop in `_split_large_section`

In [`_split_large_section`](src/backend/documents/services/persian_legal_chunker.py:879-884), change the overlap logic to ensure `i` always advances:

```python
# Move to next chunk with overlap
if overlap_sentences > 0 and j < len(sentences):
    # Start the next chunk `overlap_sentences` sentences before
    # the end of the current chunk
    next_i = j - overlap_sentences
    # GUARD: Ensure we always make progress (prevent infinite loop)
    # when a single sentence exceeds max_tokens and overlap_sentences >= 1
    i = next_i if next_i > i else j
else:
    i = j
```

### Fix 2 (RECOMMENDED): Add Max Iteration Guard to `_split_large_section`

Add a safety counter to prevent any possible infinite loop:

```python
max_iterations = len(sentences) * 2  # Should never need more than len(sentences)
iteration_count = 0

while i < len(sentences):
    iteration_count += 1
    if iteration_count > max_iterations:
        logger.error(
            "_split_large_section: Exceeded max iterations (%d) for %d sentences — breaking",
            max_iterations, len(sentences),
        )
        break
    # ... rest of the loop ...
```

### Fix 3 (DEFENSIVE): Add Timeout to `chunk_document` Task

In [`chunk_document`](src/backend/documents/tasks/document_processing.py:1183), add a Celery `soft_time_limit` to prevent the task from hanging indefinitely:

```python
@shared_task(bind=True, soft_time_limit=300, time_limit=600)
def chunk_document(self, extracted_text: str, document_id: str) -> None:
```

### Fix 4 (SEPARATE): Fix `collectstatic` in `entrypoint.sh`

The `collectstatic` failure in [`entrypoint.sh`](docker/backend/entrypoint.sh:19-20) should be wrapped in a try-catch or investigated separately. This may be a `whitenoise` version compatibility issue.

## Execution Order

1. **Apply Fix 1** (critical — prevents infinite loop)
2. **Apply Fix 2** (recommended — safety guard)
3. **Apply Fix 3** (defensive — task timeout)
4. **Run Step 1 test** to verify the fix
5. **Upload a test document** (3-5 pages) to verify the full pipeline
6. **Investigate `collectstatic` failure** separately if needed
