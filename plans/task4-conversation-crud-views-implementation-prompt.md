# Task 4 — Conversation CRUD Views: Implementation Prompt for Code Mode

## Overview

Implement the Conversation CRUD views (POST + GET `/conversations`, GET + DELETE `/conversations/{conversation_id}`) as specified in Epic E07, Task 4 of the PRD. This task covers only CRUD — no RAG logic.

---

## Files to Create / Modify

| Action | File | Purpose |
|--------|------|---------|
| **CREATE** | `src/backend/conversations/views.py` | Two view classes: `ConversationListCreateView`, `ConversationDetailView` |
| **CREATE** | `src/backend/conversations/urls.py` | URL patterns for the conversations app |
| **MODIFY** | `src/backend/config/urls.py` | Register `conversations/` URL include |
| **CREATE** | `src/backend/conversations/tests/test_views.py` | Test file for all CRUD operations |

---

## Implementation Details

### 1. `src/backend/conversations/views.py` — View Classes

Follow the exact patterns established in [`src/backend/documents/views.py`](src/backend/documents/views.py):
- Use `APIView` from DRF (not ViewSet)
- Use `IsAuthenticated` permission class
- Use `Request` type hints from DRF
- Use `Response` from DRF
- Use `status` module constants for HTTP status codes
- Error responses follow the format: `{"error": "error_code", "message": "..."}`

#### 1a. `ConversationListCreateView` — POST + GET `/conversations`

**POST method:**
- Permission: `IsAuthenticated`
- Validate input with [`ConversationCreateSerializer`](src/backend/conversations/serializers.py:138) — pass `context={"request": request}` so the serializer can access `request.user` for ownership validation
- The serializer's `validate_document_id()` already handles:
  - Document not found → raises `ValidationError("Document does not exist.")` → DRF returns **400**
  - Document belongs to another user → raises `ValidationError("Document does not belong to you.")` → DRF returns **400**
  - Document not completed → raises `ValidationError("Document processing is not complete.")` → DRF returns **400**
- **IMPORTANT:** The PRD says return 404/403/422 for these errors, but the serializer raises `ValidationError` which DRF converts to **400**. The serializer was already implemented in Task 2 and tested. **Do NOT change the serializer behavior.** The acceptance criteria focus on the CRUD operations working correctly. If the serializer returns 400, that's acceptable — the test should verify the error message content, not the HTTP status code for these specific validation errors. However, to match the PRD spec more closely, you can catch `ValidationError` from the serializer and re-map to appropriate status codes:
  - "Document does not exist" → 404
  - "Document does not belong to you" → 403
  - "Document processing is not complete" → 422
- Create `Conversation` object: `Conversation.objects.create(user=request.user, document=validated_data['document_id'], title=validated_data.get('title', ''))`
  - Note: `ConversationCreateSerializer.validate_document_id()` returns the `Document` instance, so `validated_data['document_id']` is a `Document` object
- Return `201 Created` with `ConversationDetailSerializer(conversation).data`
  - The conversation will have no messages yet (empty list)

**GET method:**
- Permission: `IsAuthenticated`
- Base queryset: `Conversation.objects.filter(user=request.user)`
- Optional filter: if `request.query_params.get('document_id')` is provided, filter by `document_id=document_id`
- Annotate with `message_count=Count('messages', distinct=True)`
- Order by `-updated_at` (most recent first)
- Pagination:
  - Parse `page` (default 1) and `page_size` (default 20, max 100) from query params
  - Manual slicing: `start = (page - 1) * page_size`, `end = start + page_size`
  - Total count: `queryset.count()`
  - Slice: `conversations = queryset[start:end]`
- Serialize with `ConversationListSerializer(conversations, many=True)`
- Return paginated response:
  ```python
  {
      "count": total,
      "next": page + 1 if page < total_pages else None,
      "previous": page - 1 if page > 1 else None,
      "results": serializer.data,
  }
  ```

#### 1b. `ConversationDetailView` — GET + DELETE `/conversations/{conversation_id}`

**URL kwarg:** `conversation_id` (UUID)

**GET method:**
- Permission: `IsAuthenticated`
- Fetch conversation: `Conversation.objects.prefetch_related('messages').annotate(message_count=Count('messages')).get(id=conversation_id)`
- Ownership check: if `conversation.user != request.user` → return `403`
- Return `200 OK` with `ConversationDetailSerializer(conversation).data`

**DELETE method:**
- Permission: `IsAuthenticated`
- Fetch conversation: `Conversation.objects.get(id=conversation_id)`
- Ownership check: if `conversation.user != request.user` → return `403`
- `conversation.delete()` → return `204 No Content` (empty response)

**Error handling for both methods:**
- `Conversation.DoesNotExist` → return `404` with `{"error": "not_found", "message": "Conversation not found"}`

---

### 2. `src/backend/conversations/urls.py` — URL Configuration

```python
from django.urls import path

from conversations.views import ConversationDetailView, ConversationListCreateView

app_name = "conversations"

urlpatterns = [
    path("", ConversationListCreateView.as_view(), name="conversation-list-create"),
    path("<uuid:conversation_id>/", ConversationDetailView.as_view(), name="conversation-detail"),
]
```

---

### 3. `src/backend/config/urls.py` — Registration

Add the import and include line. The existing commented-out line at line 57 should be replaced/activated:

```python
# Change this (line 57):
# path('api/v1/conversations/', include('conversations.urls', namespace='conversations')),

# To this (add after the documents include, around line 56-58):
path('conversations/', include('conversations.urls')),
```

Also add the import at the top of the file (no import needed since we use `include('conversations.urls')` string-based include).

---

### 4. `src/backend/conversations/tests/test_views.py` — Tests

Follow the exact patterns from [`src/backend/documents/tests/test_views.py`](src/backend/documents/tests/test_views.py):
- Use `APIClient` from `rest_framework.test`
- Use `TestCase` from `django.test`
- Use `_auth_header()` helper to generate JWT tokens
- Use `reverse()` with `app_name:view_name` format for URLs

#### Test Classes and Cases:

**`ConversationListCreateViewTests`:**

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_post_creates_conversation` | POST with valid `document_id` and `title` → 201, check response has id/document_id/title/created_at/updated_at/messages (empty list) |
| 2 | `test_post_without_title` | POST with only `document_id` → 201, title is empty string or null |
| 3 | `test_post_unauthenticated` | POST without auth header → 401 |
| 4 | `test_post_nonexistent_document` | POST with random UUID document_id → 400 (serializer validation) |
| 5 | `test_post_other_users_document` | POST with document owned by another user → 400 or 403 |
| 6 | `test_post_unprocessed_document` | POST with document that has `processing_status='pending'` → 400 or 422 |
| 7 | `test_get_lists_user_conversations` | GET → 200, returns only current user's conversations (not other users') |
| 8 | `test_get_with_message_count` | GET → 200, each result has `message_count` field |
| 9 | `test_get_pagination_defaults` | GET with no params → page=1, page_size=20 |
| 10 | `test_get_pagination_custom` | GET with `?page=1&page_size=2` → returns 2 results, has next/previous links |
| 11 | `test_get_pagination_max_page_size` | GET with `?page_size=200` → page_size capped at 100 |
| 12 | `test_get_filter_by_document_id` | GET with `?document_id=uuid` → only conversations for that document |
| 13 | `test_get_unauthenticated` | GET without auth header → 401 |

**`ConversationDetailViewTests`:**

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_get_returns_conversation_with_messages` | GET → 200, check nested messages, document_title, message_count |
| 2 | `test_get_other_users_conversation` | GET as different user → 403 |
| 3 | `test_get_nonexistent_conversation` | GET with random UUID → 404 |
| 4 | `test_get_unauthenticated` | GET without auth header → 401 |
| 5 | `test_delete_removes_conversation` | DELETE → 204, verify conversation deleted from DB |
| 6 | `test_delete_other_users_conversation` | DELETE as different user → 403 |
| 7 | `test_delete_nonexistent_conversation` | DELETE with random UUID → 404 |
| 8 | `test_delete_unauthenticated` | DELETE without auth header → 401 |

#### Test Setup Pattern:

```python
def setUp(self) -> None:
    self.client = APIClient()
    self.user = User.objects.create_user(
        email="test@example.com",
        password="testpass123",
    )
    self.other_user = User.objects.create_user(
        email="other@example.com",
        password="testpass123",
    )
    self.document = Document.objects.create(
        user=self.user,
        title="test-doc.pdf",
        filename="test-doc.pdf",
        original_filename="test-doc.pdf",
        file_path="/storage/test-doc.pdf",
        file_size=2048,
        mime_type="application/pdf",
        processing_status="completed",
    )
    self.conversation = Conversation.objects.create(
        user=self.user,
        document=self.document,
        title="My Conversation",
    )
    # Create some messages for detail view tests
    Message.objects.create(
        conversation=self.conversation,
        role="user",
        content="Hello",
    )
    Message.objects.create(
        conversation=self.conversation,
        role="assistant",
        content="Hi there!",
    )
```

#### URL Reverse Names:

```python
# For ConversationListCreateView
reverse("conversations:conversation-list-create")

# For ConversationDetailView
reverse("conversations:conversation-detail", kwargs={"conversation_id": conv.id})
```

---

## TDD Flow (per `.clinerules`)

1. **RED:** Write the test file first with all test cases (they will fail since views don't exist yet)
2. **GREEN:** Implement the views, URLs, and config registration to make tests pass
3. **REFACTOR:** Clean up code, ensure no duplication, verify all tests pass

---

## Verification

After implementation, run:
```bash
docker-compose exec backend pytest conversations/tests/test_views.py -v
```

Expected: All ~21 tests pass.

Then run full suite to check for regressions:
```bash
docker-compose exec backend pytest -v
```

---

## Acceptance Criteria (from PRD)

- [ ] All 4 CRUD operations tested (POST, GET list, GET detail, DELETE)
- [ ] Happy path + auth errors (401) + ownership errors (403) + not found (404)
- [ ] Pagination tested (next/previous links, page_size cap)
- [ ] `document_id` filter tested
- [ ] No regressions in existing tests
