# Plan: Remove "سند جاری" (Current Document) Mode from Legal Research Page

## Objective

Remove the "سند جاری" (`local_rag`) mode toggle from the `/legal-research` page so that it only uses "تحقیق سراسری" (`global_rag`) mode. The Document Chat page (`/documents/:documentId/chat`) remains unchanged and continues to use `local_rag` for document-specific Q&A.

## Background

The current `/legal-research` page (`GlobalRagChatPage`) has a `ModeSelector` component that lets users toggle between:
- **سند جاری** (`local_rag`) — search within a specific document
- **تحقیق سراسری** (`global_rag`) — search across all legal knowledge hubs

The user wants to remove the "سند جاری" option from this page entirely. The `/legal-research` page should always use `global_rag` mode. The Document Chat page (`/documents/:documentId/chat`) already uses `local_rag` exclusively and should remain untouched.

## Architecture Analysis

### Current Flow

```
GlobalRagChatPage (/legal-research)
  ├── ModeSelector (toggle: local_rag | global_rag)
  ├── ChatWindow (reads ragMode from store)
  │     └── sendMessageStream(conversationId, content, ragMode)
  └── ConversationSidebar (creates conversations without documentId)

ChatPage (/documents/:documentId/chat)
  └── ChatWindow (reads ragMode from store, defaults to 'local_rag')
        └── sendMessageStream(conversationId, content, ragMode)
```

### Key Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `src/frontend/src/components/rag/ModeSelector.tsx` | **DELETE** entire file |
| 2 | `src/frontend/src/pages/GlobalRagChatPage.tsx` | Remove `ModeSelector` import and usage; hardcode `global_rag` mode |
| 3 | `src/frontend/src/components/chat/ChatWindow.tsx` | Accept `mode` as prop instead of reading from store |
| 4 | `src/frontend/src/stores/conversationStore.ts` | Remove `ragMode`, `setRagMode`, and related state |
| 5 | `src/backend/conversations/serializers.py` | Change default `mode` from `local_rag` to `global_rag` |
| 6 | `src/backend/conversations/views.py` | Remove `local_rag` validation check for conversations without documents |
| 7 | `src/backend/conversations/tests/test_serializers.py` | Update test for default mode |
| 8 | `src/backend/conversations/tests/test_views_messages.py` | Update test for default mode |

## Detailed Implementation Steps

### Step 1: Delete `ModeSelector.tsx`

**File:** `src/frontend/src/components/rag/ModeSelector.tsx`

Delete the entire file. This component is only used in `GlobalRagChatPage`.

### Step 2: Update `GlobalRagChatPage.tsx`

**File:** `src/frontend/src/pages/GlobalRagChatPage.tsx`

Changes:
1. Remove the `ModeSelector` import (line 14)
2. Remove the `<ModeSelector />` JSX element (line 137)
3. In `NoConversationSelected` sub-component, the `createConversation` call already omits `documentId` — this creates a Global RAG conversation (correct, no change needed)
4. Pass `mode="global_rag"` to `ChatWindow` as a prop

```tsx
// Before (line 169):
<ChatWindow conversationId={conversationId} />

// After:
<ChatWindow conversationId={conversationId} mode="global_rag" />
```

### Step 3: Update `ChatWindow.tsx`

**File:** `src/frontend/src/components/chat/ChatWindow.tsx`

Changes:
1. Accept `mode` as a prop instead of reading `ragMode` from the store
2. Remove `ragMode` from store selectors
3. Use the prop in `handleSend`, `handleRetry`, and placeholder logic

```tsx
// New interface:
interface ChatWindowProps {
  conversationId: string;
  mode?: 'local_rag' | 'global_rag';
}
```

Default `mode` to `'local_rag'` for backward compatibility (used by `ChatPage`).

### Step 4: Update `ChatPage.tsx`

**File:** `src/frontend/src/pages/ChatPage.tsx`

Changes:
1. Pass `mode="local_rag"` to `ChatWindow` explicitly

```tsx
// Before (line 208):
<ChatWindow conversationId={conversationId} />

// After:
<ChatWindow conversationId={conversationId} mode="local_rag" />
```

### Step 5: Update `conversationStore.ts`

**File:** `src/frontend/src/stores/conversationStore.ts`

Changes:
1. Remove `ragMode` from `ConversationState` interface
2. Remove `setRagMode` from `ConversationActions` interface
3. Remove `ragMode: 'local_rag'` from `initialState`
4. Remove the `setRagMode` function implementation
5. Keep `mode?: RagMode` parameter on `sendMessage` and `sendMessageStream` — these are passed through to the API

### Step 6: Update Backend `AskQuestionSerializer`

**File:** `src/backend/conversations/serializers.py`

Change the default `mode` from `"local_rag"` to `"global_rag"`:

```python
mode = serializers.ChoiceField(
    choices=MODE_CHOICES,
    default="global_rag",  # Changed from "local_rag"
    required=False,
    ...
)
```

Keep both choices in `MODE_CHOICES` for backward compatibility (document chat still sends `local_rag`).

### Step 7: Update Backend Views

**File:** `src/backend/conversations/views.py`

In both `ConversationMessageView.post()` (line 356) and `ConversationMessageStreamView.post()` (line 509):

Remove the validation check that rejects `local_rag` mode for conversations without documents. Since the frontend no longer sends `local_rag` for legal research conversations, this check is no longer needed. However, keep it as a safety net — or simplify it to just always route to `global_rag` when `conversation.document is None`.

Actually, the cleanest approach: since `local_rag` is no longer sent from the legal research page, we can keep the validation as-is for safety. The only change needed is the serializer default.

### Step 8: Update Backend Tests

**File:** `src/backend/conversations/tests/test_serializers.py`

Update `test_default_mode_is_local_rag` to `test_default_mode_is_global_rag`:

```python
def test_default_mode_is_global_rag(self) -> None:
    """Omitting ``mode`` should default to ``'global_rag'``."""
    serializer = AskQuestionSerializer(data={"content": "Test question"})
    self.assertTrue(serializer.is_valid())
    self.assertEqual(serializer.validated_data["mode"], "global_rag")
```

**File:** `src/backend/conversations/tests/test_views_messages.py`

Update `test_default_mode_is_local_rag` to expect `global_rag` as the default.

## Files NOT Modified

These files are intentionally left unchanged:

- `src/frontend/src/api/conversations.ts` — The `RagMode` type and API functions remain unchanged; they're still used by `ChatWindow` and the store's `sendMessage`/`sendMessageStream`
- `src/frontend/src/components/rag/GlobalRagEmptyState.tsx` — Already global_rag focused, no changes needed
- `src/frontend/src/components/rag/HubStatusBadge.tsx` — Not related to mode selection
- `src/backend/conversations/global_rag_service.py` — The core global RAG pipeline is untouched
- `src/backend/conversations/rag_service.py` — The local RAG pipeline is untouched (still used by document chat)
- `src/backend/conversations/models.py` — No schema changes needed
- `src/backend/conversations/urls.py` — No routing changes needed
- `src/frontend/src/App.tsx` — Routes remain the same
- `src/frontend/src/components/layout/Sidebar.tsx` — Navigation remains the same

## Verification Checklist

After implementation, verify:

1. [ ] `/legal-research` page loads without the ModeSelector toggle
2. [ ] `/legal-research` page header shows "Legal Research" without mode buttons
3. [ ] Sending a message on `/legal-research` calls `run_global_rag_query` (not `run_rag_query`)
4. [ ] `/documents/:documentId/chat` still works with `local_rag` mode
5. [ ] No console errors related to missing `ragMode` in store
6. [ ] All existing backend tests pass
7. [ ] All existing frontend tests pass

## Rollback Plan

If issues arise:
1. Restore `ModeSelector.tsx` from git history
2. Revert `GlobalRagChatPage.tsx` changes
3. Revert `ChatWindow.tsx` prop changes
4. Revert store changes
5. Revert serializer default
