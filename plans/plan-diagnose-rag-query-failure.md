# Diagnostic & Fix Plan: RAG Query Fails for "November 1997"

## Problem Summary

User uploaded an English textbook ("Active 4") and asked: **"what happened in November 1997"**. The RAG system responded: *"I don't have enough information to answer that question based on the provided context."*

This means the retrieval step (hybrid search) failed to find the relevant chunk containing the text about November 1997, even though the text clearly exists in the document.

---

## Root Cause Analysis

### Root Cause: `filters={"legal_status": "valid"}` Blocks Non-Legal Documents

**File:** [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py:215)

```python
chunks = hybrid_search(
    document_id=document_id,
    query_vector=query_embedding,
    query_text=question,
    top_k=top_k,
    filters={"legal_status": "valid"},  # <-- THE PROBLEM
)
```

The RAG service hardcodes `filters={"legal_status": "valid"}` for **ALL** documents. For a non-legal document like an English textbook, all chunks have `legal_status=NULL` (because the chunking service only populates this field for Persian legal documents). The filter `legal_status="valid"` excludes all chunks where `legal_status IS NULL`, resulting in **zero chunks retrieved**.

**Evidence:**
- In [`document_processing.py`](src/backend/documents/tasks/document_processing.py:510-513), the denormalized fields (`law_name`, `legal_status`, etc.) are populated from `chunk.metadata.get("...")`. For non-legal documents, these metadata keys don't exist, so all fields remain `NULL`.
- The `_apply_metadata_filters()` function in [`search_service.py`](src/backend/documents/services/search_service.py:95) applies exact-match filters. `legal_status="valid"` will NOT match `legal_status=NULL`.

---

## Fix Plan

### Step 1: Add `document_type` Field to `Document` Model

**File:** [`src/backend/documents/models.py`](src/backend/documents/models.py:15)

Add a new field to distinguish between regular user uploads and reference legal documents:

```python
class Document(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('user_upload', 'User Upload'),
        ('reference_law', 'Reference Law'),
    ]
    
    # ... existing fields ...
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        default='user_upload',
        db_index=True,
        help_text="Type of document: 'user_upload' for regular files, "
                  "'reference_law' for system reference legal texts.",
    )
```

**Why this approach (instead of querying Chunk table):**
- Querying `DocumentChunk` for every RAG query adds unnecessary load on the chunks table
- A simple field on the `Document` model is indexed and O(1) to check
- More extensible for future document types
- Clear semantic meaning — the document itself knows its type

### Step 2: Create & Run Migration

```bash
docker-compose exec backend python manage.py makemigrations documents
docker-compose exec backend python manage.py migrate
```

### Step 3: Update RAG Service to Use `document_type`

**File:** [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py:161-216)

```python
def _get_rag_filters(document_id: str) -> dict | None:
    """Determine RAG search filters based on document type.
    
    For reference legal documents, only include valid (non-obsolete) laws.
    For regular user uploads, no filters are applied.
    """
    try:
        doc = Document.objects.only("document_type").get(id=document_id)
        if doc.document_type == "reference_law":
            return {"legal_status": "valid"}
    except Document.DoesNotExist:
        pass
    return None
```

Then in both `run_rag_query()` and `run_rag_query_stream()`:

```python
filters = _get_rag_filters(document_id)
chunks = hybrid_search(
    document_id=document_id,
    query_vector=query_embedding,
    query_text=question,
    top_k=top_k,
    filters=filters,
)
```

### Step 4: Update Document Upload/Processing to Set `document_type`

**File:** [`src/backend/documents/views.py`](src/backend/documents/views.py) — Document upload view

For now, all uploaded documents default to `'user_upload'`. In the future, a separate admin endpoint or import process can create `'reference_law'` documents.

### Step 5: Update Reference Documentation

- [`docs/references/database-schema.md`](docs/references/database-schema.md) — Add `document_type` field
- [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) — Update WIP state

### Step 6: Run Tests

```bash
docker-compose exec backend pytest
```

---

## Files to Modify

| File | Change |
|------|--------|
| [`src/backend/documents/models.py`](src/backend/documents/models.py) | Add `document_type` field to `Document` model |
| `src/backend/documents/migrations/0007_add_document_type.py` | **NEW** migration |
| [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) | Add `_get_rag_filters()` and use it instead of hardcoded filter |
| [`docs/references/database-schema.md`](docs/references/database-schema.md) | Add `document_type` field documentation |
| [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Update WIP state |

---

## Regarding Persian Legal Texts

The user also asked: **"آیا متن حقوقی فارسی بدم اوکی میشه؟"** (Will Persian legal texts work?)

**Answer:** Yes, the pipeline is specifically designed for Persian legal texts:

1. **Extraction:** PyMuPDF with RTL flags → pdfplumber fallback → Tesseract OCR with Persian language pack
2. **Normalization:** `PersianNormalizer` handles Tatweel, Arabic character variants, ZWNJ, and Persian digits
3. **Chunking:** `ChunkingService` detects Persian legal structure (مواد, تبصره, بند, فصل) and chunks by structural boundaries
4. **Search:** Hybrid search (vector + keyword FTS) with Persian digit normalization for matching
5. **Legal context:** The `legal_context` property provides formatted Persian legal provenance

The `nomic-embed-text` model should work reasonably well for Persian text since it's a multilingual model.

---

## Log Commands (for diagnostics if needed)

```bash
# View backend logs
docker-compose logs --tail=50 backend

# Check document types in database
docker-compose exec backend python -c "
from documents.models import Document
from django.db.models import Count
print('Document types:')
print(Document.objects.values('document_type').annotate(count=Count('id')).order_by('document_type'))
"
```
