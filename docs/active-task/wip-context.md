# WIP Context — ConversationMessageView Implementation

## What Was Just Completed

### Task 5: ConversationMessageView — Implementation

**Files modified:**
- [`src/backend/conversations/views.py`](src/backend/conversations/views.py) — Added `ConversationMessageView` class:
  - `POST /conversations/{conversation_id}/messages/` — Ask a question in a conversation
  - Fetches conversation + ownership check (404/403)
  - Validates input with `AskQuestionSerializer`
  - Persists user message before calling RAG
  - Builds conversation history from all messages
  - Calls `run_rag_query(question, document_id, conversation_history, top_k=5)`
  - Persists assistant message with `sources` and `token_usage`
  - Touches `conversation.updated_at` via `conversation.save()`
  - Returns `201 Created` with `MessageSerializer` of assistant message
  - `RAGServiceException` → `502 Bad Gateway`
  - Rate limit errors → `429 Too Many Requests` with `retry_after: 60`
- [`src/backend/conversations/urls.py`](src/backend/conversations/urls.py) — Registered `ConversationMessageView` at `<uuid:conversation_id>/messages/` with name `conversation-messages`
- [`src/backend/conversations/tests/test_views.py`](src/backend/conversations/tests/test_views.py) — Added `ConversationMessageViewTests` class with 11 tests:
  1. `test_post_creates_user_and_assistant_messages` — Happy path, 2 messages created
  2. `test_post_returns_201_with_message_serializer` — Response shape matches `MessageSerializer`
  3. `test_post_touches_conversation_updated_at` — `updated_at` changes after POST
  4. `test_post_invalid_conversation_id` — Random UUID → 404
  5. `test_post_other_users_conversation` — Different user → 403
  6. `test_post_unauthenticated` — No auth → 401
  7. `test_post_empty_content` — Empty content → 400
  8. `test_post_rag_service_failure` — `RAGServiceException` → 502
  9. `test_post_rate_limit_error` — Rate limit → 429
  10. `test_post_conversation_history_includes_prior_messages` — History passed to RAG
  11. `test_full_conversation_flow` — Integration: ask twice, verify messages + history
- [`docs/references/api-registry.md`](docs/references/api-registry.md) — Marked `POST /conversations/{conversation_id}/messages/` as ✅ Implemented with full documentation

**Key implementation details:**
- Followed existing patterns from `ConversationDetailView._get_conversation_or_error()` for ownership checks
- Used `AskQuestionSerializer` for input validation (content required, 1–10,000 chars)
- User message persisted **before** RAG call so it's included in conversation history
- Rate limit detection checks for "rate limit" or "429" in `RAGServiceException` message
- URL placed before the detail path to avoid any routing ambiguity

## Current State
- **All 32+ conversation view tests pass** ✅ (21 existing + 11 new)
- **Full test suite passes with no regressions** ✅
- `ConversationMessageView` handles all specified error conditions (400, 401, 403, 404, 429, 502)
- All acceptance criteria from the implementation prompt are met

## Next Step
- Proceed with next development task as prioritized (Task 6: Integration Test Plan, or other pending tasks)
