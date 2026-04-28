# Task 7 — Integration Tests & Final QA — Implementation Prompt

## Objective

Create comprehensive test files for the `conversations` app to achieve **≥ 90% code coverage**, and write a full end-to-end integration test. All existing tests (E01–E06) must continue to pass with **zero regressions**.

---

## Background Context

### What Already Exists

The following source code is already implemented and **must not be modified**:

| File | Purpose |
|------|---------|
| [`src/backend/conversations/models.py`](src/backend/conversations/models.py) | `Conversation` and `Message` models |
| [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) | 6 serializers: `MessageSerializer`, `ConversationListSerializer`, `ConversationDetailSerializer`, `ConversationCreateSerializer`, `AskQuestionSerializer`, `DirectQuerySerializer` |
| [`src/backend/conversations/rag_service.py`](src/backend/conversations/rag_service.py) | `build_context`, `build_system_prompt`, `extract_citations`, `run_rag_query`, `RAGServiceException` |
| [`src/backend/conversations/views.py`](src/backend/conversations/views.py) | `ConversationListCreateView`, `ConversationDetailView`, `ConversationMessageView`, `DocumentDirectQueryView` |
| [`src/backend/conversations/urls.py`](src/backend/conversations/urls.py) | URL routing for conversations app |

### What Already Exists in Tests

The following test files **already exist** and must be **refactored/reorganized** (not deleted — content should be moved into the new file structure):

| File | Contents |
|------|----------|
| [`src/backend/conversations/tests/test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py) | `BuildContextTests`, `BuildSystemPromptTests`, `ExtractCitationsTests`, `RunRagQueryTests` |
| [`src/backend/conversations/tests/test_serializers.py`](src/backend/conversations/tests/test_serializers.py) | `MessageSerializerTests`, `ConversationListSerializerTests`, `ConversationDetailSerializerTests`, `ConversationCreateSerializerTests`, `AskQuestionSerializerTests`, `DirectQuerySerializerTests` |
| [`src/backend/conversations/tests/test_views.py`](src/backend/conversations/tests/test_views.py) | `ConversationListCreateViewTests`, `ConversationDetailViewTests`, `ConversationMessageViewTests`, `DocumentDirectQueryViewTests` |

### Key Configuration

- **pytest.ini** at [`src/backend/pytest.ini`](src/backend/pytest.ini): Uses `--reuse-db`, discovers `test_*.py` files, looks for `Test*` or `*Tests` classes
- **conftest.py** at [`src/backend/conftest.py`](src/backend/conftest.py): Sets `DJANGO_SETTINGS_MODULE`
- **Settings** at [`src/backend/config/settings.py`](src/backend/config/settings.py): Key RAG settings — `RAG_CONTEXT_TOKEN_BUDGET=4000`, `RAG_MAX_HISTORY_TURNS=10`, `OPENAI_CHAT_MODEL=gpt-4o-mini`, `OPENAI_CHAT_MAX_TOKENS=1000`
- **Auth**: Uses `rest_framework_simplejwt` — generate tokens via `RefreshToken.for_user(user)`
- **User model**: Custom `users.models.User` with `email` as USERNAME_FIELD, uses `User.objects.create_user(email=..., password=...)`

---

## Test File Structure

Create **7 test files** in [`src/backend/conversations/tests/`](src/backend/conversations/tests/):

```
src/backend/conversations/tests/
├── __init__.py                          # Already exists (empty)
├── test_models.py                       # NEW — model tests
├── test_serializers.py                  # REFACTOR — move from existing test_serializers.py
├── test_rag_service.py                  # REFACTOR — move from existing test_rag_service.py
├── test_views_conversations.py          # NEW — CRUD view tests (split from test_views.py)
├── test_views_messages.py               # NEW — ask-question view tests (split from test_views.py)
├── test_views_query.py                  # NEW — direct query view tests (split from test_views.py)
└── test_integration.py                  # NEW — end-to-end integration test
```

**IMPORTANT**: The existing [`test_views.py`](src/backend/conversations/tests/test_views.py) file should be **deleted** after its contents are distributed into the 3 new view test files. The existing [`test_serializers.py`](src/backend/conversations/tests/test_serializers.py) and [`test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py) should be **replaced** by the new versions (same content, just reorganized).

---

## Detailed Test Specifications

### 1. [`test_models.py`](src/backend/conversations/tests/test_models.py)

**Test class:** `ConversationModelTests` (extends `django.test.TestCase`)

**Tests to implement:**

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_create_conversation` | Create a `Conversation` with a user + document, verify all fields are set correctly, verify `id` is a UUID |
| 2 | `test_create_message` | Create a `Message` linked to a conversation, verify `role`, `content`, `sources` default to `[]`, `token_usage` is `None` |
| 3 | `test_conversation_str` | Verify `str(conversation)` returns `"Conversation about {document.title} ({user.email})"` |
| 4 | `test_message_str` | Verify `str(message)` returns `"{role}: {content[:50]}..."` |
| 5 | `test_cascade_delete_conversation` | Delete a conversation, verify all its messages are also deleted (cascade) |
| 6 | `test_cascade_delete_user` | Delete a user, verify their conversations are also deleted |
| 7 | `test_cascade_delete_document` | Delete a document, verify its conversations are also deleted |
| 8 | `test_message_ordering` | Create messages with different `created_at` values, verify default ordering by `created_at` |
| 9 | `test_conversation_updated_at_auto_now` | Create conversation, save it again, verify `updated_at` changes |
| 10 | `test_message_sources_json_field` | Create a message with complex `sources` data (list of dicts), verify it's stored and retrievable as JSON |

### 2. [`test_serializers.py`](src/backend/conversations/tests/test_serializers.py)

**Content:** Same as the existing [`test_serializers.py`](src/backend/conversations/tests/test_serializers.py) — **no changes needed**. Just copy the existing file content.

**Test classes (all already exist):**
- `MessageSerializerTests` — 4 tests
- `ConversationListSerializerTests` — 3 tests
- `ConversationDetailSerializerTests` — 3 tests
- `ConversationCreateSerializerTests` — 6 tests
- `AskQuestionSerializerTests` — 5 tests
- `DirectQuerySerializerTests` — 7 tests

### 3. [`test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py)

**Content:** Same as the existing [`test_rag_service.py`](src/backend/conversations/tests/test_rag_service.py) — **no changes needed**. Just copy the existing file content.

**Test classes (all already exist):**
- `BuildContextTests` — 4 tests
- `BuildSystemPromptTests` — 2 tests
- `ExtractCitationsTests` — 6 tests
- `RunRagQueryTests` — 9 tests

### 4. [`test_views_conversations.py`](src/backend/conversations/tests/test_views_conversations.py)

**Test classes:**

#### `ConversationListCreateViewTests` (moved from existing `test_views.py`)

**Tests (all already exist in `test_views.py`):**

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_post_creates_conversation` | POST with valid document_id + title → 201 |
| 2 | `test_post_without_title` | POST with only document_id → 201 |
| 3 | `test_post_unauthenticated` | POST without auth → 401 |
| 4 | `test_post_nonexistent_document` | POST with random UUID → 400 |
| 5 | `test_post_other_users_document` | POST with another user's doc → 400 |
| 6 | `test_post_unprocessed_document` | POST with pending doc → 400 |
| 7 | `test_get_lists_user_conversations` | GET returns only current user's conversations |
| 8 | `test_get_with_message_count` | GET includes annotated message_count |
| 9 | `test_get_pagination_defaults` | GET with no pagination params |
| 10 | `test_get_pagination_custom` | GET with page=1&page_size=2 |
| 11 | `test_get_pagination_max_page_size` | GET with page_size=200 capped at 100 |
| 12 | `test_get_filter_by_document_id` | GET with ?document_id=uuid |
| 13 | `test_get_unauthenticated` | GET without auth → 401 |

#### `ConversationDetailViewTests` (moved from existing `test_views.py`)

**Tests (all already exist):**

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_get_returns_conversation_with_messages` | GET returns conversation with nested messages |
| 2 | `test_get_other_users_conversation` | GET as different user → 403 |
| 3 | `test_get_nonexistent_conversation` | GET with random UUID → 404 |
| 4 | `test_get_unauthenticated` | GET without auth → 401 |
| 5 | `test_delete_removes_conversation` | DELETE → 204 + removed from DB |
| 6 | `test_delete_other_users_conversation` | DELETE as different user → 403 |
| 7 | `test_delete_nonexistent_conversation` | DELETE with random UUID → 404 |
| 8 | `test_delete_unauthenticated` | DELETE without auth → 401 |

### 5. [`test_views_messages.py`](src/backend/conversations/tests/test_views_messages.py)

**Test class:** `ConversationMessageViewTests` (moved from existing `test_views.py`)

**Tests (all already exist):**

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_post_creates_user_and_assistant_messages` | POST creates 2 messages (user + assistant) |
| 2 | `test_post_returns_201_with_message_serializer` | POST returns MessageSerializer fields |
| 3 | `test_post_touches_conversation_updated_at` | POST updates conversation.updated_at |
| 4 | `test_post_invalid_conversation_id` | POST with random UUID → 404 |
| 5 | `test_post_other_users_conversation` | POST as different user → 403 |
| 6 | `test_post_unauthenticated` | POST without auth → 401 |
| 7 | `test_post_empty_content` | POST with empty content → 400 |
| 8 | `test_post_rag_service_failure` | POST when RAG raises → 502 |
| 9 | `test_post_rate_limit_error` | POST when RAG raises rate limit → 429 |
| 10 | `test_post_conversation_history_includes_prior_messages` | POST passes prior messages in history |
| 11 | `test_full_conversation_flow` | Full flow: create conv → ask → check → ask again → verify history |

### 6. [`test_views_query.py`](src/backend/conversations/tests/test_views_query.py)

**Test class:** `DocumentDirectQueryViewTests` (moved from existing `test_views.py`)

**Tests (all already exist):**

| # | Test Method | Description |
|---|-------------|-------------|
| 1 | `test_post_returns_200_with_answer_sources_token_usage` | Happy path → 200 |
| 2 | `test_post_does_not_create_any_messages_or_conversations` | Stateless verification |
| 3 | `test_post_calls_run_rag_query_with_correct_args` | Correct args passed |
| 4 | `test_post_document_not_found` | Non-existent doc → 404 |
| 5 | `test_post_other_users_document` | Wrong user → 403 |
| 6 | `test_post_unauthenticated` | No auth → 401 |
| 7 | `test_post_document_not_completed` | Unprocessed doc → 422 |
| 8 | `test_post_empty_question` | Empty question → 400 |
| 9 | `test_post_rag_service_failure` | RAG error → 502 |
| 10 | `test_post_rate_limit_error` | Rate limit → 429 |
| 11 | `test_post_default_top_k` | Default top_k is 5 |

### 7. [`test_integration.py`](src/backend/conversations/tests/test_integration.py) — **THE KEY NEW FILE**

**Test class:** `ConversationIntegrationTests` (extends `django.test.TestCase`)

**Purpose:** Test the full end-to-end flow: register → upload document → process → embed → create conversation → ask questions → verify history → delete conversation.

**Key design decisions:**
- Use `@patch('conversations.views.run_rag_query')` at the **class level** to mock the RAG pipeline
- Use `@patch('conversations.rag_service.embed_query')` and `@patch('conversations.rag_service.search_chunks')` and `@patch('conversations.rag_service.OpenAI')` at the **method level** for the RAG service integration sub-test
- Create a helper method `_create_processed_document(user)` that creates a `Document` with `processing_status='completed'` and `status='completed'`, plus a few `DocumentChunk` records with mock embeddings

**Integration scenario (7 steps):**

| Step | Action | Assertion |
|------|--------|-----------|
| 1 | Register user via `POST /auth/register/` | 201 + JWT tokens returned |
| 2 | Create a processed document + chunks directly in DB (no actual upload) | Document exists with `processing_status='completed'` |
| 3 | Create conversation via `POST /conversations/` with the document_id | 201 + conversation returned |
| 4 | POST a question to `/conversations/{id}/messages/` with mocked `run_rag_query` | 201 + assistant message with non-empty content and sources |
| 5 | GET `/conversations/{id}/` | 200 + exactly 2 messages (user + assistant) in history |
| 6 | POST a second question → verify `run_rag_query` was called with conversation_history containing both prior messages | 201 + call_args captured |
| 7 | DELETE `/conversations/{id}/` | 204 + conversation deleted + messages cascade-deleted |

**Detailed test methods:**

```python
class ConversationIntegrationTests(TestCase):
    """End-to-end integration tests for the conversations app."""

    MOCK_RAG_RESPONSE = {
        "content": "Based on the document, the answer is about machine learning.",
        "sources": [
            {
                "chunk_id": "chunk-1",
                "page_start": 1,
                "page_end": 3,
                "content_preview": "Machine learning is...",
                "relevance_score": 0.95,
            }
        ],
        "token_usage": {"prompt_tokens": 350, "completion_tokens": 50, "total_tokens": 400},
        "raw_chunks": [],
    }

    def setUp(self):
        self.client = APIClient()
        # Step 1: Register user
        self.register_url = '/auth/register/'
        response = self.client.post(
            self.register_url,
            {"email": "integration@example.com", "password": "SecurePass123!", "full_name": "Integration Test"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.user_email = data["user"]["email"]
        self.access_token = data["accessToken"]
        self.auth_header = {"HTTP_AUTHORIZATION": f"Bearer {self.access_token}"}

        # Step 2: Create a processed document with chunks directly
        self.user = User.objects.get(email=self.user_email)
        self.document = Document.objects.create(
            user=self.user,
            title="integration-test-doc.pdf",
            filename="integration-test-doc.pdf",
            original_filename="integration-test-doc.pdf",
            file_path="/tmp/integration-test-doc.pdf",
            file_size=2048,
            mime_type="application/pdf",
            processing_status="completed",
            status="completed",
        )
        # Create chunks with mock embeddings
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=0,
            page_start=1,
            page_end=3,
            content="Machine learning is a subset of artificial intelligence.",
            token_count=10,
            embedding=[0.1] * 768,
        )
        DocumentChunk.objects.create(
            document=self.document,
            chunk_index=1,
            page_start=4,
            page_end=6,
            content="Deep learning uses neural networks with multiple layers.",
            token_count=8,
            embedding=[0.2] * 768,
        )

    # --- Test methods ---

    @patch("conversations.views.run_rag_query")
    def test_full_conversation_lifecycle(self, mock_run_rag_query):
        """Complete lifecycle: create conv → ask → verify → ask again → delete."""
        mock_run_rag_query.return_value = self.MOCK_RAG_RESPONSE

        # Step 3: Create conversation
        create_url = reverse("conversations:conversation-list-create")
        response = self.client.post(
            create_url,
            {"document_id": str(self.document.id), "title": "Integration Test Conv"},
            format="json",
            **self.auth_header,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        conv_data = response.json()
        conversation_id = conv_data["id"]
        self.assertEqual(conv_data["document_id"], str(self.document.id))

        # Step 4: POST first question
        messages_url = reverse(
            "conversations:conversation-messages",
            kwargs={"conversation_id": conversation_id},
        )
        response = self.client.post(
            messages_url,
            {"content": "What is machine learning?"},
            format="json",
            **self.auth_header,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        msg_data = response.json()
        self.assertEqual(msg_data["role"], "assistant")
        self.assertIn("machine learning", msg_data["content"].lower())
        self.assertGreater(len(msg_data["sources"]), 0)
        self.assertIn("token_usage", msg_data)

        # Step 5: GET conversation → verify 2 messages
        detail_url = reverse(
            "conversations:conversation-detail",
            kwargs={"conversation_id": conversation_id},
        )
        response = self.client.get(detail_url, **self.auth_header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        detail_data = response.json()
        self.assertEqual(detail_data["message_count"], 2)
        self.assertEqual(len(detail_data["messages"]), 2)
        self.assertEqual(detail_data["messages"][0]["role"], "user")
        self.assertEqual(detail_data["messages"][0]["content"], "What is machine learning?")
        self.assertEqual(detail_data["messages"][1]["role"], "assistant")

        # Step 6: POST second question → verify history passed to RAG
        response = self.client.post(
            messages_url,
            {"content": "Tell me more about deep learning."},
            format="json",
            **self.auth_header,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify run_rag_query was called with conversation_history
        call_args = mock_run_rag_query.call_args
        self.assertIsNotNone(call_args)
        history = call_args.kwargs["conversation_history"]
        self.assertIsNotNone(history)
        # History should contain: first user msg + first assistant msg + second user msg
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "What is machine learning?")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[2]["role"], "user")
        self.assertEqual(history[2]["content"], "Tell me more about deep learning.")

        # Step 7: DELETE conversation
        response = self.client.delete(detail_url, **self.auth_header)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify conversation is deleted
        self.assertFalse(Conversation.objects.filter(id=conversation_id).exists())
        # Verify messages are cascade-deleted
        self.assertEqual(Message.objects.filter(conversation_id=conversation_id).count(), 0)
```

**Additional integration test — RAG service integration with mocked internals:**

```python
    @patch("conversations.rag_service.search_chunks")
    @patch("conversations.rag_service.embed_query")
    @patch("conversations.rag_service.OpenAI")
    def test_rag_service_integration(
        self, mock_openai, mock_embed_query, mock_search_chunks
    ):
        """Test that run_rag_query correctly orchestrates embedding, search, and OpenAI."""
        # Arrange
        mock_embed_query.return_value = [0.1] * 768
        mock_search_chunks.return_value = [
            {
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "page_start": 1,
                "page_end": 3,
                "content": "Machine learning is a subset of artificial intelligence.",
                "relevance_score": 0.95,
                "token_count": 10,
                "metadata": {},
            }
        ]
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "Based on [Source 1], machine learning is a subset of AI."
        )
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        # Act
        result = run_rag_query(
            question="What is machine learning?",
            document_id=str(self.document.id),
            top_k=5,
        )

        # Assert
        self.assertIn("content", result)
        self.assertIn("sources", result)
        self.assertIn("token_usage", result)
        self.assertIn("raw_chunks", result)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["chunk_id"], "chunk-1")
        self.assertEqual(result["token_usage"]["total_tokens"], 150)
```

---

## Implementation Steps (for Code Mode)

### Step 1: Create [`test_models.py`](src/backend/conversations/tests/test_models.py)

Write the file with `ConversationModelTests` class containing all 10 tests listed above.

### Step 2: Create [`test_views_conversations.py`](src/backend/conversations/tests/test_views_conversations.py)

Copy the `ConversationListCreateViewTests` and `ConversationDetailViewTests` classes from the existing [`test_views.py`](src/backend/conversations/tests/test_views.py). Include the helper functions `_auth_header` and `_create_document`.

### Step 3: Create [`test_views_messages.py`](src/backend/conversations/tests/test_views_messages.py)

Copy the `ConversationMessageViewTests` class from the existing [`test_views.py`](src/backend/conversations/tests/test_views.py). Include the helper functions.

### Step 4: Create [`test_views_query.py`](src/backend/conversations/tests/test_views_query.py)

Copy the `DocumentDirectQueryViewTests` class from the existing [`test_views.py`](src/backend/conversations/tests/test_views.py). Include the helper functions.

### Step 5: Delete [`test_views.py`](src/backend/conversations/tests/test_views.py)

After confirming all tests have been moved to the 3 new files, delete the old file.

### Step 6: Create [`test_integration.py`](src/backend/conversations/tests/test_integration.py)

Write the file with `ConversationIntegrationTests` class containing the full lifecycle test and the RAG service integration test.

### Step 7: Run tests and verify coverage

```bash
# Run all conversations tests
docker-compose exec backend pytest conversations/tests/ -v

# Check coverage
docker-compose exec backend pytest --cov=conversations --cov-report=term-missing

# Check no regressions
docker-compose exec backend pytest -v

# Django system checks
docker-compose exec backend python manage.py check
```

---

## Acceptance Criteria Checklist

- [ ] `pytest --cov=conversations --cov-report=term-missing` shows **≥ 90%** coverage
- [ ] All existing tests (E01–E06) still pass — **no regressions**
- [ ] `python manage.py check` passes clean
- [ ] `test_models.py` — 10 tests covering model creation, `__str__`, cascade delete, JSON fields
- [ ] `test_serializers.py` — 28 tests (unchanged from existing)
- [ ] `test_rag_service.py` — 21 tests (unchanged from existing)
- [ ] `test_views_conversations.py` — 21 tests (13 list-create + 8 detail)
- [ ] `test_views_messages.py` — 11 tests
- [ ] `test_views_query.py` — 11 tests
- [ ] `test_integration.py` — 2 tests (full lifecycle + RAG service integration)
- [ ] Old `test_views.py` is deleted after content migration

---

## Important Notes

1. **Do NOT modify** any source files in `conversations/models.py`, `conversations/serializers.py`, `conversations/rag_service.py`, `conversations/views.py`, or `conversations/urls.py`.
2. **Do NOT modify** any files outside `conversations/tests/`.
3. **Do NOT modify** `pytest.ini` or `conftest.py`.
4. The existing `test_serializers.py` and `test_rag_service.py` can be **replaced** with identical content — no changes needed.
5. The helper functions `_auth_header()` and `_create_document()` should be duplicated in each view test file that needs them (or placed in a shared conftest, but simpler to just duplicate).
6. For the integration test, create the document and chunks **directly in the database** (no actual file upload or Celery processing needed).
7. Use `from unittest.mock import patch, MagicMock` for all mocking.
8. All test classes should extend `django.test.TestCase` (not `pytest` plain tests) for database access.
9. The `__init__.py` file in the tests directory is already empty — no changes needed.
