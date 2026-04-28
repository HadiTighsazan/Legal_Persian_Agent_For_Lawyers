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
