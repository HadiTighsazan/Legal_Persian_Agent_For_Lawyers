# WIP Context — Fix: RAG Query Fails for Non-Legal Documents

## Status: ✅ COMPLETED (2026-05-05)

The `legal_status: "valid"` hardcoded filter in the RAG service has been replaced with a document-type-aware approach. Non-legal documents (e.g., English textbooks) no longer get filtered, so chunks with `legal_status=NULL` are retrievable.

---

## Problem

The RAG service hardcoded `filters={"legal_status": "valid"}` for **all** documents. For non-legal documents (e.g., an English textbook), all chunks have `legal_status=NULL` because the chunking service only populates this field for Persian legal documents. The filter `legal_status="valid"` excluded all chunks where `legal_status IS NULL`, resulting in **zero chunks retrieved** and the response: *"I don't have enough information to answer that question based on the provided context."*

## Fix Applied

### 1. Added `document_type` Field to `Document` Model
- **File:** [`src/backend/documents/models.py`](src/backend/documents/models.py:15)
- New field: `document_type = CharField(max_length=20, choices=[('user_upload', 'User Upload'), ('reference_law', 'Reference Law')], default='user_upload', db_index=True)`
- All existing documents default to `'user_upload'` (backward compatible)

### 2. Created Migration `0007_add_document_type`
- **File:** [`src/backend/documents/migrations/0007_add_document_type.py`](src/backend/documents/migrations/0007_add_document_type.py)
- Adds the `document_type` column to the `documents` table with `db_index=True`

### 3. Updated RAG Service with `_get_rag_filters()`
- **File:** [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py:161)
- Added [`_get_rag_filters(document_id)`](src/backend/conversations/rag_service.py:161) helper that checks the document's `document_type`:
  - For `reference_law` → returns `{"legal_status": "valid"}`
  - For `user_upload` (and any other type) → returns `None` (no filters)
- Updated both [`run_rag_query()`](src/backend/conversations/rag_service.py:196) and [`run_rag_query_stream()`](src/backend/conversations/rag_service.py:306) to use `_get_rag_filters()` instead of the hardcoded `{"legal_status": "valid"}`

### 4. Updated Reference Documentation
- [`docs/references/database-schema.md`](docs/references/database-schema.md): Added `document_type` column to documents table, added `idx_documents_document_type` index, added migration 0007 notes

---

## Files Changed

| File | Action |
|------|--------|
| `src/backend/documents/models.py` | Modified (added `document_type` field + index) |
| `src/backend/documents/migrations/0007_add_document_type.py` | **NEW** |
| `src/backend/conversations/rag_service.py` | Modified (added `_get_rag_filters()`, updated both query functions) |
| `docs/references/database-schema.md` | Modified (added `document_type` column, index, migration notes) |
| `docs/active-task/wip-context.md` | Modified (this file) |

---

## Next Steps / Verification

1. **Run migrations:** `docker-compose exec backend python manage.py migrate`
2. **Run backend tests:** `docker-compose exec backend pytest`
3. **Verify RAG query for non-legal documents** — ask a question about an uploaded English textbook
4. **Verify RAG query for legal documents** — `legal_status: "valid"` filter still applies for `reference_law` documents
