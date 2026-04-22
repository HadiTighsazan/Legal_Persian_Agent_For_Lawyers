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

### ⚠️ Partially Working Endpoints

#### GET /swagger/
**Description:** Swagger API documentation  
**Status:** Returns 500 Internal Server Error  
**Issue:** Django REST Framework documentation needs configuration

#### GET /redoc/
**Description:** ReDoc API documentation  
**Status:** Returns 500 Internal Server Error  
**Issue:** Django REST Framework documentation needs configuration

---

## Current Implementation Status (Epic E02)

### ✅ Implemented Endpoints

#### POST /auth/register
**Description:** Register new user account  
**Auth Required:** No  
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

---

#### POST /auth/login
**Description:** Login and get JWT tokens
**Auth Required:** No
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

---

#### POST /auth/refresh
**Description:** Refresh JWT access token
**Auth Required:** No
**Request Body:**
```json
{
  "refreshToken": "jwt_refresh_token"
}
```
**Response:** `200 OK`
```json
{
  "accessToken": "new_jwt_access_token"
}
```
**Error Responses:**
- `400 Bad Request`: Missing refresh token
- `401 Unauthorized`: Invalid, expired, or revoked refresh token
- `401 Unauthorized`: User account is inactive
- `500 Internal Server Error`: Unexpected server error

---

#### POST /auth/logout
**Description:** Logout and revoke a refresh token
**Auth Required:** Yes
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

## Planned Endpoints (Epic E02+)

### Authentication

#### GET /users/me
**Description:** Get current user profile
**Auth Required:** Yes
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "created_at": "2026-04-18T10:00:00Z",
  "stats": {
    "documents_count": 15,
    "conversations_count": 42,
    "total_storage_bytes": 524288000
  }
}
```

---

#### PATCH /users/me
**Description:** Update user profile
**Auth Required:** Yes
**Request Body:**
```json
{
  "full_name": "John Updated Doe"
}
```
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "John Updated Doe",
  "updated_at": "2026-04-18T11:00:00Z"
}
```

---

## Documents

#### POST /documents/upload
**Description:** Upload document file  
**Auth Required:** Yes  
**Content-Type:** `multipart/form-data`  
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

---

#### GET /documents/{document_id}
**Description:** Get document details  
**Auth Required:** Yes  
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

---

#### DELETE /documents/{document_id}
**Description:** Delete document and all related data  
**Auth Required:** Yes  
**Response:** `204 No Content`

---

#### POST /documents/{document_id}/process
**Description:** Start document processing (extract, chunk, embed)  
**Auth Required:** Yes  
**Response:** `202 Accepted`
```json
{
  "task_id": "uuid",
  "status": "pending",
  "message": "Processing started"
}
```

---

#### GET /documents/{document_id}/status
**Description:** Get document processing status  
**Auth Required:** Yes  
**Response:** `200 OK`
```json
{
  "document_id": "uuid",
  "status": "processing",
  "progress": 45,
  "tasks": [
    {
      "task_type": "extract",
      "status": "completed",
      "progress": 100
    },
    {
      "task_type": "chunk",
      "status": "running",
      "progress": 60
    },
    {
      "task_type": "embed",
      "status": "pending",
      "progress": 0
    }
  ]
}
```

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

#### DELETE /conversations/{conversation_id}
**Description:** Delete conversation and all messages  
**Auth Required:** Yes  
**Response:** `204 No Content`

---

## Messages / Q&A

#### POST /conversations/{conversation_id}/messages
**Description:** Ask question in conversation (RAG query)  
**Auth Required:** Yes  
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

---

#### POST /documents/{document_id}/query
**Description:** Direct query without conversation (stateless)  
**Auth Required:** Yes  
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

#### POST /documents/{document_id}/search
**Description:** Semantic search in document chunks  
**Auth Required:** Yes  
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
      "page_start": 120,
      "page_end": 122,
      "content": "Machine learning algorithms are...",
      "relevance_score": 0.93,
      "metadata": {}
    }
  ]
}
```

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

## User Profile

#### GET /users/me
**Description:** Get current user profile  
**Auth Required:** Yes  
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "created_at": "2026-04-18T10:00:00Z",
  "stats": {
    "documents_count": 15,
    "conversations_count": 42,
    "total_storage_bytes": 524288000
  }
}
```

---

#### PATCH /users/me
**Description:** Update user profile  
**Auth Required:** Yes  
**Request Body:**
```json
{
  "full_name": "John Updated Doe"
}
```
**Response:** `200 OK`
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "John Updated Doe",
  "updated_at": "2026-04-18T11:00:00Z"
}
```

---

## API Keys (Optional)

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
- Supported file types: PDF only (initial version)
- Current implementation (Epic E01) only has health endpoint working
- Swagger/ReDoc documentation endpoints return 500 (need configuration)