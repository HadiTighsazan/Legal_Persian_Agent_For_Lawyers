# PRD — Epic E07: Conversation & Q&A Engine

**Status:** ⏳ Todo  
**Epic ID:** E07  
**Depends On:** E02 (Auth), E03 (Documents), E04 (Processing Pipeline), E05 (Embeddings), E06 (Semantic Search)  
**Output Path:** `docs/active-task/current-prd.md`

---

## Overview

Implement the full RAG-based Q&A engine. This epic wires together the existing embedding + search infrastructure (E05/E06) with LangChain, conversation/message persistence, citation tracking, and hallucination mitigation. The output is two working endpoints: a **stateful conversation endpoint** and a **stateless direct-query endpoint**.

---

## Affected Database Tables

| Table | Action |
|-------|--------|
| `conversations` | CREATE — new Django model |
| `messages` | CREATE — new Django model |
| `documents` | READ — ownership checks, status validation |
| `document_chunks` | READ — retrieved chunks for context injection |
| `processing_tasks` | READ — validate document is `completed` before allowing Q&A |

Schema for `conversations` and `messages` is already defined in `database-schema.md`. No new columns are needed beyond what is spec'd there.

---

## Affected API Endpoints

| Method | Path | Status |
|--------|------|--------|
| POST | `/conversations` | 🆕 Implement |
| GET | `/conversations` | 🆕 Implement |
| GET | `/conversations/{conversation_id}` | 🆕 Implement |
| DELETE | `/conversations/{conversation_id}` | 🆕 Implement |
| POST | `/conversations/{conversation_id}/messages` | 🆕 Implement (core RAG) |
| POST | `/documents/{document_id}/query` | 🆕 Implement (stateless RAG) |

Full request/response contracts are defined in `api-registry.md` under **Conversations** and **Messages / Q&A** sections. Do not deviate from them.

---

## Tech Stack Additions

- `langchain` + `langchain-openai` — RAG chain orchestration
- `langchain-community` — pgvector retriever (optional, can use custom retriever)
- No new infrastructure (Celery/Redis already available, OpenAI client already used in E05)

Add to `requirements.txt`:
```
langchain>=0.2.0
langchain-openai>=0.1.0
```

---

## Micro-Tasks

---

### Task 1 — Django Models: `Conversation` & `Message`

**Scope:** `src/backend/conversations/` (new app)

**Steps:**
1. Create Django app: `python manage.py startapp conversations`
2. Register in `INSTALLED_APPS` in `settings.py`
3. Create `Conversation` model mapping to `conversations` table:
   - `id`: UUIDField, primary_key, default=uuid4
   - `user`: ForeignKey → `users.User`, on_delete=CASCADE
   - `document`: ForeignKey → `documents.Document`, on_delete=CASCADE
   - `title`: CharField(max_length=500, null=True, blank=True)
   - `created_at`: DateTimeField(auto_now_add=True)
   - `updated_at`: DateTimeField(auto_now=True)
   - Meta: `db_table = 'conversations'`, ordering=['-updated_at']
4. Create `Message` model mapping to `messages` table:
   - `id`: UUIDField, primary_key, default=uuid4
   - `conversation`: ForeignKey → `Conversation`, on_delete=CASCADE, related_name='messages'
   - `role`: CharField(max_length=20, choices=[('user','user'),('assistant','assistant'),('system','system')])
   - `content`: TextField
   - `sources`: JSONField(default=list)
   - `token_usage`: JSONField(null=True, blank=True)
   - `created_at`: DateTimeField(auto_now_add=True)
   - Meta: `db_table = 'messages'`, ordering=['created_at']
5. Generate and run migration

**Acceptance Criteria:**
- `python manage.py migrate` runs without errors
- `python manage.py check` passes
- Both tables exist in DB with correct columns and FK constraints
- Unit tests: model instantiation, `__str__`, cascade delete behavior

---

### Task 2 — Serializers for Conversations & Messages

**Scope:** `src/backend/conversations/serializers.py`

**Serializers to implement:**

1. `MessageSerializer` — serializes a single message. Fields: `id`, `role`, `content`, `sources`, `token_usage`, `created_at`. Sources must serialize as the JSONB array defined in the schema.

2. `ConversationListSerializer` — for GET `/conversations` list response. Fields: `id`, `document_id`, `document_title` (via `conversation.document.title`), `title`, `message_count` (annotated), `created_at`, `updated_at`.

3. `ConversationDetailSerializer` — for GET `/conversations/{id}`. Includes nested `messages` via `MessageSerializer(many=True)`. Fields: all from list + `messages`.

4. `ConversationCreateSerializer` — for POST `/conversations`. Input fields: `document_id` (UUIDField), `title` (CharField, optional). Validates that `document_id` exists and belongs to the requesting user. Validate document `processing_status == 'completed'`.

5. `AskQuestionSerializer` — for POST `/conversations/{id}/messages`. Input field: `content` (CharField, required, min_length=1).

6. `DirectQuerySerializer` — for POST `/documents/{document_id}/query`. Input fields: `question` (CharField, required), `top_k` (IntegerField, default=5, min=1, max=20).

**Acceptance Criteria:**
- All serializers have unit tests with valid and invalid inputs
- `ConversationCreateSerializer.validate()` raises `ValidationError` if document doesn't exist, doesn't belong to user, or `processing_status != 'completed'`

---

### Task 3 — RAG Service Layer

**Scope:** `src/backend/conversations/rag_service.py`

This is the core business logic. No view logic here — pure service functions.

**Functions to implement:**

#### `build_context(chunks: list[dict]) -> str`
- Takes a list of chunk dicts (from search service: `chunk_id`, `content`, `page_start`, `page_end`, `relevance_score`)
- Returns a formatted context string for injection into the LLM prompt
- Format each chunk as:
  ```
  [Source {i+1} | Pages {page_start}-{page_end}]
  {content}
  ```
- Max total context: trim to fit within token budget (4000 tokens). Use `tiktoken` or simple char estimate (1 token ≈ 4 chars).

#### `build_system_prompt(document_title: str) -> str`
- Returns the system prompt string for the RAG chain
- Must include hallucination mitigation instruction: the assistant must only answer from provided context and must explicitly say "I don't have enough information in the document to answer this" if context is insufficient
- Must instruct the model to cite sources by referencing `[Source N]` markers

#### `extract_citations(content: str, chunks: list[dict]) -> list[dict]`
- Parses `[Source N]` references from assistant response
- Returns a list of citation dicts matching the `sources` JSONB schema:
  ```json
  {
    "chunk_id": "uuid",
    "page_start": 1,
    "page_end": 3,
    "content_preview": "first 200 chars...",
    "relevance_score": 0.93
  }
  ```
- Only includes chunks actually cited in the response

#### `run_rag_query(question: str, document_id: str, conversation_history: list[dict], top_k: int = 5) -> dict`
- Orchestrates the full RAG pipeline:
  1. Call `embed_query(question)` from embedding service (already exists from E05/E06)
  2. Call `search_chunks(document_id, query_embedding, top_k)` from search service (E06)
  3. Call `build_context(chunks)`
  4. Build messages array for OpenAI: system prompt + conversation history (last 10 turns max) + user question with context injected
  5. Call OpenAI `chat.completions.create` with `model=settings.OPENAI_CHAT_MODEL` (default: `gpt-4o-mini`)
  6. Call `extract_citations(response_content, chunks)`
  7. Return dict:
     ```python
     {
         "content": str,        # assistant response text
         "sources": list[dict], # citations
         "token_usage": {
             "prompt_tokens": int,
             "completion_tokens": int,
             "total_tokens": int
         },
         "raw_chunks": list[dict]  # all retrieved chunks (for storage)
     }
     ```
- Raises `RAGServiceException` (custom exception) on OpenAI API errors

**Settings to add in `settings.py`:**
```python
OPENAI_CHAT_MODEL = env("OPENAI_CHAT_MODEL", default="gpt-4o-mini")
OPENAI_CHAT_MAX_TOKENS = env.int("OPENAI_CHAT_MAX_TOKENS", default=1000)
RAG_MAX_HISTORY_TURNS = env.int("RAG_MAX_HISTORY_TURNS", default=10)
RAG_CONTEXT_TOKEN_BUDGET = env.int("RAG_CONTEXT_TOKEN_BUDGET", default=4000)
```

**Acceptance Criteria:**
- Unit tests with mocked OpenAI client and mocked search/embed services
- `run_rag_query` is tested for: normal response, citation extraction, history truncation, OpenAI error handling
- `extract_citations` is tested for: cited sources, uncited sources ignored, malformed references

---

### Task 4 — Conversation CRUD Views

**Scope:** `src/backend/conversations/views.py` (CRUD only, no RAG yet)

**Views to implement:**

#### `ConversationListCreateView` — handles POST + GET `/conversations`

**POST `/conversations`:**
- Auth: `IsAuthenticated`
- Use `ConversationCreateSerializer` for input validation
- Create `Conversation` object; set `user=request.user`
- Return `201 Created` with `ConversationDetailSerializer` (no messages yet, empty list)
- Error: `404` if document not found, `403` if document belongs to another user, `422` if document not completed

**GET `/conversations`:**
- Auth: `IsAuthenticated`
- Filter: `Conversation.objects.filter(user=request.user)`
- Optional filter: `?document_id=uuid`
- Annotate with `message_count=Count('messages')`
- Paginate: `page` + `page_size` (default 20, max 100)
- Return `ConversationListSerializer`

#### `ConversationDetailView` — handles GET + DELETE `/conversations/{conversation_id}`

**GET `/conversations/{conversation_id}`:**
- Auth: `IsAuthenticated`
- Fetch with `.prefetch_related('messages')`
- Ownership check: `conversation.user != request.user` → `403`
- Return `ConversationDetailSerializer`

**DELETE `/conversations/{conversation_id}`:**
- Auth: `IsAuthenticated`
- Ownership check → `403`
- `conversation.delete()` → `204 No Content`

**URL Registration:**
- Add `conversations/urls.py`
- Register in `config/urls.py`:
  ```python
  path('conversations/', include('conversations.urls')),
  ```

**Acceptance Criteria:**
- All 4 CRUD operations tested (happy path + auth errors + ownership errors)
- Pagination tested (next/previous links)
- `document_id` filter tested

---

### Task 5 — Ask Question View (Core RAG Endpoint)

**Scope:** `src/backend/conversations/views.py` — add `ConversationMessageView`

**POST `/conversations/{conversation_id}/messages`:**
- Auth: `IsAuthenticated`
- Validate: conversation exists + ownership check → `403`
- Use `AskQuestionSerializer` for input
- Persist the **user message** first:
  ```python
  Message.objects.create(
      conversation=conversation,
      role='user',
      content=validated_data['content']
  )
  ```
- Build `conversation_history` from `conversation.messages.all()` ordered by `created_at` — format as `[{"role": msg.role, "content": msg.content}, ...]`
- Call `run_rag_query(question, document_id, conversation_history, top_k=5)`
- Persist the **assistant message**:
  ```python
  Message.objects.create(
      conversation=conversation,
      role='assistant',
      content=result['content'],
      sources=result['sources'],
      token_usage=result['token_usage']
  )
  ```
- Touch `conversation.updated_at` (auto via `auto_now=True`, but explicitly call `conversation.save()` to trigger)
- Return `201 Created` with `MessageSerializer` of the assistant message
- Error handling:
  - `RAGServiceException` → `502 Bad Gateway` with `{"error": "rag_error", "message": "..."}`
  - OpenAI rate limit → `429` with retry-after hint

**Acceptance Criteria:**
- Unit tests with mocked `run_rag_query`
- Integration test: full conversation flow (create → ask → check messages persisted)
- Error cases: invalid conversation_id, ownership violation, RAG service failure

---

### Task 6 — Direct Query View (Stateless RAG Endpoint)

**Scope:** `src/backend/conversations/views.py` — add `DocumentDirectQueryView`

**POST `/documents/{document_id}/query`:**
- Auth: `IsAuthenticated`
- Ownership check on document → `403`
- Validate document `processing_status == 'completed'` → `422` if not
- Use `DirectQuerySerializer` for input: `question`, `top_k` (default 5)
- Call `run_rag_query(question, document_id, conversation_history=[], top_k=top_k)`
- **Do NOT persist any messages or conversations** — this is stateless
- Return `200 OK`:
  ```json
  {
    "answer": "...",
    "sources": [...],
    "token_usage": {...}
  }
  ```
- URL: Register under `documents/` URL namespace in `documents/urls.py`:
  ```python
  path('<uuid:document_id>/query/', DirectQueryView.as_view(), name='document-query'),
  ```

**Acceptance Criteria:**
- Unit tests with mocked `run_rag_query`
- Verify no `Message` or `Conversation` objects are created
- Test: document not found, document not completed, RAG failure

---

### Task 7 — Integration Tests & Final QA

**Scope:** `src/backend/conversations/tests/`

**Test files to create:**
- `test_models.py` — model creation, cascade delete, `__str__`
- `test_serializers.py` — all serializer validation cases
- `test_rag_service.py` — unit tests for all service functions (mocked external calls)
- `test_views_conversations.py` — CRUD view tests
- `test_views_messages.py` — ask-question endpoint tests
- `test_views_query.py` — stateless query endpoint tests
- `test_integration.py` — end-to-end: upload → process → embed → search → converse

**Coverage requirement:** ≥ 90% for the `conversations` app.

**Integration test scenario:**
1. Register user → get JWT
2. Upload + process + embed a test PDF (use fixtures)
3. Create conversation for that document
4. POST a question → assert assistant message returned with non-empty content and sources
5. GET conversation → assert 2 messages (user + assistant) in history
6. POST second question → assert history is passed to RAG (mock captures call args)
7. DELETE conversation → assert 204 + messages cascade-deleted

**Acceptance Criteria:**
- `pytest --cov=conversations --cov-report=term-missing` shows ≥ 90%
- All existing tests (E01–E06) still pass — no regressions
- `python manage.py check` passes clean

---

## Implementation Order

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7
```

Tasks 1 and 2 must be completed before any other task. Task 3 (service layer) must be complete before Tasks 5 and 6. Task 4 can be developed in parallel with Task 3.

---

## Environment Variables (add to `.env.example`)

```env
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_CHAT_MAX_TOKENS=1000
RAG_MAX_HISTORY_TURNS=10
RAG_CONTEXT_TOKEN_BUDGET=4000
```

---

## Constraints & Rules

- Follow TDD: write tests before or alongside implementation (per `.clinerules`)
- No business logic in views — all RAG logic lives in `rag_service.py`
- All responses must match the exact JSON schema in `api-registry.md`
- Do not modify existing models, migrations, or URLs from E01–E06
- `sources` field in `Message` must be stored as JSONB array, not as related model
- Conversation history passed to LLM must be capped at `RAG_MAX_HISTORY_TURNS` most recent turns (user+assistant pairs) to prevent context overflow
- The system prompt must always be the first message in the OpenAI messages array
- Never expose raw OpenAI errors to the client — wrap in `RAGServiceException`