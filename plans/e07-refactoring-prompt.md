# E07 Refactoring — Conversation & Q&A Engine

## Objective

Apply 9 targeted refactoring changes to the E07 (Conversation & Q&A Engine) code. All existing tests must continue to pass after the changes.

## Files to Modify

1. `src/backend/conversations/rag_service.py`
2. `src/backend/conversations/views.py`
3. `src/backend/config/settings.py`
4. `src/backend/.env.example` (if `OPENAI_CHAT_MAX_TOKENS` is referenced there)

## Changes

### Change 1 — Move lazy import to top level in `rag_service.py`

**File:** `src/backend/conversations/rag_service.py`

**What:** Move `from documents.models import Document` from inside `_get_document_title()` to the top-level imports (near line 18, after the existing `from providers.registry import get_chat_provider`).

**Why:** Lazy imports inside hot-path functions add overhead and obscure module dependencies.

**Before (lines 267-269):**
```python
def _get_document_title(document_id: str) -> str:
    try:
        from documents.models import Document
        return str(Document.objects.values_list("title", flat=True).get(id=document_id))
    except Exception:
        ...
```

**After:**
- Add `from documents.models import Document` at the top of the file (after line 18).
- Remove the lazy import from inside `_get_document_title()`.

---

### Change 2 — Narrow exception handling in `_get_document_title()`

**File:** `src/backend/conversations/rag_service.py`

**What:** Change `except Exception` to `except Document.DoesNotExist` in `_get_document_title()`.

**Why:** Catching all exceptions silently swallows real errors (DB connection failures, etc.). Only `DoesNotExist` is expected here.

**Before:**
```python
    try:
        return str(Document.objects.values_list("title", flat=True).get(id=document_id))
    except Exception:
        logger.warning(...)
        return "Unknown Document"
```

**After:**
```python
    try:
        return str(Document.objects.values_list("title", flat=True).get(id=document_id))
    except Document.DoesNotExist:
        logger.warning(...)
        return "Unknown Document"
```

---

### Change 3 — Eliminate double DB query in `ConversationDetailView.get()`

**File:** `src/backend/conversations/views.py`

**What:** Refactor `ConversationDetailView.get()` to avoid fetching the conversation twice. The helper `_get_conversation_or_error()` already fetches it once, then `get()` re-fetches it with `prefetch_related` and `annotate`.

**Option A (Recommended):** Modify `_get_conversation_or_error()` to accept an optional `prefetch_related` parameter, or create a separate `_get_conversation_detail()` method.

**Option B (Simpler):** Inline the ownership check in `get()` and do a single query with `prefetch_related` + `annotate` + ownership check.

**Before (lines 203-218):**
```python
def get(self, request: Request, conversation_id: str) -> Response:
    conversation, error = self._get_conversation_or_error(conversation_id, request)
    if error:
        return error

    # Prefetch messages and annotate message_count
    conversation = Conversation.objects.prefetch_related("messages").annotate(
        message_count=Count("messages"),
    ).get(id=conversation.id)

    serializer = ConversationDetailSerializer(conversation)
    return Response(serializer.data, status=status.HTTP_200_OK)
```

**After (Option B):**
```python
def get(self, request: Request, conversation_id: str) -> Response:
    try:
        conversation = Conversation.objects.prefetch_related("messages").annotate(
            message_count=Count("messages"),
        ).get(id=conversation_id)
    except Conversation.DoesNotExist:
        return Response(
            {"error": "not_found", "message": "Conversation not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    if conversation.user != request.user:
        return Response(
            {"error": "permission_denied", "message": "You do not have permission to access this conversation."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = ConversationDetailSerializer(conversation)
    return Response(serializer.data, status=status.HTTP_200_OK)
```

---

### Change 4 — Reuse `_get_conversation_or_error` in `ConversationMessageView`

**File:** `src/backend/conversations/views.py`

**What:** Replace the inline ownership check in `ConversationMessageView.post()` with a call to the existing `_get_conversation_or_error()` helper.

**Before (lines 272-287):**
```python
try:
    conversation = Conversation.objects.get(id=conversation_id)
except Conversation.DoesNotExist:
    return Response(
        {"error": "not_found", "message": "Conversation not found"},
        status=status.HTTP_404_NOT_FOUND,
    )

if conversation.user != request.user:
    return Response(
        {"error": "permission_denied", "message": "You do not have permission to access this conversation."},
        status=status.HTTP_403_FORBIDDEN,
    )
```

**After:**
```python
conversation, error = self._get_conversation_or_error(conversation_id, request)
if error:
    return error
```

**Note:** `ConversationMessageView` doesn't have `_get_conversation_or_error` — it's on `ConversationDetailView`. You'll need to either:
- Make it a module-level function, or
- Create a mixin, or
- Add the same method to `ConversationMessageView`

**Recommendation:** Extract `_get_conversation_or_error` as a **standalone module-level function** in `views.py` (not a method), so both views can use it.

---

### Change 5 — Replace manual pagination with DRF `PageNumberPagination`

**File:** `src/backend/conversations/views.py`

**What:** Replace the hand-rolled pagination logic in `ConversationListCreateView.get()` with DRF's built-in `PageNumberPagination`.

**Steps:**
1. Create a `ConversationPagination(PageNumberPagination)` class (can be in the same file or a separate `pagination.py`).
2. Set `page_size = 20`, `page_size_query_param = 'page_size'`, `max_page_size = 100`.
3. Assign `pagination_class = ConversationPagination` on the view (or call it manually in `get()`).
4. Remove the manual `page`/`page_size` parsing, bounds checking, and `next`/`previous` calculation.

**Before (lines 110-140):**
```python
try:
    page = int(request.query_params.get("page", 1))
    page_size = int(request.query_params.get("page_size", 20))
except (ValueError, TypeError):
    page, page_size = 1, 20

if page < 1:
    page = 1
if page_size < 1:
    page_size = 20
if page_size > 100:
    page_size = 100

total = queryset.count()
start = (page - 1) * page_size
end = start + page_size
page_conversations = queryset[start:end]

serializer = ConversationListSerializer(page_conversations, many=True)

total_pages = (total + page_size - 1) // page_size if total > 0 else 0

return Response(
    {
        "count": total,
        "next": page + 1 if page < total_pages else None,
        "previous": page - 1 if page > 1 else None,
        "results": serializer.data,
    },
    status=status.HTTP_200_OK,
)
```

**After:**
```python
paginator = ConversationPagination()
page = paginator.paginate_queryset(queryset, request)
serializer = ConversationListSerializer(page, many=True)
return paginator.get_paginated_response(serializer.data)
```

---

### Change 6 — Use running total in `build_context()` loop

**File:** `src/backend/conversations/rag_service.py`

**What:** Replace `sum(len(p) for p in context_parts)` with a running `total_chars` counter.

**Why:** O(n²) → O(n).

**Before (lines 55-70):**
```python
context_parts: list[str] = []

for i, chunk in enumerate(chunks):
    header = f"[Source {i + 1} | Pages {chunk['page_start']}-{chunk['page_end']}]"
    part = f"{header}\n{chunk['content']}"

    current_len = sum(len(p) for p in context_parts)
    if current_len + len(part) > max_chars:
        remaining = max_chars - current_len
        ...
    context_parts.append(part)
```

**After:**
```python
context_parts: list[str] = []
total_chars = 0

for i, chunk in enumerate(chunks):
    header = f"[Source {i + 1} | Pages {chunk['page_start']}-{chunk['page_end']}]"
    part = f"{header}\n{chunk['content']}"

    if total_chars + len(part) > max_chars:
        remaining = max_chars - total_chars
        ...
    context_parts.append(part)
    total_chars += len(part)
```

---

### Change 7 — Use `.get()` with defaults for chunk dict access in `build_context()`

**File:** `src/backend/conversations/rag_service.py`

**What:** Use `.get()` with sensible defaults instead of direct key access for `chunk['page_start']`, `chunk['page_end']`, and `chunk['content']`.

**Why:** Prevents `KeyError` if the chunk dict shape changes in the future.

**Before (line 56):**
```python
header = f"[Source {i + 1} | Pages {chunk['page_start']}-{chunk['page_end']}]"
part = f"{header}\n{chunk['content']}"
```

**After:**
```python
page_start = chunk.get("page_start", "?")
page_end = chunk.get("page_end", "?")
content = chunk.get("content", "")
header = f"[Source {i + 1} | Pages {page_start}-{page_end}]"
part = f"{header}\n{content}"
```

---

### Change 8 — Add `RateLimitError` to provider layer (Optional / Low Priority)

**File:** `src/backend/providers/base.py` and `src/backend/conversations/views.py`

**What:** 
1. Add a `RateLimitError` exception class to `providers/base.py`.
2. Update chat providers (OpenAI, Gemini, Ollama) to raise `RateLimitError` when they detect a 429/rate-limit response.
3. Update `views.py` to catch `RateLimitError` instead of doing string matching on error messages.

**In `providers/base.py`:**
```python
class ProviderError(Exception):
    """Base exception for all provider errors."""
    pass

class RateLimitError(ProviderError):
    """Raised when the provider returns a rate-limit response."""
    pass
```

**In `views.py` (lines 326-334 and 446-454):**
```python
except RAGServiceException as e:
    if isinstance(e.__cause__, RateLimitError):
        return Response(
            {"error": "rate_limit_exceeded", ...},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
```

---

### Change 9 — Rename `OPENAI_CHAT_MAX_TOKENS` → `CHAT_MAX_TOKENS`

**File:** `src/backend/config/settings.py` and `src/backend/conversations/rag_service.py`

**What:** Rename the setting since the project supports multiple chat providers (OpenAI, Gemini, Ollama), not just OpenAI.

**In `settings.py`:**
```python
# Before
OPENAI_CHAT_MAX_TOKENS = env.int("OPENAI_CHAT_MAX_TOKENS", default=1000)

# After
CHAT_MAX_TOKENS = env.int("CHAT_MAX_TOKENS", default=1000)
```

**In `rag_service.py:235`:**
```python
# Before
max_tokens=settings.OPENAI_CHAT_MAX_TOKENS,

# After
max_tokens=settings.CHAT_MAX_TOKENS,
```

**Also update:** `.env.example` if it references `OPENAI_CHAT_MAX_TOKENS`.

---

## Testing

After all changes, run the existing tests to verify nothing is broken:

```bash
docker-compose exec backend pytest src/backend/conversations/tests/ -v
```

All tests must pass. If any test fails, revert the change that caused the failure and investigate.

## WIP Update

After completing all changes, update `docs/active-task/wip-context.md` with:
1. What was completed (list of changes applied)
2. Current state of the code
3. Any remaining items (e.g., Change 8 if skipped)
