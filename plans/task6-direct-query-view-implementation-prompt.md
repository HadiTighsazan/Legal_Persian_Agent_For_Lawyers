# Task 6 — Direct Query View (Stateless RAG Endpoint) — Implementation Prompt

## Overview

Implement a stateless RAG query endpoint `POST /documents/{document_id}/query` that allows users to ask questions directly about a document **without** creating any `Conversation` or `Message` records. This is a pure query-and-response endpoint.

---

## Files to Modify

| File | Action |
|------|--------|
| [`src/backend/conversations/views.py`](src/backend/conversations/views.py) | Add `DocumentDirectQueryView` class |
| [`src/backend/documents/urls.py`](src/backend/documents/urls.py) | Register the new route |
| [`src/backend/conversations/tests/test_views.py`](src/backend/conversations/tests/test_views.py) | Add `DocumentDirectQueryViewTests` class |
| [`docs/references/api-registry.md`](docs/references/api-registry.md) | Mark `POST /documents/{document_id}/query` as ✅ Implemented |
| [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) | Update with completion details |

---

## Step 1: Add `DocumentDirectQueryView` to [`src/backend/conversations/views.py`](src/backend/conversations/views.py)

### Location

Add the new class **after** `ConversationMessageView` (line 367) and **before** the end of the file.

### Class Structure

```python
class DocumentDirectQueryView(APIView):
    """Handle stateless direct queries against a document.

    **Endpoint:** ``POST /documents/{document_id}/query``

    **Authentication:** Required (JWT via ``rest_framework_simplejwt``).

    **POST Responses:**
        - ``200 OK`` — Query answered successfully.
        - ``400 Bad Request`` — Validation error (empty question, invalid top_k, etc.).
        - ``401 Unauthorized`` — Missing or invalid authentication.
        - ``403 Forbidden`` — Document belongs to another user.
        - ``404 Not Found`` — Document does not exist.
        - ``422 Unprocessable Entity`` — Document processing is not complete.
        - ``429 Too Many Requests`` — OpenAI API rate limit exceeded.
        - ``502 Bad Gateway`` — RAG service error.
    """

    permission_classes = [IsAuthenticated]
```

### POST Method Logic

```python
def post(self, request: Request, document_id: str) -> Response:
    """Handle the direct query POST request."""
    # ------------------------------------------------------------------
    # 1. Fetch document + ownership check
    # ------------------------------------------------------------------
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return Response(
            {"error": "not_found", "message": "Document not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    if document.user != request.user:
        return Response(
            {
                "error": "permission_denied",
                "message": "You do not have permission to access this document.",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # ------------------------------------------------------------------
    # 2. Validate document processing status
    # ------------------------------------------------------------------
    if document.processing_status != "completed":
        return Response(
            {
                "error": "processing_incomplete",
                "message": "Document processing is not complete. Please wait for processing to finish.",
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # ------------------------------------------------------------------
    # 3. Validate input with DirectQuerySerializer
    # ------------------------------------------------------------------
    serializer = DirectQuerySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data
    question = validated_data["question"]
    top_k = validated_data.get("top_k", 5)

    # ------------------------------------------------------------------
    # 4. Call run_rag_query (stateless — no conversation history)
    # ------------------------------------------------------------------
    try:
        result = run_rag_query(
            question=question,
            document_id=str(document.id),
            conversation_history=[],
            top_k=top_k,
        )
    except RAGServiceException as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "429" in error_msg:
            return Response(
                {
                    "error": "rate_limit_exceeded",
                    "message": "OpenAI API rate limit exceeded. Please try again later.",
                    "retry_after": 60,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        logger.error(
            "Direct query RAG failed for document %s: %s",
            document_id,
            e,
        )
        return Response(
            {"error": "rag_error", "message": str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # ------------------------------------------------------------------
    # 5. Return 200 OK with answer, sources, token_usage
    #    NOTE: Do NOT persist any messages or conversations
    # ------------------------------------------------------------------
    return Response(
        {
            "answer": result["content"],
            "sources": result["sources"],
            "token_usage": result["token_usage"],
        },
        status=status.HTTP_200_OK,
    )
```

### Key Design Decisions

1. **Ownership check** — Uses the same pattern as other views: `Document.objects.get(id=document_id)` then `document.user != request.user` → `403`. This is consistent with [`ConversationDetailView._get_conversation_or_error()`](src/backend/conversations/views.py:168).

2. **Processing status check** — Returns `422 Unprocessable Entity` if `document.processing_status != "completed"`. This matches the PRD spec (Task 6) which says `→ 422 if not`.

3. **Stateless** — `conversation_history=[]` is passed to `run_rag_query`. No `Message` or `Conversation` objects are created anywhere in this view.

4. **Response shape** — Returns `answer` (not `content`) as the key for the assistant's response, matching the API registry contract at [`docs/references/api-registry.md:804`](docs/references/api-registry.md:804).

5. **Error handling** — Same pattern as [`ConversationMessageView`](src/backend/conversations/views.py:316-342): `RAGServiceException` → `502`, rate limit detection → `429`.

### Required Imports

The following imports already exist in [`src/backend/conversations/views.py`](src/backend/conversations/views.py):

```python
from documents.models import Document  # Already imported? Check.
```

**Check:** The current imports at lines 21-29 include:
```python
from conversations.models import Conversation, Message
from conversations.rag_service import RAGServiceException, run_rag_query
from conversations.serializers import (
    AskQuestionSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    MessageSerializer,
)
```

You need to **add**:
- `DirectQuerySerializer` to the imports from `conversations.serializers`
- `Document` from `documents.models` (if not already imported — verify)

---

## Step 2: Register URL in [`src/backend/documents/urls.py`](src/backend/documents/urls.py)

Add the following import and path entry.

### Import

Add to the existing imports at lines 10-20:

```python
from conversations.views import DocumentDirectQueryView
```

### URL Pattern

Add to the `urlpatterns` list (after the existing paths, before the closing bracket):

```python
path(
    "<uuid:document_id>/query/",
    DocumentDirectQueryView.as_view(),
    name="document-query",
),
```

**Important:** This route is registered under the `documents` app's URL namespace (`app_name = "documents"`), so the full path will be `/documents/{document_id}/query/`.

---

## Step 3: Add Tests to [`src/backend/conversations/tests/test_views.py`](src/backend/conversations/tests/test_views.py)

Add a new test class `DocumentDirectQueryViewTests` at the end of the file.

### Mock RAG Response

Use the same `_MOCK_RAG_RESPONSE` that `ConversationMessageViewTests` uses (already defined at lines 435-452). If it's a class-level constant, you can reference it. If it's inside `ConversationMessageViewTests`, define a new one in your test class.

```python
_MOCK_RAG_RESPONSE: dict = {
    "content": "Based on the document, the answer is...",
    "sources": [
        {
            "chunk_id": "chunk-1",
            "page_start": 1,
            "page_end": 3,
            "content_preview": "Sample content...",
            "relevance_score": 0.95,
        }
    ],
    "token_usage": {
        "prompt_tokens": 350,
        "completion_tokens": 50,
        "total_tokens": 400,
    },
    "raw_chunks": [],
}
```

### Test Class

```python
class DocumentDirectQueryViewTests(TestCase):
    """Tests for the :class:`DocumentDirectQueryView` endpoint."""

    _MOCK_RAG_RESPONSE: dict = {
        "content": "Based on the document, the answer is...",
        "sources": [
            {
                "chunk_id": "chunk-1",
                "page_start": 1,
                "page_end": 3,
                "content_preview": "Sample content...",
                "relevance_score": 0.95,
            }
        ],
        "token_usage": {
            "prompt_tokens": 350,
            "completion_tokens": 50,
            "total_tokens": 400,
        },
        "raw_chunks": [],
    }

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="query-test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-query@example.com",
            password="testpass123",
        )
        self.document = _create_document(self.user)
        self.url = reverse(
            "documents:document-query",
            kwargs={"document_id": self.document.id},
        )

    def _post_query(
        self,
        question: str = "What is this document about?",
        top_k: int | None = None,
        **extra,
    ) -> Response:
        """Helper to POST a direct query."""
        payload: dict = {"question": question}
        if top_k is not None:
            payload["top_k"] = top_k
        return self.client.post(
            self.url,
            payload,
            format="json",
            **_auth_header(self.user),
            **extra,
        )
```

### Test Cases (10 tests minimum)

#### 1. Happy path — returns 200 with answer, sources, token_usage

```python
@patch("conversations.views.run_rag_query")
def test_post_returns_200_with_answer_sources_token_usage(
    self,
    mock_run_rag_query: patch,
) -> None:
    """POST with valid question should return 200 with answer, sources, token_usage."""
    mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

    response = self._post_query()
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    data = response.json()
    self.assertIn("answer", data)
    self.assertEqual(data["answer"], "Based on the document, the answer is...")
    self.assertIn("sources", data)
    self.assertEqual(data["sources"], self._MOCK_RAG_RESPONSE["sources"])
    self.assertIn("token_usage", data)
    self.assertEqual(data["token_usage"], self._MOCK_RAG_RESPONSE["token_usage"])
```

#### 2. Verify no Message or Conversation objects are created

```python
@patch("conversations.views.run_rag_query")
def test_post_does_not_create_any_messages_or_conversations(
    self,
    mock_run_rag_query: patch,
) -> None:
    """POST should NOT create any Message or Conversation objects."""
    mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

    initial_msg_count = Message.objects.count()
    initial_conv_count = Conversation.objects.count()

    response = self._post_query()
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    # Verify no new records were created
    self.assertEqual(Message.objects.count(), initial_msg_count)
    self.assertEqual(Conversation.objects.count(), initial_conv_count)
```

#### 3. Verify run_rag_query is called with correct args

```python
@patch("conversations.views.run_rag_query")
def test_post_calls_run_rag_query_with_correct_args(
    self,
    mock_run_rag_query: patch,
) -> None:
    """POST should call run_rag_query with question, document_id, empty history, and top_k."""
    mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

    self._post_query(question="Test question?", top_k=3)

    mock_run_rag_query.assert_called_once_with(
        question="Test question?",
        document_id=str(self.document.id),
        conversation_history=[],
        top_k=3,
    )
```

#### 4. Document not found → 404

```python
def test_post_document_not_found(self) -> None:
    """POST with non-existent document_id should return 404."""
    url = reverse(
        "documents:document-query",
        kwargs={"document_id": uuid.uuid4()},
    )
    payload = {"question": "Hello?"}
    response = self.client.post(
        url,
        payload,
        format="json",
        **_auth_header(self.user),
    )
    self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    self.assertEqual(response.data["error"], "not_found")
```

#### 5. Other user's document → 403

```python
def test_post_other_users_document(self) -> None:
    """POST as a different user should return 403."""
    payload = {"question": "Hello?"}
    response = self.client.post(
        self.url,
        payload,
        format="json",
        **_auth_header(self.other_user),
    )
    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    self.assertEqual(response.data["error"], "permission_denied")
```

#### 6. Unauthenticated → 401

```python
def test_post_unauthenticated(self) -> None:
    """POST without auth header should return 401."""
    payload = {"question": "Hello?"}
    response = self.client.post(self.url, payload, format="json")
    self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
```

#### 7. Document not completed → 422

```python
def test_post_document_not_completed(self) -> None:
    """POST with a document that has processing_status != 'completed' should return 422."""
    unprocessed_doc = _create_document(self.user, processing_status="pending")
    url = reverse(
        "documents:document-query",
        kwargs={"document_id": unprocessed_doc.id},
    )
    payload = {"question": "Hello?"}
    response = self.client.post(
        url,
        payload,
        format="json",
        **_auth_header(self.user),
    )
    self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
    self.assertEqual(response.data["error"], "processing_incomplete")
```

#### 8. Empty question → 400

```python
def test_post_empty_question(self) -> None:
    """POST with empty question should return 400."""
    response = self._post_query(question="")
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
```

#### 9. RAG service failure → 502

```python
@patch("conversations.views.run_rag_query")
def test_post_rag_service_failure(
    self,
    mock_run_rag_query: patch,
) -> None:
    """POST when RAG service raises RAGServiceException should return 502."""
    mock_run_rag_query.side_effect = RAGServiceException(
        "OpenAI API call failed: Connection error"
    )

    response = self._post_query()
    self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
    self.assertEqual(response.data["error"], "rag_error")
```

#### 10. Rate limit error → 429

```python
@patch("conversations.views.run_rag_query")
def test_post_rate_limit_error(
    self,
    mock_run_rag_query: patch,
) -> None:
    """POST when RAG service raises rate limit error should return 429."""
    mock_run_rag_query.side_effect = RAGServiceException(
        "rate limit exceeded: 429 Too Many Requests"
    )

    response = self._post_query()
    self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
    self.assertEqual(response.data["error"], "rate_limit_exceeded")
    self.assertEqual(response.data["retry_after"], 60)
```

#### 11. Default top_k is 5

```python
@patch("conversations.views.run_rag_query")
def test_post_default_top_k(
    self,
    mock_run_rag_query: patch,
) -> None:
    """POST without top_k should default to 5."""
    mock_run_rag_query.return_value = self._MOCK_RAG_RESPONSE

    self._post_query(question="Test question?")

    call_kwargs = mock_run_rag_query.call_args[1]
    self.assertEqual(call_kwargs["top_k"], 5)
```

---

## Step 4: Update Reference Documents

### Update [`docs/references/api-registry.md`](docs/references/api-registry.md)

Change the `POST /documents/{document_id}/query` entry (lines 792-821) from a planned endpoint to an implemented one. Add:

```
**Status:** ✅ Implemented
**Implementation Date:** 2026-04-28
**View Class:** `DocumentDirectQueryView`
**Test Coverage:** 11 tests in `DocumentDirectQueryViewTests`
```

### Update [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md)

Overwrite with:

```markdown
# WIP Context — DocumentDirectQueryView Implementation

## What Was Just Completed

### Task 6: DocumentDirectQueryView — Implementation

**Files modified:**
- [`src/backend/conversations/views.py`](src/backend/conversations/views.py) — Added `DocumentDirectQueryView` class:
  - `POST /documents/{document_id}/query/` — Stateless direct query endpoint
  - Fetches document + ownership check (404/403)
  - Validates document `processing_status == 'completed'` → 422
  - Validates input with `DirectQuerySerializer` (question, top_k)
  - Calls `run_rag_query(question, document_id, conversation_history=[], top_k=top_k)`
  - Returns `200 OK` with `answer`, `sources`, `token_usage`
  - **Does NOT persist any Message or Conversation objects** (stateless)
  - `RAGServiceException` → `502 Bad Gateway`
  - Rate limit errors → `429 Too Many Requests` with `retry_after: 60`
- [`src/backend/documents/urls.py`](src/backend/documents/urls.py) — Registered `DocumentDirectQueryView` at `<uuid:document_id>/query/` with name `document-query`
- [`src/backend/conversations/tests/test_views.py`](src/backend/conversations/tests/test_views.py) — Added `DocumentDirectQueryViewTests` class with 11 tests:
  1. `test_post_returns_200_with_answer_sources_token_usage` — Happy path
  2. `test_post_does_not_create_any_messages_or_conversations` — Stateless verification
  3. `test_post_calls_run_rag_query_with_correct_args` — Correct args passed
  4. `test_post_document_not_found` — Non-existent doc → 404
  5. `test_post_other_users_document` — Wrong user → 403
  6. `test_post_unauthenticated` — No auth → 401
  7. `test_post_document_not_completed` — Unprocessed doc → 422
  8. `test_post_empty_question` — Empty question → 400
  9. `test_post_rag_service_failure` — RAG error → 502
  10. `test_post_rate_limit_error` — Rate limit → 429
  11. `test_post_default_top_k` — Default top_k is 5
- [`docs/references/api-registry.md`](docs/references/api-registry.md) — Marked `POST /documents/{document_id}/query` as ✅ Implemented with full documentation

**Key implementation details:**
- Followed existing patterns from `ConversationMessageView` for ownership checks and error handling
- Used `DirectQuerySerializer` for input validation (question required, top_k optional with default 5)
- Passed `conversation_history=[]` to `run_rag_query` since this is stateless
- Response uses `answer` key (not `content`) to match the API registry contract
- URL registered under `documents/` URL namespace (not `conversations/`)

## Current State
- **All conversation view tests pass** ✅ (existing + 11 new)
- **Full test suite passes with no regressions** ✅
- `DocumentDirectQueryView` handles all specified error conditions (400, 401, 403, 404, 422, 429, 502)
- All acceptance criteria from the implementation prompt are met

## Next Step
- Proceed with next development task as prioritized
```

---

## Acceptance Criteria Checklist

- [ ] `DocumentDirectQueryView` added to [`src/backend/conversations/views.py`](src/backend/conversations/views.py)
- [ ] Route registered in [`src/backend/documents/urls.py`](src/backend/documents/urls.py) as `documents:document-query`
- [ ] `DirectQuerySerializer` imported and used for input validation
- [ ] Ownership check on document → `403 Forbidden`
- [ ] Document `processing_status == 'completed'` check → `422 Unprocessable Entity`
- [ ] `run_rag_query` called with `conversation_history=[]`
- [ ] No `Message` or `Conversation` objects created (stateless)
- [ ] Response returns `200 OK` with `answer`, `sources`, `token_usage`
- [ ] `RAGServiceException` → `502 Bad Gateway`
- [ ] Rate limit detection → `429 Too Many Requests`
- [ ] 11 unit tests pass with mocked `run_rag_query`
- [ ] No regressions in existing tests
- [ ] `python manage.py check` passes clean
- [ ] Reference docs updated (`api-registry.md`, `wip-context.md`)
