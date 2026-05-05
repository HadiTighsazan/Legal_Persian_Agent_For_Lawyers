# Prompt for Code Mode — TASK 8: Accessibility, Polish & Error Boundaries

## Context

This is the final polish task for Epic E10 (Frontend Chat Interface). All previous tasks (T1–T7) are complete. The chat UI is fully functional with:

- [`ChatPage.tsx`](src/frontend/src/pages/ChatPage.tsx) — full-page chat with sidebar + chat window
- [`ChatWindow.tsx`](src/frontend/src/components/chat/ChatWindow.tsx) — orchestrator with message list, empty state, error alerts, skeleton loading
- [`MessageInput.tsx`](src/frontend/src/components/chat/MessageInput.tsx) — auto-growing textarea with send button
- [`MessageBubble.tsx`](src/frontend/src/components/chat/MessageBubble.tsx) — user/assistant message rendering with markdown + source citations
- [`ConversationSidebar.tsx`](src/frontend/src/components/chat/ConversationSidebar.tsx) — conversation list with create/rename/delete
- [`conversationStore.ts`](src/frontend/src/stores/conversationStore.ts) — Zustand store with optimistic updates
- [`App.tsx`](src/frontend/src/App.tsx) — routes for `/documents/:documentId/chat` and `/documents/:documentId/chat/:conversationId`
- [`DocumentDetailPage.tsx`](src/frontend/src/pages/documents/DocumentDetailPage.tsx) — "Chat with Document" button (visible when `document.status === 'completed'`)

## What to Do

### 1. Create `ChatErrorBoundary.tsx`

**File:** [`src/frontend/src/components/chat/ChatErrorBoundary.tsx`](src/frontend/src/components/chat/ChatErrorBoundary.tsx)

A React Error Boundary class component that wraps `ChatWindow`. On an unhandled JavaScript error in the chat component tree:

- Catch the error via `componentDidCatch` / `getDerivedStateFromError`
- Display a centered error state:
  - `AlertCircle` icon
  - "Something went wrong" heading
  - "An unexpected error occurred in the chat. Please try reloading." description
  - A "Reload" button that calls `window.location.reload()`
- Log the error to `console.error` for debugging

**Props:** `children: React.ReactNode`

**Pattern:** Class component (Error Boundaries require class lifecycle methods). Use TypeScript.

**Integration:** In [`ChatPage.tsx`](src/frontend/src/pages/ChatPage.tsx), wrap the `ChatWindow` usage (line 193) with `<ChatErrorBoundary>...</ChatErrorBoundary>`.

### 2. Audit & Fix ARIA Labels

Audit all chat components and add/improve ARIA labels where missing.

#### [`MessageInput.tsx`](src/frontend/src/components/chat/MessageInput.tsx)

- **Textarea** (line 88-101): Already has `aria-label="Message input"`. Change to `aria-label="Ask a question"` to be more descriptive.
- **Send button** (line 109-121): Already has `aria-label` that dynamically changes. Keep as-is — it's good.

#### [`ConversationSidebar.tsx`](src/frontend/src/components/chat/ConversationSidebar.tsx)

- **Sidebar container** (line 319): Add `role="navigation"` and `aria-label="Conversations"` to the root `<div>`.
- **Conversation items** (line 162-231): The `<div>` for each conversation item should have `role="button"` and `aria-label="Conversation: {title}"` (or "Conversation: Untitled Chat" if title is null).
- **Delete button** (line 218-227): Already has `aria-label="Delete conversation {title}"`. Good.
- **Rename button** (line 208-217): Already has `aria-label="Rename conversation {title}"`. Good.
- **"New Chat" button** (line 325-338): Add `aria-label="Create new conversation"`.

#### [`ChatWindow.tsx`](src/frontend/src/components/chat/ChatWindow.tsx)

- **Message list container** (line 183-201): Already has `role="log"`, `aria-live="polite"`, and `aria-busy={isSendingMessage}`. Keep as-is — it's correct.
- **Error alert** (line 103-121): The dismiss button already has `aria-label="Dismiss error"`. Good.
- **Starter chips** (line 55-71): Add `aria-label` to each starter chip button, e.g., `aria-label="Ask: {question}"`.

#### [`MessageBubble.tsx`](src/frontend/src/components/chat/MessageBubble.tsx)

- **User message bubble** (line 105-123): Add `aria-label="Your message"`.
- **Assistant message container** (line 105-123): Add `aria-label="AI response"`.
- **Source citations toggle** (line 45-54): Add `aria-expanded={open}` and `aria-controls="sources-{message.id}"` to the trigger. Add `id="sources-{message.id}"` to the collapsible content.

### 3. Focus Management

#### [`MessageInput.tsx`](src/frontend/src/components/chat/MessageInput.tsx)

The component already has focus management after send (lines 56-58 using `requestAnimationFrame`). Verify it works correctly:

- After `handleSubmit` clears the input, `textareaRef.current?.focus()` is called inside `requestAnimationFrame`.
- This is correct. No changes needed unless testing reveals issues.

### 4. Page Title

#### [`ChatPage.tsx`](src/frontend/src/pages/ChatPage.tsx)

Add a `useEffect` that sets `document.title` dynamically:

```typescript
useEffect(() => {
  const title = documentTitle
    ? `Chat — ${documentTitle} | DocuChat`
    : 'Chat | DocuChat';
  document.title = title;

  // Cleanup: restore default title on unmount
  return () => {
    document.title = 'DocuChat';
  };
}, [documentTitle]);
```

This should be placed after the `documentTitle` state and its fetching logic (around line 81).

### 5. Visual First — Manual Browser Accessibility Audit

After implementing all changes:

1. Rebuild the frontend container: `docker-compose up -d --build frontend`
2. Open the browser DevTools → Accessibility panel
3. Navigate to a chat page (e.g., `/documents/{id}/chat/{convId}`)
4. Verify:
   - Error Boundary: Temporarily throw an error in ChatWindow (e.g., add `throw new Error('test')` in a useEffect) and confirm the fallback UI appears with "Reload" button
   - ARIA labels are present on all interactive elements
   - Focus returns to textarea after sending a message
   - `aria-live="polite"` region announces new messages
   - Page title updates to "Chat — {document_title} | DocuChat"
5. Remove any test error throws before finalizing

### 6. Update `wip-context.md`

After completion, update [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md) with:
- What was completed (all 5 items above)
- Current state of code
- Next steps (if any remaining for E10)

## Files to Create

| # | File | Purpose |
|---|------|---------|
| 1 | `src/frontend/src/components/chat/ChatErrorBoundary.tsx` | Error Boundary class component |

## Files to Modify

| # | File | Changes |
|---|------|---------|
| 1 | `src/frontend/src/components/chat/MessageInput.tsx` | Update textarea `aria-label` to "Ask a question" |
| 2 | `src/frontend/src/components/chat/ConversationSidebar.tsx` | Add `role="navigation"`, `aria-label` on sidebar container, `role="button"` + `aria-label` on conversation items, `aria-label` on "New Chat" button |
| 3 | `src/frontend/src/components/chat/ChatWindow.tsx` | Add `aria-label` on starter chips |
| 4 | `src/frontend/src/components/chat/MessageBubble.tsx` | Add `aria-label` on user/assistant bubbles, `aria-expanded` + `aria-controls` on source toggle |
| 5 | `src/frontend/src/pages/ChatPage.tsx` | Add `useEffect` for dynamic `document.title`; wrap `ChatWindow` with `ChatErrorBoundary` |

## Execution Order

1. Create `ChatErrorBoundary.tsx`
2. Integrate Error Boundary in `ChatPage.tsx`
3. Add page title `useEffect` in `ChatPage.tsx`
4. Audit and fix ARIA labels in all chat components
5. Manual browser accessibility audit
6. Update `wip-context.md`

## Acceptance Criteria

- [ ] `ChatErrorBoundary.tsx` created — class component with `getDerivedStateFromError` + `componentDidCatch`
- [ ] Error Boundary shows "Something went wrong" + "Reload" button on crash
- [ ] Textarea has `aria-label="Ask a question"`
- [ ] Sidebar has `role="navigation"` + `aria-label="Conversations"`
- [ ] Conversation items have `role="button"` + `aria-label="Conversation: {title}"`
- [ ] "New Chat" button has `aria-label="Create new conversation"`
- [ ] Starter chips have `aria-label="Ask: {question}"`
- [ ] User message bubble has `aria-label="Your message"`
- [ ] Assistant message has `aria-label="AI response"`
- [ ] Source citations toggle has `aria-expanded` + `aria-controls`
- [ ] Focus returns to textarea after sending a message
- [ ] `document.title` updates to "Chat — {title} | DocuChat" when a conversation is active
- [ ] `document.title` resets to "DocuChat" on unmount
- [ ] `wip-context.md` updated
- [ ] No automated UI tests created (manual verification only)
