# API Registry

## Base URL
- Development: `http://localhost/api/` (via Nginx proxy)
- Direct Backend: `http://localhost:8000/` (for debugging)
- Production: `https://api.yourdomain.com/api/`

**Note:** Nginx routes `/api/` to Django backend. The backend doesn't have `/api/` prefix internally.

---

## Current Implementation Status (Epic E01)

### ✅ Implemented Endpoints

#### GET /api/health/
**Description:** Health check endpoint
**Auth Required:** No
**Response:** `200 OK`
```json
{
  "status": "ok",
  "timestamp": "2026-04-20T09:24:16.163298Z",
  "service": "docuchat-api",
  "version": "1.0.0"
}
```

#### GET /health/
**Description:** Nginx health check (simple text response)
**Auth Required:** No
**Response:** `200 OK` with "healthy"

#### GET /admin/
**Description:** Django admin interface
**Auth Required:** Yes (redirects to login)
**Response:** `302 Found` (redirects to login page)

---

## Current Implementation Status (Epic E02)

### ✅ Implemented Endpoints — Authentication & User Management

#### POST /auth/register
**Description:** Register new user account
**Auth Required:** No
**Implementation Date:** 2026-04-22
**Test Coverage:** 59 view tests, 6 middleware integration tests
**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword",
  "full_name": "John Doe"
}
```
**Response:** `201 Created`
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "full_name": "John Doe",
    "created_at": "2026-04-18T10:00:00Z",
    "is_active": true
  },
  "accessToken": "jwt_access_token",
  "refreshToken": "jwt_refresh_token"
}
```
**Error Responses:**
- `400 Bad Request`: Missing/invalid fields, weak password (< 8 chars)
- `409 Conflict`: Email already exists
- `500 Internal Server Error`: Unexpected server error

**Implementation Notes:**
- Uses `@authentication_classes([])` and `@permission_classes([AllowAny])` to allow unauthenticated access
- Validates input via `RegisterSerializer` (email uniqueness, password strength via Django validators)
- Creates user via `User.objects.create_user()`
- Generates JWT access + refresh token pair on successful registration
- Stores refresh token hash in `refresh_tokens` table
- Returns user data via `UserSerializer`

---

#### POST /auth/login
**Description:** Login and get JWT tokens
**Auth Required:** No
**Implementation Date:** 2026-04-22
**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword"
}
```
**Response:** `200 OK`
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "full_name": "John Doe",
    "created_at": "2026-04-18T10:00:00Z",
    "is_active": true
  },
  "accessToken": "jwt_access_token",
  "refreshToken": "jwt_refresh_token"
}
```
**Error Responses:**
- `400 Bad Request`: Missing/invalid fields, invalid email format, invalid JSON
- `401 Unauthorized`: Invalid credentials (wrong email or password)
- `401 Unauthorized`: User account is inactive
- `500 Internal Server Error`: Unexpected server error

**Implementation Notes:**
- Uses `@authentication_classes([])` and `@permission_classes([AllowAny])` to allow unauthenticated access
- Validates input via `LoginSerializer`
- Authenticates via email + password using `user.verify_password()`
- Generates new JWT access + refresh token pair on successful login
- Stores refresh token hash in `refresh_tokens` table
- Returns user data via `UserSerializer`

---

#### POST /auth/refresh
**Description:** Refresh JWT access token (with rotation)
**Auth Required:** No (requires valid refresh token in body)
**Implementation Date:** 2026-04-22 (updated 2026-04-25 with rotation)
**Request Body:**
```json
{
  "refreshToken": "jwt_refresh_token"
}
```
**Response:** `200 OK`
```json
{
  "accessToken": "new_jwt_access_token",
  "refreshToken": "new_jwt_refresh_token"
}
```
**Error Responses:**
- `400 Bad Request`: Missing refresh token
- `401 Unauthorized`: Invalid, expired, or revoked refresh token
- `401 Unauthorized`: User account is inactive
- `500 Internal Server Error`: Unexpected server error

**Implementation Notes:**
- Uses `@authentication_classes([])` and `@permission_classes([AllowAny])` to allow unauthenticated access
- Verifies refresh token JWT signature and payload via `verify_refresh_token()`
- Looks up token hash in `refresh_tokens` table to ensure it hasn't been revoked
- Validates token expiry and user active status
- **Refresh token rotation is now implemented**: the old refresh token is revoked (deleted from DB) and a new refresh token is generated and stored
- Returns both `accessToken` and `refreshToken` in the response
- Refresh token lifetime is read from `settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']`

---

#### POST /auth/logout
**Description:** Logout and revoke a refresh token
**Auth Required:** Yes (valid access token in Authorization header)
**Implementation Date:** 2026-04-22
**Request Body:**
```json
{
  "refreshToken": "jwt_refresh_token"
}
```
**Response:** `204 No Content` (empty body)

**Error Responses:**
- `400 Bad Request`: Missing refresh token
- `401 Unauthorized`: Invalid, expired, or revoked refresh token
- `401 Unauthorized`: Refresh token does not belong to authenticated user
- `500 Internal Server Error`: Unexpected server error

**Notes:**
- Requires valid access token in `Authorization: Bearer <token>` header
- Deletes the refresh token from database, preventing future use
- Access tokens remain valid until expiry (stateless JWT)
- Users can only revoke their own refresh tokens

---

#### GET /users/me
**Description:** Get current user profile
**Auth Required:** Yes
**Implementation Date:** 2026-04-22
**Test Coverage:** 5 unit tests
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "created_at": "2026-04-18T10:00:00Z",
  "updated_at": "2026-04-18T10:00:00Z"
}
```
**Error Responses:**
- `401 Unauthorized`: No valid authentication token provided
- `401 Unauthorized`: Token expired or invalid

**Example Usage:**
```bash
# Get user profile with valid token
curl -X GET http://localhost:8000/users/me/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# Response (unauthorized)
curl -X GET http://localhost:8000/users/me/
# Returns: {"detail": "Authentication credentials were not provided."}
```

**Implementation Notes:**
- Uses Django REST Framework's `IsAuthenticated` permission class
- Authentication is handled by DRF's `JWTAuthentication` (custom `JWTAuthenticationMiddleware` has been removed)
- Returns user data via `UserSerializer` (read-only ModelSerializer)
- Returns ISO 8601 formatted timestamps
- Follows consistent error response format
- Note: `stats` field is not yet implemented (planned for future enhancement)

---

#### PATCH /users/me
**Description:** Update current user profile (partial update)
**Auth Required:** Yes
**Implementation Date:** 2026-04-22
**Request Body:**
```json
{
  "full_name": "John Updated Doe",
  "email": "newemail@example.com"
}
```
Both fields are optional. At least one should be provided for meaningful updates.

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "email": "newemail@example.com",
  "full_name": "John Updated Doe",
  "is_active": true,
  "created_at": "2026-04-18T10:00:00Z",
  "updated_at": "2026-04-18T11:00:00Z"
}
```
**Error Responses:**
- `400 Bad Request`: Invalid email format, invalid JSON
- `401 Unauthorized`: No valid authentication token
- `409 Conflict`: Email already exists

**Notes:**
- Uses the same endpoint as GET `/users/me` but with PATCH HTTP method
- Only provided fields are updated (partial update)
- `updated_at` is automatically updated via model's `auto_now=True`
- Uses `ProfileUpdateSerializer` for validation
- Returns user data via `UserSerializer`

---

### ✅ Implemented Endpoints — API Documentation

#### GET /swagger/
**Description:** Swagger UI API documentation
**Auth Required:** No
**Status:** ✅ Working
**Implementation Date:** 2026-04-23
**Configuration:** `drf_yasg` with OpenAPI schema view in `config/urls.py`

#### GET /redoc/
**Description:** ReDoc API documentation
**Auth Required:** No
**Status:** ✅ Working
**Implementation Date:** 2026-04-23
**Configuration:** `drf_yasg` with OpenAPI schema view in `config/urls.py`

---

## Documents

### ✅ Implemented Endpoints — Document CRUD & Processing

#### POST /documents/upload
**Description:** Upload document file
**Auth Required:** Yes
**Content-Type:** `multipart/form-data`
**Status:** ✅ Implemented
**Implementation Date:** 2026-04-24
**View Class:** `DocumentUploadView`
**Request Body:**
- `file`: File (PDF, max 500MB)
- `title`: String (optional)

**Response:** `201 Created`
```json
{
  "id": "uuid",
  "title": "Document Title",
  "original_filename": "file.pdf",
  "file_size": 104857600,
  "total_pages": null,
  "status": "uploaded",
  "created_at": "2026-04-18T10:00:00Z"
}
```

---

#### GET /documents
**Description:** List user's documents
**Auth Required:** Yes
**Status:** ✅ Implemented
**Implementation Date:** 2026-05-03
**View Class:** `DocumentListView`
**Query Parameters:**
- `page`: Integer (default: 1)
- `page_size`: Integer (default: 20, max: 100)
- `status`: String (uploaded, processing, completed, failed)
- `search`: String (search in title)

**Response:** `200 OK`
```json
{
  "count": 50,
  "next": "url_to_next_page",
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "title": "Document Title",
      "original_filename": "file.pdf",
      "file_size": 104857600,
      "total_pages": 2000,
      "status": "completed",
      "created_at": "2026-04-18T10:00:00Z",
      "updated_at": "2026-04-18T10:30:00Z"
    }
  ]
}
```

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Filters by `Document.objects.filter(user=request.user)`
- Supports `title__icontains` search and `status` exact filter
- Paginates via Django's `Paginator` with clamped `page` (min 1) and `page_size` (1–100)
- Returns `count`, `next`, `previous`, `results` in standard paginated format
- Results ordered by `-created_at` (newest first)
- URL registered at `""` (root of documents app) with name `document-list`
- **Important:** The empty path `""` must be placed **before** `upload/` in `urlpatterns` to avoid Django catching `upload` as a UUID

---

#### GET /documents/{document_id}
**Description:** Get document details
**Auth Required:** Yes
**Status:** ✅ Implemented
**Implementation Date:** 2026-05-03
**View Class:** `DocumentDetailView`
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "title": "Document Title",
  "original_filename": "file.pdf",
  "file_size": 104857600,
  "mime_type": "application/pdf",
  "total_pages": 2000,
  "status": "completed",
  "error_message": null,
  "created_at": "2026-04-18T10:00:00Z",
  "updated_at": "2026-04-18T10:30:00Z",
  "chunks_count": 500
}
```
**Error Responses:**
- `403 Forbidden`: Document belongs to another user
- `404 Not Found`: Document does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies document ownership via `document.user != request.user`
- Returns full document details including `mime_type`, `processing_status`, `error_message`, `chunks_count` (mapped from `total_chunks`)
- URL registered at `"<uuid:document_id>/"` with name `document-detail`
- **Important:** Route placed after `upload/` but before sub-routes like `process/` to avoid conflicts

---

#### DELETE /documents/{document_id}
**Description:** Delete document and all related data
**Auth Required:** Yes
**Status:** ✅ Implemented
**Implementation Date:** 2026-05-03
**View Class:** `DocumentDetailView`
**Response:** `204 No Content`
**Error Responses:**
- `403 Forbidden`: Document belongs to another user
- `404 Not Found`: Document does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies document ownership via `document.user != request.user`
- Calls `document.delete()` which cascades to related chunks, processing tasks, and conversations
- Returns `204 No Content` on success

---

#### POST /documents/processing-tasks/{task_id}/retry/
**Description:** Retry a failed processing task
**Auth Required:** Yes
**View:** `ProcessingTaskRetryView`
**Response:** `200 OK`
```json
{
  "task_id": "new_celery_task_id",
  "status": "pending",
  "retry_count": 1,
  "document_id": "uuid"
}
```
**Error Responses:**
- `400 Bad Request`: Task is not in a failed state
- `400 Bad Request`: Maximum retry limit (3) exceeded
- `403 Forbidden`: Task belongs to another user
- `404 Not Found`: Processing task does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies task ownership via `task.document.user != request.user`
- Checks task is in `'failed'` state before allowing retry
- Enforces maximum of 3 retries (`retry_count < 3`)
- Increments `retry_count`, resets `status` to `'pending'`, clears `error_message` and `completed_at`
- Calls `process_document(document_id)` to re-trigger the Celery chain
- Updates `celery_task_id` with the new task ID from `process_document`
- Reuses the existing failed `ProcessingTask` record (does not create a new one)

---

#### POST /documents/{document_id}/process/
**Description:** Start document processing pipeline (extract → chunk → embed)
**Auth Required:** Yes
**Implementation Date:** 2026-04-24 (updated 2026-05-04: added auto-embedding)
**View:** `DocumentProcessView`
**Response:** `202 Accepted`
```json
{
  "task_id": "celery_task_id",
  "status": "pending",
  "document_id": "uuid"
}
```
**Error Responses:**
- `400 Bad Request`: Document is already being processed
- `403 Forbidden`: Document belongs to another user
- `404 Not Found`: Document does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies document ownership via `document.user != request.user`
- Prevents duplicate processing if `processing_status in ("processing", "completed")`
- Calls `process_document(document_id)` directly (regular Python function, not a Celery task)
- The Celery chain now includes 3 steps: `extract_text_from_pdf → chunk_document → embed_document`
- Embeddings are automatically generated for all chunks after chunking completes
- Returns `202 Accepted` with Celery chain task ID
- Error responses follow standard format: `{"error": "error_code", "message": "..."}`

---

#### GET /documents/{document_id}/processing-status/
**Description:** Get document processing status with per-task details
**Auth Required:** Yes
**Implementation Date:** 2026-04-24
**View:** `DocumentProcessingStatusView`
**Response:** `200 OK`
```json
{
  "document_id": "uuid",
  "status": "processing",
  "progress": 33,
  "tasks": [
    {
      "task_type": "extract",
      "status": "completed",
      "progress": 100,
      "error_message": null
    },
    {
      "task_type": "chunk",
      "status": "running",
      "progress": 60,
      "error_message": null
    },
    {
      "task_type": "embed",
      "status": "pending",
      "progress": 0,
      "error_message": null
    }
  ]
}
```
**Error Responses:**
- `403 Forbidden`: Document belongs to another user
- `404 Not Found`: Document does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies document ownership
- Queries `ProcessingTask.objects.filter(document=document).order_by("created_at")`
- The pipeline now includes 3 tasks: `extract`, `chunk`, and `embed`
- Per-task progress: completed=100, failed=0, running=task.progress, pending=0
- Overall progress: average of all task progress values (0 if no tasks)
- Uses `ProcessingStatusSerializer` for response validation

---

#### GET /documents/{document_id}/chunks/
**Description:** Retrieve paginated chunks for a given document
**Auth Required:** Yes
**Query Parameters:**
- `page`: Integer (default: 1)
- `page_size`: Integer (default: 20)

**Response:** `200 OK`
```json
{
  "count": 5,
  "page": 1,
  "page_size": 20,
  "total_pages": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "chunk_index": 0,
      "page_start": 1,
      "page_end": 5,
      "content": "Chunk text content...",
      "token_count": 50,
      "metadata": {}
    }
  ]
}
```
**Error Responses:**
- `403 Forbidden`: Document belongs to another user
- `404 Not Found`: Document does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies document ownership
- Queries `DocumentChunk.objects.filter(document=document).order_by("chunk_index")`
- Manual pagination via slice-based `[start:end]` on the queryset
- Returns `count`, `page`, `page_size`, `total_pages`, `next`, `previous`, `results`
- Uses `DocumentChunkSerializer` for response serialization

---

### ✅ Implemented Endpoints — Embedding Views (Epic E-05, Task 4)

#### POST /documents/{document_id}/embed/
**Description:** Trigger embedding for all un-embedded chunks of a document
**Auth Required:** Yes
**View:** `DocumentEmbedView`
**Response:** `202 Accepted`
```json
{
  "task_id": "uuid",
  "task_type": "embed",
  "status": "pending",
  "document_id": "uuid",
  "total_chunks": 5
}
```
**Error Responses:**
- `403 Forbidden`: Document belongs to another user
- `404 Not Found`: Document does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies document ownership via `document.user != request.user`
- Counts un-embedded chunks via `DocumentChunk.objects.filter(document=document, embedding__isnull=True).count()`
- Creates a `ProcessingTask` with `task_type='embed'` and `status='pending'`
- Dispatches `embed_document.delay(str(document.id), str(processing_task.id))` Celery task
- Uses `DocumentEmbedResponseSerializer` for response validation

---

#### POST /chunks/batch-embed/
**Description:** Embed a batch of chunks by their IDs
**Auth Required:** Yes
**View:** `ChunkBatchEmbedView`
**Request Body:**
```json
{
  "chunk_ids": ["<uuid>", "<uuid>"]
}
```
**Response:** `200 OK`
```json
{
  "processed": 3,
  "skipped": 1,
  "failed": 0
}
```
**Error Responses:**
- `400 Bad Request`: Invalid chunk_ids
- `403 Forbidden`: One or more chunks belong to another user's document

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Validates request body with `ChunkBatchEmbedRequestSerializer`
- Filters chunks by `document__user=request.user` to enforce ownership
- Calls `batch_embed_chunks(chunk_ids)` from the embedding service
- Uses `ChunkBatchEmbedResponseSerializer` for response validation

---

#### POST /chunks/{chunk_id}/re-embed/
**Description:** Re-embed a single chunk by regenerating its embedding
**Auth Required:** Yes
**View:** `ChunkReEmbedView`
**Response:** `200 OK`
```json
{
  "chunk_id": "uuid",
  "embedding_updated": true
}
```
**Error Responses:**
- `403 Forbidden`: Chunk belongs to another user's document
- `404 Not Found`: Chunk does not exist
- `500 Internal Server Error`: Embedding generation failed
  ```json
  {
    "error": "embedding_failed",
    "message": "Failed to generate embedding for chunk <chunk_id>"
  }
  ```

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies chunk ownership via `chunk.document.user != request.user`
- Calls `reembed_chunk(str(chunk.id))` from the embedding service
- Catches `EmbeddingError` and returns 500 with structured error response
- Uses `ChunkReEmbedResponseSerializer` for response validation

---

#### GET /tasks/{task_id}/
**Description:** Retrieve the status of a processing task
**Auth Required:** Yes
**View:** `TaskStatusView`
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "document_id": "uuid",
  "task_type": "embed",
  "status": "running",
  "progress": 75,
  "result": null,
  "error_message": null,
  "started_at": "2026-04-18T10:00:00Z",
  "completed_at": null
}
```
**Error Responses:**
- `403 Forbidden`: Task belongs to another user
- `404 Not Found`: Task does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies task ownership via `task.document.user != request.user`
- Returns all task fields including `id`, `document_id`, `task_type`, `status`, `progress`, `result`, `error_message`, `started_at`, `completed_at`
- Timestamps are ISO 8601 formatted

---

## Conversations

#### POST /conversations
**Description:** Create new conversation for a document  
**Auth Required:** Yes  
**Request Body:**
```json
{
  "document_id": "uuid",
  "title": "Questions about Chapter 5"
}
```
**Response:** `201 Created`
```json
{
  "id": "uuid",
  "document_id": "uuid",
  "title": "Questions about Chapter 5",
  "created_at": "2026-04-18T10:00:00Z",
  "updated_at": "2026-04-18T10:00:00Z"
}
```

---

#### GET /conversations
**Description:** List user's conversations  
**Auth Required:** Yes  
**Query Parameters:**
- `page`: Integer (default: 1)
- `page_size`: Integer (default: 20)
- `document_id`: UUID (filter by document)

**Response:** `200 OK`
```json
{
  "count": 10,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "document_id": "uuid",
      "document_title": "Document Title",
      "title": "Questions about Chapter 5",
      "message_count": 8,
      "created_at": "2026-04-18T10:00:00Z",
      "updated_at": "2026-04-18T11:00:00Z"
    }
  ]
}
```

---

#### GET /conversations/{conversation_id}
**Description:** Get conversation details with messages  
**Auth Required:** Yes  
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "document_id": "uuid",
  "document_title": "Document Title",
  "title": "Questions about Chapter 5",
  "created_at": "2026-04-18T10:00:00Z",
  "updated_at": "2026-04-18T11:00:00Z",
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "What is discussed in chapter 5?",
      "created_at": "2026-04-18T10:05:00Z"
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "Chapter 5 discusses...",
      "sources": [
        {
          "chunk_id": "uuid",
          "page_start": 45,
          "page_end": 47,
          "relevance_score": 0.92
        }
      ],
      "created_at": "2026-04-18T10:05:15Z"
    }
  ]
}
```

---

#### PATCH /conversations/{conversation_id}
**Description:** Rename conversation (update title)
**Auth Required:** Yes
**View Class:** `ConversationDetailView.patch()`
**Implementation Date:** 2026-05-04 (Deep Refactor — Issue 2)
**Request Body:**
```json
{
  "title": "New Conversation Title"
}
```
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "document_id": "uuid",
  "document_title": "Document Title",
  "title": "New Conversation Title",
  "message_count": 8,
  "created_at": "2026-04-18T10:00:00Z",
  "updated_at": "2026-04-18T11:00:00Z"
}
```
**Error Responses:**
- `400 Bad Request`: Title is empty or invalid
- `403 Forbidden`: Conversation belongs to another user
- `404 Not Found`: Conversation does not exist

**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies conversation ownership (403 if wrong user, 404 if not found)
- Validates that `title` is a non-empty string
- Returns the updated conversation via `ConversationListSerializer`

---

#### DELETE /conversations/{conversation_id}
**Description:** Delete conversation and all messages
**Auth Required:** Yes
**Response:** `204 No Content`

---

## Messages / Q&A

### ✅ Implemented Endpoints

#### POST /conversations/{conversation_id}/messages/
**Description:** Ask question in conversation (RAG query)
**Auth Required:** Yes
**Implementation Date:** 2026-04-28
**View Class:** `ConversationMessageView`
**Test Coverage:** 11 tests (10 unit + 1 integration) in `ConversationMessageViewTests`
**Status:** ✅ Implemented
**Implementation Notes:**
- Uses `IsAuthenticated` permission class
- Verifies conversation ownership (403 if wrong user, 404 if not found)
- Validates input with `AskQuestionSerializer` (content required, 1–10,000 chars)
- Persists user message **before** calling RAG service
- Builds conversation history from all messages ordered by `created_at`
- Calls `run_rag_query(question, document_id, conversation_history, top_k=5)`
- Persists assistant message with `sources` and `token_usage` from RAG result
- Touches `conversation.updated_at` via `conversation.save()`
- Returns `201 Created` with `MessageSerializer` of the assistant message
- `RAGServiceException` → `502 Bad Gateway` with `{"error": "rag_error", ...}`
- OpenAI rate limit errors → `429 Too Many Requests` with `{"error": "rate_limit_exceeded", "retry_after": 60}`
- URL registered at `conversations/<uuid:conversation_id>/messages/` with name `conversation-messages`

**Request Body:**
```json
{
  "content": "What is the main conclusion of the study?"
}
```

**Response:** `201 Created`
```json
{
  "id": "uuid",
  "role": "assistant",
  "content": "The main conclusion is...",
  "sources": [
    {
      "chunk_id": "uuid",
      "page_start": 1950,
      "page_end": 1952,
      "content_preview": "In conclusion, we found that...",
      "relevance_score": 0.95
    }
  ],
  "token_usage": {
    "prompt_tokens": 3500,
    "completion_tokens": 250,
    "total_tokens": 3750
  },
  "created_at": "2026-04-18T10:10:00Z"
}
```

**Error Responses:**
- `400 Bad Request` — Validation error (empty content, etc.)
- `401 Unauthorized` — Missing or invalid authentication
- `403 Forbidden` — Conversation belongs to another user
- `404 Not Found` — Conversation does not exist
- `429 Too Many Requests` — OpenAI API rate limit exceeded
- `502 Bad Gateway` — RAG service error

---

#### POST /documents/{document_id}/query
**Description:** Direct query without conversation (stateless)
**Auth Required:** Yes
**Status:** ✅ Implemented
**Implementation Date:** 2026-04-28
**View Class:** `DocumentDirectQueryView`
**Test Coverage:** 11 tests in `DocumentDirectQueryViewTests`
**Implementation Notes:** Stateless RAG query endpoint. Fetches document with ownership check (404/403), validates `document.status == 'completed'` (422) — uses the authoritative upload lifecycle field, not `processing_status`, validates input with `DirectQuerySerializer`, calls `run_rag_query` with `conversation_history=[]`, and returns `answer`, `sources`, `token_usage` without persisting any `Message` or `Conversation` objects. `RAGServiceException` → 502, rate limit → 429 with `retry_after: 60`.
**Request Body:**
```json
{
  "question": "What is the main conclusion?",
  "top_k": 5
}
```
**Response:** `200 OK`
```json
{
  "answer": "The main conclusion is...",
  "sources": [
    {
      "chunk_id": "uuid",
      "page_start": 1950,
      "page_end": 1952,
      "content_preview": "In conclusion, we found that...",
      "relevance_score": 0.95
    }
  ],
  "token_usage": {
    "prompt_tokens": 3500,
    "completion_tokens": 250,
    "total_tokens": 3750
  }
}
```

---

## Search & Retrieval

#### POST /documents/{document_id}/search/
**Description:** Semantic search in document chunks
**Auth Required:** Yes
**Implementation Date:** 2026-04-27
**Test Coverage:** 7 view tests + 1 integration test (DocumentSearchViewTests + DocumentSearchIntegrationTest)
**View Class:** `DocumentSearchView`
**Status:** ✅ Implemented
**Implementation Notes:** Uses `embed_query()` from the embedding service to vectorize the search query, then `search_chunks()` from the search service to perform cosine similarity search via pgvector's `<=>` operator. Results are ordered by relevance_score descending. The `ivfflat.probes` session parameter is set before each query for performance tuning.
**Request Body:**
```json
{
  "query": "machine learning algorithms",
  "top_k": 10,
  "min_score": 0.7
}
```
**Response:** `200 OK`
```json
{
  "results": [
    {
      "chunk_id": "uuid",
      "chunk_index": 0,
      "page_start": 120,
      "page_end": 122,
      "content": "Machine learning algorithms are...",
      "relevance_score": 0.93,
      "token_count": 150,
      "metadata": {}
    }
  ],
  "query": "machine learning algorithms",
  "top_k": 10,
  "min_score": 0.7,
  "total_results": 1
}
```
**Error Responses:**
- `400 Bad Request` — Invalid request body (DRF validation)
- `403 Forbidden` — Document belongs to another user
- `404 Not Found` — Document does not exist
- `422 Unprocessable Entity` — Document processing is not complete
- `500 Internal Server Error` — Embedding generation failed

---

## Tasks & Processing

#### GET /tasks/{task_id}
**Description:** Get processing task status  
**Auth Required:** Yes  
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "document_id": "uuid",
  "task_type": "embed",
  "status": "running",
  "progress": 75,
  "result": null,
  "error_message": null,
  "started_at": "2026-04-18T10:00:00Z",
  "completed_at": null
}
```

---

#### POST /tasks/{task_id}/cancel
**Description:** Cancel running task  
**Auth Required:** Yes  
**Response:** `200 OK`
```json
{
  "message": "Task cancellation requested",
  "status": "cancelling"
}
```

---

## API Keys (Optional - Planned)

#### GET /api-keys
**Description:** List user's API keys  
**Auth Required:** Yes  
**Response:** `200 OK`
```json
{
  "results": [
    {
      "id": "uuid",
      "name": "Production Key",
      "is_active": true,
      "last_used_at": "2026-04-18T09:00:00Z",
      "created_at": "2026-04-01T10:00:00Z",
      "expires_at": null
    }
  ]
}
```

---

#### POST /api-keys
**Description:** Create new API key  
**Auth Required:** Yes  
**Request Body:**
```json
{
  "name": "My App Key",
  "expires_at": "2027-04-18T00:00:00Z"
}
```
**Response:** `201 Created`
```json
{
  "id": "uuid",
  "name": "My App Key",
  "key": "sk_live_xxxxxxxxxxxxxxxx",
  "created_at": "2026-04-18T10:00:00Z",
  "expires_at": "2027-04-18T00:00:00Z",
  "warning": "Save this key now. It won't be shown again."
}
```

---

#### DELETE /api-keys/{key_id}
**Description:** Revoke API key  
**Auth Required:** Yes  
**Response:** `204 No Content`

---

## Error Responses

All endpoints may return these error formats:

**400 Bad Request**
```json
{
  "error": "validation_error",
  "message": "Invalid request data",
  "details": {
    "field_name": ["Error message"]
  }
}
```

**401 Unauthorized**
```json
{
  "error": "authentication_failed",
  "message": "Invalid or expired token"
}
```

**403 Forbidden**
```json
{
  "error": "permission_denied",
  "message": "You don't have permission to access this resource"
}
```

**404 Not Found**
```json
{
  "error": "not_found",
  "message": "Resource not found"
}
```

**429 Too Many Requests**
```json
{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please try again later.",
  "retry_after": 60
}
```

**500 Internal Server Error**
```json
{
  "error": "internal_error",
  "message": "An unexpected error occurred"
}
```

---

## Rate Limiting

- Authenticated users: 1000 requests/hour
- Anonymous users: 100 requests/hour
- Document upload: 10 uploads/hour per user
- Query endpoints: 100 queries/hour per user

---

## Notes

- All timestamps in ISO 8601 format (UTC)
- All IDs are UUIDs
- Pagination uses `page` and `page_size` parameters
- Authentication via JWT in `Authorization: Bearer <token>` header
- File uploads limited to 500MB per file

## Configuration Changes (E04-T4-T5 Bug Fixes — 2026-04-25)

### Middleware
- **Removed:** `users.middleware.JWTAuthenticationMiddleware` from `MIDDLEWARE` in settings.py
- **Replaced by:** DRF's built-in `JWTAuthentication` in `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`
- The middleware file (`src/backend/users/middleware.py`) is preserved with a deprecation warning for reference

### Authentication Error Format
- With DRF's `JWTAuthentication`, unauthorized responses return `{"detail": "..."}` instead of the old middleware's `{"error": "...", "message": "..."}` format
- This affects all protected endpoints when no valid token is provided

### Token Blacklist
- **Removed:** `rest_framework_simplejwt.token_blacklist` from `INSTALLED_APPS`
- Token revocation is handled entirely via the custom `RefreshToken` model (in `refresh_tokens` table)
- `is_token_blacklisted()` in `jwt_utils.py` now always returns `False` (revocation is checked via DB lookup)

### URL Configuration
- **Removed:** Duplicate `path('users/', include('users.urls'))` from `config/urls.py`
- **Added:** Direct `path('users/me/', users_views.profile_view, name='users-profile')` for the profile endpoint
- The `/users/me/` endpoint is now explicitly defined in the root URL configuration
- Supported file types: PDF only (initial version)
- Epic E01 (Health & Infrastructure): Health endpoints implemented and working
- Epic E02 (Authentication & User Management): All auth endpoints implemented and working
- Swagger/ReDoc documentation endpoints are configured and working via `drf_yasg`