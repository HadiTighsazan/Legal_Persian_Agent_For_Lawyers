# PRD: E-05 — Embedding & Vector Storage

**Epic:** E-05 | Embedding & Vector Storage  
**Status:** ⏳ Todo  
**Owner:** AI Coding Assistant (Cline)  
**Dependencies:** E-04 (Document Processing Pipeline) must be complete  
**Enables:** E-06 (Semantic Search & Retrieval)

---

## Overview

Generate OpenAI embeddings for processed document chunks, store them in pgvector, support batch processing, and allow re-embedding when needed.

---

## Database Schema Requirements

**Table:** `chunks`  
- Column `embedding` already exists: `VECTOR(1536) | NULL`
- Index `idx_chunks_embedding` already exists (ivfflat)
- **No schema migration needed** — schema is ready.

**Embedding model:** OpenAI `text-embedding-3-small` (1536 dimensions)

---

## API Endpoints to Implement

Based on `api-registry.md` and roadmap context:

1. **POST `/api/documents/{document_id}/embed`** — trigger embedding generation for all chunks of a document
2. **POST `/api/chunks/batch-embed`** — batch embed multiple chunks by IDs
3. **POST `/api/chunks/{chunk_id}/re-embed`** — re-generate embedding for a single chunk
4. **GET `/api/tasks/{task_id}`** — check embedding task status (task_type: `"embed"`)

---

## Micro-Tasks

### **Task 1: Implement OpenAI Embedding Service**

**File to create:** `src/services/embedding.service.ts` (or equivalent per `.clinerules`)

**Requirements:**
- Function `generateEmbedding(text: string): Promise<number[]>`
- Call OpenAI API `text-embedding-3-small`
- Return 1536-dimension vector
- Handle rate limits (retry with exponential backoff)
- Handle empty/null text gracefully (return null or skip)
- Log errors clearly

**Acceptance Criteria:**
- ✅ Service can generate embedding for a single text string
- ✅ Returns array of 1536 floats
- ✅ Handles OpenAI API errors without crashing
- ✅ Respects `.clinerules` file structure and naming conventions

---

### **Task 2: Implement Batch Embedding Logic**

**File to create/modify:** `src/services/embedding.service.ts`

**Requirements:**
- Function `batchGenerateEmbeddings(texts: string[]): Promise<(number[] | null)[]>`
- Use OpenAI batch embedding API (up to 2048 texts per request per OpenAI limits)
- Split large batches into sub-batches if needed
- Return array of embeddings in same order as input
- Handle partial failures (some embeddings succeed, some fail)

**Acceptance Criteria:**
- ✅ Can embed up to 100 chunks in one call
- ✅ Returns results in correct order
- ✅ Logs which chunks failed (if any)

---

### **Task 3: POST `/api/documents/{document_id}/embed` — Trigger Document Embedding**

**File to create/modify:** `src/routes/documents.routes.ts` (or per `.clinerules`)

**Request:**
```json
POST /api/documents/{document_id}/embed
```

**Response:**
```json
{
  "task_id": "uuid",
  "task_type": "embed",
  "status": "pending",
  "document_id": "uuid",
  "total_chunks": 42
}
```

**Logic:**
1. Fetch all chunks for `document_id` from DB where `embedding IS NULL`
2. Create async task record in `tasks` table (task_type: `"embed"`, status: `"pending"`)
3. Queue background job to process embeddings
4. Return task_id immediately

**Acceptance Criteria:**
- ✅ Endpoint returns task_id within 200ms
- ✅ Task record created in DB with correct `task_type` and `document_id`
- ✅ Only chunks without embeddings are queued
- ✅ Returns 404 if document_id not found
- ✅ Follows `.clinerules` error handling patterns

---

### **Task 4: Background Job — Process Embedding Task**

**File to create:** `src/jobs/embedding.job.ts` (or per `.clinerules`)

**Requirements:**
- Listen for `embed` tasks
- Fetch chunks for the document
- Call `batchGenerateEmbeddings()` in batches of 50 chunks
- Update `chunks.embedding` column for each chunk
- Update task `status` to `"running"`, then `"completed"` or `"failed"`
- Update task `progress` field (0–100)
- Log errors per chunk if embedding fails

**Acceptance Criteria:**
- ✅ Task status updates correctly (`pending` → `running` → `completed`)
- ✅ Progress field updates incrementally (e.g., 25%, 50%, 75%, 100%)
- ✅ All chunk embeddings saved to DB
- ✅ Task marked `"failed"` 
### **Task 5: POST `/api/chunks/batch-embed` — Batch Embed Chunks**

**Endpoint**
POST /api/chunks/batch-embed


**Request**
```json
{
  "chunk_ids": ["uuid1", "uuid2", "uuid3"]
}
```

**Logic**
1. Validate chunk IDs.
2. Fetch chunk text for each ID.
3. Call `batchGenerateEmbeddings()`.
4. Store embeddings in `chunks.embedding`.

**Acceptance Criteria**
- ✅ Handles up to 100 chunk IDs per request
- ✅ Skips chunks that already have embeddings
- ✅ Returns count of processed chunks

**Response**
```json
{
  "processed": 12,
  "skipped": 3,
  "failed": 1
}
```

---

### **Task 6: POST `/api/chunks/{chunk_id}/re-embed` — Re-generate Single Embedding**

**Endpoint**
POST /api/chunks/{chunk_id}/re-embed


**Logic**
1. Fetch chunk text.
2. Call `generateEmbedding()`.
3. Replace existing embedding in `chunks.embedding`.

**Acceptance Criteria**
- ✅ Existing embedding is overwritten
- ✅ Returns updated chunk metadata
- ✅ Returns 404 if chunk does not exist

**Response**
```json
{
  "chunk_id": "uuid",
  "embedding_updated": true
}
```

---

### **Task 7: pgvector Similarity Index Verification**

Even though schema already includes the index, the assistant must verify its existence.

**Required SQL**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
ON chunks
USING ivfflat (embedding vector_cosine_ops);
```

**Acceptance Criteria**
- ✅ Index exists
- ✅ Index type is `ivfflat`
- ✅ Works with cosine similarity
- ✅ No migration error if index already exists

---

### **Task 8: Embedding Rebuild Utility (Admin Script)**

**File:** `scripts/reembed-all.ts`

**Purpose**
Rebuild embeddings when:
- embedding model changes
- chunk content changes
- vector dimension changes

**Logic**
1. Query all chunks
2. Set `embedding = NULL`
3. Trigger embedding jobs in batches of 500 chunks

**Acceptance Criteria**
- ✅ Script processes large datasets safely
- ✅ Uses batching to avoid API rate limits
- ✅ Logs progress

---

# Edge Cases

The implementation must handle:

• Empty chunk text  
• OpenAI API failure  
• Rate limits  
• Partial batch failure  
• Chunk deleted during processing  
• Task restart after crash

---

# Observability Requirements

Logs must include:

• document_id  
• chunk_id  
• task_id  
• batch size  
• embedding generation time  
• API errors

---

# Performance Targets

• Batch size: **50 chunks per request**  
• Max document size: **10,000 chunks**  
• Average embedding throughput: **≥ 200 chunks/minute**

---

# Final Acceptance Criteria for Epic E‑05

The Epic is complete when:

✅ Chunks can generate embeddings using OpenAI  
✅ Embeddings stored in `chunks.embedding (VECTOR(1536))`  
✅ Batch embedding supported  
✅ Async embedding tasks implemented (`task_type: "embed"`)  
✅ Re-embedding endpoint works  
✅ pgvector index verified and operational  
✅ System ready for **E‑06 Semantic Search**

---

