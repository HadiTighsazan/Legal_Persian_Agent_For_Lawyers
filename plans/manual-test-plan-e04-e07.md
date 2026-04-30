# Manual Integration Test Plan — Epics E04–E07

> **Target PDF:** `C:/Users/hadit/Desktop/DataAnalysis2 (2)-3.pdf`
> **Environment:** Dockerized (Windows 10, Git Bash)
> **Base URL (via Nginx):** `http://localhost/api/`
> **Direct Backend URL:** `http://localhost:8000/`
> **Prerequisites:** Docker containers running (`docker-compose up -d`), `.env` configured with valid API keys

---

## Table of Contents

1. [Prerequisites & Setup](#1-prerequisites--setup)
2. [Test Flow Overview](#2-test-flow-overview)
3. [Step-by-Step Test Commands](#3-step-by-step-test-commands)
   - [Phase 1: Authentication (E02)](#phase-1-authentication-e02)
   - [Phase 2: Document Upload (E03)](#phase-2-document-upload-e03)
   - [Phase 3: Document Processing Pipeline (E04)](#phase-3-document-processing-pipeline-e04)
   - [Phase 4: Embedding & Vector Storage (E05)](#phase-4-embedding--vector-storage-e05)
   - [Phase 5: Semantic Search & Retrieval (E06)](#phase-5-semantic-search--retrieval-e06)
   - [Phase 6: Conversation & Q&A Engine (E07)](#phase-6-conversation--qa-engine-e07)
   - [Phase 7: Error Handling & Edge Cases](#phase-7-error-handling--edge-cases)
4. [Expected Results Summary](#4-expected-results-summary)
5. [Troubleshooting](#5-troubleshooting)

---

## 1. Prerequisites & Setup

### 1.1 Environment Variables

Ensure your `.env` file has **at minimum** these values configured:

```bash
# Database (defaults work for dev)
POSTGRES_DB=docuchat_db
POSTGRES_USER=docuchat_user
POSTGRES_PASSWORD=changeme

# Django
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,backend,nginx
DJANGO_CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:80

# JWT
JWT_SECRET=your-jwt-secret

# AI Provider — at least ONE must be configured:
# Option A: Google Gemini (recommended for this test)
GOOGLE_API_KEY=your-google-api-key
EMBEDDING_PROVIDER=google
CHAT_PROVIDER=google

# Option B: OpenAI
# OPENAI_API_KEY=sk-...
# EMBEDDING_PROVIDER=openai
# CHAT_PROVIDER=openai
```

### 1.2 Start Services

```bash
# From the project root (c:/Users/hadit/Desktop/rag-project)
docker-compose up -d

# Verify all services are healthy
docker-compose ps
```

Expected output (all services should show `Up` or `healthy`):
```
docuchat_backend       ... Up (healthy)
docuchat_celery_worker ... Up
docuchat_celery_beat   ... Up
docuchat_frontend      ... Up
docuchat_nginx         ... Up (healthy)
docuchat_postgres      ... Up (healthy)
docuchat_redis         ... Up (healthy)
```

### 1.3 Run Migrations (if first time)

```bash
docker-compose exec backend python manage.py migrate
```

### 1.4 Verify Health Check

```bash
curl -s http://localhost:8000/health/ | python -m json.tool
```

**Expected:**
```json
{
  "status": "ok",
  "timestamp": "...",
  "service": "docuchat-api",
  "version": "1.0.0"
}
```

---

## 2. Test Flow Overview

```mermaid
flowchart TD
    A[Phase 1: Auth] -->|Register + Login| B[Phase 2: Upload PDF]
    B -->|POST /documents/upload| C[Phase 3: Process Pipeline]
    C -->|POST /documents/{id}/process| D[Poll processing-status]
    D -->|Wait for completed| E[Phase 4: Embedding]
    E -->|POST /documents/{id}/embed| F[Poll task status]
    F -->|Wait for completed| G[Phase 5: Semantic Search]
    G -->|POST /documents/{id}/search| H[Phase 6: Q&A]
    H -->|POST /documents/{id}/query| I[Create Conversation]
    I -->|POST /conversations| J[Ask Questions]
    J -->|POST /conversations/{id}/messages| K[Phase 7: Edge Cases]
```

---

## 3. Step-by-Step Test Commands

> **Note:** All commands use `bash` syntax. Run them in Git Bash.
> We store the `ACCESS_TOKEN` and `DOCUMENT_ID` in shell variables for reuse.

---

### Phase 1: Authentication (E02)

#### Step 1.1 — Register a new user

```bash
curl -s -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "testuser@example.com",
    "password": "testpassword123",
    "full_name": "Test User"
  }' | python -m json.tool
```

**Expected Response:** `201 Created`
```json
{
  "user": {
    "id": "<uuid>",
    "email": "testuser@example.com",
    "full_name": "Test User",
    "created_at": "...",
    "is_active": true
  },
  "accessToken": "<jwt_token>",
  "refreshToken": "<jwt_refresh_token>"
}
```

**Save the tokens:**
```bash
# Extract and save tokens
REGISTER_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email": "testuser@example.com", "password": "testpassword123", "full_name": "Test User"}')

ACCESS_TOKEN=$(echo "$REGISTER_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")
REFRESH_TOKEN=$(echo "$REGISTER_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['refreshToken'])")
echo "ACCESS_TOKEN=$ACCESS_TOKEN"
echo "REFRESH_TOKEN=$REFRESH_TOKEN"
```

> **If user already exists**, use login instead (Step 1.2).

#### Step 1.2 — Login (alternative if already registered)

```bash
LOGIN_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "testuser@example.com", "password": "testpassword123"}')

ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")
REFRESH_TOKEN=$(echo "$LOGIN_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['refreshToken'])")
echo "ACCESS_TOKEN=$ACCESS_TOKEN"
```

**Expected:** `200 OK` with same structure as register (minus `user`).

#### Step 1.3 — Verify token works (GET /users/me)

```bash
curl -s http://localhost:8000/users/me/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
```

**Expected:** `200 OK` with user profile including `email`, `full_name`, `is_active`.

---

### Phase 2: Document Upload (E03)

#### Step 2.1 — Upload the target PDF

```bash
UPLOAD_RESPONSE=$(curl -s -X POST http://localhost:8000/documents/upload/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "file=@/c/Users/hadit/Desktop/DataAnalysis2 (2)-3.pdf" \
  -F "title=Data Analysis Test Document")

echo "$UPLOAD_RESPONSE" | python -m json.tool

# Save the document ID
DOCUMENT_ID=$(echo "$UPLOAD_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "DOCUMENT_ID=$DOCUMENT_ID"
```

**Expected Response:** `201 Created`
```json
{
  "id": "<uuid>",
  "title": "Data Analysis Test Document",
  "original_filename": "DataAnalysis2 (2)-3.pdf",
  "file_size": <bytes>,
  "total_pages": null,
  "status": "uploaded",
  "created_at": "..."
}
```

**Verify:**
- `file_size` > 0 (PDF has content)
- `status` is `"uploaded"` (not yet processed)
- `total_pages` is `null` (not yet extracted)

---

### Phase 3: Document Processing Pipeline (E04)

This phase tests the Celery pipeline: **Extract → Chunk**.

#### Step 3.1 — Trigger processing

```bash
PROCESS_RESPONSE=$(curl -s -X POST "http://localhost:8000/documents/$DOCUMENT_ID/process/" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

echo "$PROCESS_RESPONSE" | python -m json.tool

# Save the task ID
PROCESS_TASK_ID=$(echo "$PROCESS_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['task_id'])")
echo "PROCESS_TASK_ID=$PROCESS_TASK_ID"
```

**Expected Response:** `202 Accepted`
```json
{
  "task_id": "<celery_task_id>",
  "status": "pending",
  "document_id": "<uuid>"
}
```

#### Step 3.2 — Poll processing status until complete

```bash
# Poll every 5 seconds, up to 60 seconds
for i in $(seq 1 12); do
  echo "=== Poll attempt $i ==="
  STATUS_RESPONSE=$(curl -s "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/" \
    -H "Authorization: Bearer $ACCESS_TOKEN")
  echo "$STATUS_RESPONSE" | python -m json.tool
  
  STATUS=$(echo "$STATUS_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['status'])")
  
  if [ "$STATUS" = "completed" ]; then
    echo "✅ Processing completed!"
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "❌ Processing failed!"
    break
  fi
  
  sleep 5
done
```

**Expected (eventually):** `200 OK` with:
```json
{
  "document_id": "<uuid>",
  "status": "completed",
  "progress": 100,
  "tasks": [
    {
      "task_type": "extract",
      "status": "completed",
      "progress": 100,
      "error_message": null
    },
    {
      "task_type": "chunk",
      "status": "completed",
      "progress": 100,
      "error_message": null
    }
  ]
}
```

**What to verify:**
- Both `extract` and `chunk` tasks show `status: "completed"`
- Overall `progress` is `100`
- `error_message` is `null` for both tasks

#### Step 3.3 — Check document metadata after processing

> **⚠️ Note:** There is currently **no `GET /documents/{id}/` detail endpoint** implemented in the codebase. The [`documents/urls.py`](src/backend/documents/urls.py) only defines sub-routes like `.../process/`, `.../chunks/`, etc., but no bare `/<uuid:document_id>/` route, and there is no `DocumentDetailView` in [`documents/views.py`](src/backend/documents/views.py).
>
> To verify document metadata after processing, use the **processing-status endpoint** instead (which returns `document_id`, `status`, `progress`, and task details), or check the **chunks list** to confirm chunks were created.

```bash
# Option A: Use processing-status to verify document state
curl -s "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
```

**Expected:** `200 OK` with:
- `status`: `"completed"`
- `progress`: `100`
- `tasks`: array with both `extract` and `chunk` tasks showing `status: "completed"`

```bash
# Option B: Check chunks count to verify processing produced output
curl -s "http://localhost:8000/documents/$DOCUMENT_ID/chunks/?page_size=1" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Total chunks: {d[\"count\"]}')"
```

**Expected:** `Total chunks: <number > 0>`

#### Step 3.4 — View the chunks

```bash
curl -s "http://localhost:8000/documents/$DOCUMENT_ID/chunks/?page_size=5" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
```

**Expected:** `200 OK` with paginated chunk list:
```json
{
  "count": <total_chunks>,
  "page": 1,
  "page_size": 5,
  "total_pages": <calculated>,
  "results": [
    {
      "id": "<uuid>",
      "chunk_index": 0,
      "page_start": 1,
      "page_end": <n>,
      "content": "...",
      "token_count": <int>,
      "metadata": {}
    }
  ]
}
```

**What to verify:**
- `count` > 0 (chunks were created)
- Each chunk has `content` (non-empty text)
- `page_start` and `page_end` are reasonable (within PDF page count)
- `chunk_index` starts at 0 and increments sequentially

---

### Phase 4: Embedding & Vector Storage (E05)

#### Step 4.1 — Trigger embedding

```bash
EMBED_RESPONSE=$(curl -s -X POST "http://localhost:8000/documents/$DOCUMENT_ID/embed/" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

echo "$EMBED_RESPONSE" | python -m json.tool

# Save the embed task ID
EMBED_TASK_ID=$(echo "$EMBED_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['task_id'])")
echo "EMBED_TASK_ID=$EMBED_TASK_ID"
```

**Expected Response:** `202 Accepted`
```json
{
  "task_id": "<uuid>",
  "task_type": "embed",
  "status": "pending",
  "document_id": "<uuid>",
  "total_chunks": <number>
}
```

**Verify:** `total_chunks` matches the chunk count from Step 3.4.

#### Step 4.2 — Poll embedding task status

```bash
# Poll via the task status endpoint
for i in $(seq 1 12); do
  echo "=== Poll attempt $i ==="
  TASK_RESPONSE=$(curl -s "http://localhost:8000/tasks/$EMBED_TASK_ID/" \
    -H "Authorization: Bearer $ACCESS_TOKEN")
  echo "$TASK_RESPONSE" | python -m json.tool
  
  TASK_STATUS=$(echo "$TASK_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['status'])")
  
  if [ "$TASK_STATUS" = "completed" ]; then
    echo "✅ Embedding completed!"
    break
  elif [ "$TASK_STATUS" = "failed" ]; then
    echo "❌ Embedding failed!"
    break
  fi
  
  sleep 5
done
```

**Expected (eventually):** `200 OK`
```json
{
  "id": "<uuid>",
  "document_id": "<uuid>",
  "task_type": "embed",
  "status": "completed",
  "progress": 100,
  "result": null,
  "error_message": null,
  "started_at": "...",
  "completed_at": "..."
}
```

**What to verify:**
- `status` transitions: `pending` → `running` → `completed`
- `progress` reaches `100`
- `error_message` is `null`
- `started_at` and `completed_at` are populated with valid timestamps

#### Step 4.3 — Verify processing status now includes embed task

```bash
curl -s "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
```

**Expected:** Three tasks now visible:
```json
{
  "tasks": [
    {"task_type": "extract", "status": "completed", ...},
    {"task_type": "chunk", "status": "completed", ...},
    {"task_type": "embed", "status": "completed", ...}
  ],
  "status": "completed",
  "progress": 100
}
```

---

### Phase 5: Semantic Search & Retrieval (E06)

#### Step 5.1 — Basic semantic search

```bash
curl -s -X POST "http://localhost:8000/documents/$DOCUMENT_ID/search/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "data analysis methods",
    "top_k": 5,
    "min_score": 0.0
  }' | python -m json.tool
```

**Expected Response:** `200 OK`
```json
{
  "results": [
    {
      "chunk_id": "<uuid>",
      "chunk_index": <int>,
      "page_start": <int>,
      "page_end": <int>,
      "content": "...",
      "relevance_score": 0.85,
      "token_count": <int>,
      "metadata": {}
    }
  ],
  "query": "data analysis methods",
  "top_k": 5,
  "min_score": 0.0,
  "total_results": <int>
}
```

**What to verify:**
- `total_results` > 0 (at least one relevant chunk found)
- Results are ordered by `relevance_score` descending
- `relevance_score` values are between 0 and 1
- Content is semantically related to "data analysis methods"

#### Step 5.2 — Search with relevance threshold

```bash
curl -s -X POST "http://localhost:8000/documents/$DOCUMENT_ID/search/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "data analysis methods",
    "top_k": 10,
    "min_score": 0.75
  }' | python -m json.tool
```

**Expected:**
- Only chunks with `relevance_score >= 0.75` are returned
- `total_results` ≤ `top_k` (10)
- All results have `relevance_score >= 0.75`

#### Step 5.3 — Search with different query (specific topic)

```bash
curl -s -X POST "http://localhost:8000/documents/$DOCUMENT_ID/search/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "regression analysis",
    "top_k": 3,
    "min_score": 0.0
  }' | python -m json.tool
```

**Expected:**
- Results are relevant to "regression analysis"
- Different results from Step 5.1 (different semantic query)
- `total_results` may be fewer than 5 if the PDF has limited content on this topic

#### Step 5.4 — Search with empty/nonsense query (edge case)

```bash
curl -s -X POST "http://localhost:8000/documents/$DOCUMENT_ID/search/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "xyzzy nonsense query that should not match anything specific",
    "top_k": 5,
    "min_score": 0.0
  }' | python -m json.tool
```

**Expected:**
- `total_results` may be 0 or very few
- If results exist, `relevance_score` should be low (< 0.5)

---

### Phase 6: Conversation & Q&A Engine (E07)

#### Step 6.1 — Direct query (stateless RAG)

```bash
curl -s -X POST "http://localhost:8000/documents/$DOCUMENT_ID/query/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is this document about? Summarize the main topics.",
    "top_k": 5
  }' | python -m json.tool
```

**Expected Response:** `200 OK`
```json
{
  "answer": "This document discusses... [detailed summary]",
  "sources": [
    {
      "chunk_id": "<uuid>",
      "page_start": <int>,
      "page_end": <int>,
      "content_preview": "...",
      "relevance_score": 0.92
    }
  ],
  "token_usage": {
    "prompt_tokens": <int>,
    "completion_tokens": <int>,
    "total_tokens": <int>
  }
}
```

**What to verify:**
- `answer` is a coherent, relevant summary (not gibberish)
- `sources` array is non-empty with valid chunk references
- Each source has `relevance_score` > 0
- `token_usage` shows reasonable token counts
- The answer is grounded in the document content (not hallucinated)

#### Step 6.2 — Create a conversation

```bash
CONV_RESPONSE=$(curl -s -X POST "http://localhost:8000/conversations/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"document_id\": \"$DOCUMENT_ID\",
    \"title\": \"Data Analysis Q&A\"
  }")

echo "$CONV_RESPONSE" | python -m json.tool

# Save conversation ID
CONVERSATION_ID=$(echo "$CONV_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "CONVERSATION_ID=$CONVERSATION_ID"
```

**Expected Response:** `201 Created`
```json
{
  "id": "<uuid>",
  "document_id": "<uuid>",
  "title": "Data Analysis Q&A",
  "created_at": "...",
  "updated_at": "...",
  "messages": []
}
```

#### Step 6.3 — Ask a question in the conversation

```bash
curl -s -X POST "http://localhost:8000/conversations/$CONVERSATION_ID/messages/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "What statistical methods are discussed in this document?"
  }' | python -m json.tool
```

**Expected Response:** `201 Created`
```json
{
  "id": "<uuid>",
  "role": "assistant",
  "content": "The document discusses several statistical methods including...",
  "sources": [
    {
      "chunk_id": "<uuid>",
      "page_start": <int>,
      "page_end": <int>,
      "content_preview": "...",
      "relevance_score": 0.91
    }
  ],
  "token_usage": {
    "prompt_tokens": <int>,
    "completion_tokens": <int>,
    "total_tokens": <int>
  },
  "created_at": "..."
}
```

**What to verify:**
- `role` is `"assistant"`
- `content` is a meaningful answer about statistical methods
- `sources` are populated with relevant chunks
- Citations are present (content_preview matches parts of the answer)

#### Step 6.4 — Ask a follow-up question (context awareness)

```bash
curl -s -X POST "http://localhost:8000/conversations/$CONVERSATION_ID/messages/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Can you explain how these methods are applied to real data?"
  }' | python -m json.tool
```

**Expected:**
- `201 Created`
- Answer should reference the previous context (statistical methods from Step 6.3)
- The model should understand this is a follow-up, not a new standalone question
- Sources may include different chunks than the first question

#### Step 6.5 — View conversation with full message history

```bash
curl -s "http://localhost:8000/conversations/$CONVERSATION_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
```

**Expected:** `200 OK`
```json
{
  "id": "<uuid>",
  "document_id": "<uuid>",
  "document_title": "Data Analysis Test Document",
  "title": "Data Analysis Q&A",
  "message_count": 4,
  "messages": [
    {"role": "user", "content": "What statistical methods...", ...},
    {"role": "assistant", "content": "...", "sources": [...], ...},
    {"role": "user", "content": "Can you explain how...", ...},
    {"role": "assistant", "content": "...", "sources": [...], ...}
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

**What to verify:**
- `message_count` is 4 (2 user + 2 assistant messages)
- Messages are in chronological order
- Each assistant message has `sources` and `token_usage`
- `updated_at` reflects the latest message time

#### Step 6.6 — List conversations

```bash
curl -s "http://localhost:8000/conversations/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
```

**Expected:** `200 OK` with paginated list:
```json
{
  "count": 1,
  "results": [
    {
      "id": "<uuid>",
      "document_id": "<uuid>",
      "document_title": "Data Analysis Test Document",
      "title": "Data Analysis Q&A",
      "message_count": 4,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

#### Step 6.7 — Ask a question that should trigger citation tracking

```bash
curl -s -X POST "http://localhost:8000/conversations/$CONVERSATION_ID/messages/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "What specific data or numbers are mentioned in the document?"
  }' | python -m json.tool
```

**Expected:**
- Answer should include specific numbers/statistics from the document
- Sources should reference the exact chunks containing those numbers
- This tests that the RAG chain is retrieving and citing specific content, not just generating generic text

---

### Phase 7: Error Handling & Edge Cases

#### Step 7.1 — Unauthenticated access

```bash
# Try to upload without token
curl -s -X POST http://localhost:8000/documents/upload/ \
  -F "file=@/c/Users/hadit/Desktop/DataAnalysis2 (2)-3.pdf" | python -m json.tool
```

**Expected:** `401 Unauthorized`
```json
{
  "detail": "Authentication credentials were not provided."
}
```

#### Step 7.2 — Access another user's document (cross-user permission check)

```bash
# Register a second user
USER2_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email": "user2@example.com", "password": "password456", "full_name": "User Two"}')
TOKEN2=$(echo "$USER2_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")

# Try to access the first user's processing-status with second user's token
curl -s "http://localhost:8000/documents/$DOCUMENT_ID/processing-status/" \
  -H "Authorization: Bearer $TOKEN2" | python -m json.tool
```

**Expected:** `403 Forbidden`
```json
{
  "error": "permission_denied",
  "message": "You do not have permission to view this document."
}
```

#### Step 7.3 — Search on non-existent document

```bash
curl -s -X POST "http://localhost:8000/documents/00000000-0000-0000-0000-000000000000/search/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 5, "min_score": 0.0}' | python -m json.tool
```

**Expected:** `404 Not Found`
```json
{
  "error": "not_found",
  "message": "Document not found"
}
```

#### Step 7.4 — Ask question with empty content

```bash
curl -s -X POST "http://localhost:8000/conversations/$CONVERSATION_ID/messages/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": ""}' | python -m json.tool
```

**Expected:** `400 Bad Request` with validation error.

#### Step 7.5 — Delete conversation

```bash
curl -s -X DELETE "http://localhost:8000/conversations/$CONVERSATION_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -w "\nHTTP Status: %{http_code}\n"
```

**Expected:** `204 No Content` (empty body).

#### Step 7.6 — Verify conversation deletion

```bash
curl -s "http://localhost:8000/conversations/$CONVERSATION_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool
```

**Expected:** `404 Not Found`
```json
{
  "error": "not_found",
  "message": "Conversation not found"
}
```

#### Step 7.7 — Token refresh

```bash
# Refresh the access token
REFRESH_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refreshToken\": \"$REFRESH_TOKEN\"}")

echo "$REFRESH_RESPONSE" | python -m json.tool

# Save new tokens
NEW_ACCESS=$(echo "$REFRESH_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")
NEW_REFRESH=$(echo "$REFRESH_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['refreshToken'])")

# Verify old refresh token is revoked (should fail)
curl -s -X POST http://localhost:8000/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refreshToken\": \"$REFRESH_TOKEN\"}" | python -m json.tool
```

**Expected:**
- First call: `200 OK` with new `accessToken` and `refreshToken` (token rotation)
- Second call (with old token): `401 Unauthorized` (old token revoked)

---

## 4. Expected Results Summary

| # | Test Case | Epic | Expected HTTP Status | Key Verification |
|---|-----------|------|---------------------|------------------|
| 1.1 | Register | E02 | 201 | Tokens returned |
| 1.2 | Login | E02 | 200 | Valid JWT |
| 1.3 | Get profile | E02 | 200 | Correct user data |
| 2.1 | Upload PDF | E03 | 201 | Document ID returned |
| 3.1 | Trigger processing | E04 | 202 | Task ID returned |
| 3.2 | Poll processing status | E04 | 200 | Both tasks completed |
| 3.3 | Check doc metadata via processing-status | E04 | 200 | status=completed, progress=100 |
| 3.4 | View chunks | E04 | 200 | Non-empty chunk list |
| 4.1 | Trigger embedding | E05 | 202 | Task ID, total_chunks |
| 4.2 | Poll embed status | E05 | 200 | Progress 100% |
| 4.3 | Verify embed in status | E05 | 200 | 3 tasks visible |
| 5.1 | Basic search | E06 | 200 | Results with scores |
| 5.2 | Search with threshold | E06 | 200 | Filtered results |
| 5.3 | Different query | E06 | 200 | Different results |
| 5.4 | Nonsense query | E06 | 200 | Low/no results |
| 6.1 | Direct query | E07 | 200 | Coherent answer + sources |
| 6.2 | Create conversation | E07 | 201 | Conversation created |
| 6.3 | Ask question | E07 | 201 | Answer with citations |
| 6.4 | Follow-up question | E07 | 201 | Context-aware answer |
| 6.5 | View conversation | E07 | 200 | Full message history |
| 6.6 | List conversations | E07 | 200 | Paginated list |
| 6.7 | Citation tracking | E07 | 201 | Specific data cited |
| 7.1 | Unauthenticated | Error | 401 | Auth error |
| 7.2 | Wrong user access processing-status | Error | 403 | Permission denied |
| 7.3 | Non-existent doc | Error | 404 | Not found |
| 7.4 | Empty question | Error | 400 | Validation error |
| 7.5 | Delete conversation | E07 | 204 | No content |
| 7.6 | Verify deletion | E07 | 404 | Gone |
| 7.7 | Token refresh | E02 | 200/401 | Rotation works |

---

## 5. Troubleshooting

### 5.1 Celery tasks not executing

If processing status stays at `pending` for more than 30 seconds:

```bash
# Check celery worker logs
docker-compose logs celery_worker

# Check if Redis is reachable
docker-compose exec redis redis-cli ping
# Should return: PONG
```

### 5.2 Embedding fails

If embedding task fails:

```bash
# Check the task error message
curl -s "http://localhost:8000/tasks/$EMBED_TASK_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" | python -m json.tool

# Verify API key is set
docker-compose exec backend env | grep -E "(GOOGLE_API_KEY|OPENAI_API_KEY|EMBEDDING_PROVIDER)"
```

### 5.3 RAG query returns 502

```bash
# Check backend logs for the RAG error details
docker-compose logs backend --tail 50
```

### 5.4 Common curl errors on Windows/Git Bash

- **Path issues:** Use `/c/Users/...` instead of `C:\Users\...`
- **Variable expansion:** Use double quotes around variables: `"$ACCESS_TOKEN"`
- **JSON escaping:** Use single quotes for JSON body on Git Bash, or escape double quotes properly

### 5.5 Quick reset (clean test)

If you want to start fresh:

```bash
# Stop and remove volumes
docker-compose down -v

# Restart
docker-compose up -d

# Run migrations
docker-compose exec backend python manage.py migrate
```
