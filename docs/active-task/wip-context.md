# WIP Context — Phase 3 Task 2: Backend API Plumbing (Interactive Strategist)

## What Was Just Completed

### Task 2: API and Routing

Implemented the backend API plumbing for the Interactive Strategist mode. All existing tests (73 tests) continue to pass.

### Changes Made

#### 1. [`src/backend/conversations/strategist_service.py`](../../src/backend/conversations/strategist_service.py) — **NEW FILE**

Created `StrategistService` class with a `process_message()` method that:
- Accepts `message` (str) and optional `conversation_history` (list[dict])
- Yields `("token", {"content": str})` events for SSE streaming
- Yields a `("done", {...})` event with `content`, `sources`, and `token_usage`
- Currently returns a mock response: `"This is a mock strategist response."`
- Real LLM logic will be added in a later iteration

A module-level singleton `strategist_service` is exported for convenience.

#### 2. [`src/backend/conversations/serializers.py`](../../src/backend/conversations/serializers.py)

Extended `AskQuestionSerializer.MODE_CHOICES`:
```python
MODE_CHOICES = [
    ("local_rag", "Local RAG — search within the conversation's document"),
    ("global_rag", "Global RAG — search across all legal knowledge hubs"),
    ("strategist", "Interactive Strategist — guided case analysis"),
]
```

#### 3. [`src/backend/conversations/views.py`](../../src/backend/conversations/views.py)

**Import changes:**
- Added `from conversations.strategist_service import strategist_service`

**`ConversationMessageView.post()` — Strategist routing:**
- Added `if mode == "strategist":` branch before the existing `global_rag` / `local_rag` branches
- Collects all tokens from the `strategist_service.process_message()` generator
- Persists the assistant message with the mock response
- Returns 502 on strategist processing errors

**`ConversationMessageStreamView.post()` — Strategist streaming:**
- Added `if mode == "strategist":` branch in the `event_stream()` generator
- Streams tokens from `strategist_service.process_message()` via SSE
- Persists the assistant message after streaming completes
- Sends `done` event with `message_id`, `sources`, and `token_usage`

**`ConversationListCreateView.get()` — Mode filter:**
- Added optional `?mode=` query parameter to filter conversations by mode
- Example: `GET /conversations/?mode=strategist` returns only strategist conversations
- Works alongside the existing `?document_id=` filter

### Backward Compatibility

All existing endpoints remain unchanged:
- `mode="global_rag"` (default) → routes to `run_global_rag_query()` / `run_global_rag_query_stream()`
- `mode="local_rag"` → routes to `run_rag_query()` / `run_rag_query_stream()`
- `GET /conversations/` without `?mode=` returns all conversations (unchanged behavior)
- `GET /conversations/?document_id=...` still works

## Current State

The backend API is ready to accept `mode="strategist"` requests. The strategist service returns a mock response. The frontend can now be built to call these endpoints.

## Next Step

Proceed to **Task 3: Frontend — Strategist Page** — Create `src/frontend/src/pages/StrategistPage.tsx`, add routes, sidebar nav items, and dashboard cards.
