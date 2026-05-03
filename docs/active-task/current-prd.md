# PRD — Epic E10: Frontend Chat Interface
**Status:** Ready for Implementation  
**Epic ID:** E10  
**Depends On:** E08 (Auth & Layout ✅), E09 (Document Management ⏳), E07 (RAG Backend ✅)  
**Stack:** React + Vite + TypeScript + TailwindCSS + shadcn/ui  
**Test Strategy:** Visual First → Playwright (NO RTL, NO Vitest for UI)

---

## Scope

Build the full chat UI for the Document Q&A system. Users arrive at a document detail page, create or resume a conversation, send questions, and receive answers with source citations.

---

## API Endpoints Consumed (from `api-registry.md`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/conversations` | Create new conversation |
| GET | `/conversations` | List conversations (filter by `document_id`) |
| GET | `/conversations/{conversation_id}` | Load conversation + messages |
| DELETE | `/conversations/{conversation_id}` | Delete conversation |
| POST | `/conversations/{conversation_id}/messages/` | Send question → get answer |
| POST | `/documents/{document_id}/query` | Stateless direct query (no conversation) |

**No new API endpoints or DB tables are required for this Epic.**

---

## Database Impact

**None.** No schema changes. All persistence is handled by the backend.

---

## Micro-Tasks

---

### TASK 1 — Conversation API Service Layer
**Effort:** Small | **Test Type:** Vitest (pure non-UI logic)

**Goal:** Typed API client module for all conversation/message endpoints.

**File to Create:** `src/frontend/src/api/conversations.ts`

**Types to export:**
```typescript
export interface Conversation { id: string; document_id: string; document_title: string; title: string | null; message_count: number; created_at: string; updated_at: string; }
export interface MessageSource { chunk_id: string; page_start: number; page_end: number; content_preview: string; relevance_score: number; }
export interface Message { id: string; role: 'user' | 'assistant'; content: string; sources?: MessageSource[]; token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }; created_at: string; }
export interface ConversationDetail extends Conversation { messages: Message[]; }
export interface PaginatedConversations { count: number; next: string | null; previous: string | null; results: Conversation[]; }
```

**Functions to implement** (all use the existing `apiClient` from E08):
1. `createConversation(documentId: string, title?: string): Promise<Conversation>`
2. `listConversations(documentId?: string, page?: number): Promise<PaginatedConversations>`
3. `getConversation(conversationId: string): Promise<ConversationDetail>`
4. `deleteConversation(conversationId: string): Promise<void>`
5. `sendMessage(conversationId: string, content: string): Promise<Message>`
6. `directQuery(documentId: string, question: string, topK?: number): Promise<{ answer: string; sources: MessageSource[]; token_usage: object }>`

**TDD Steps:**
1. RED: Write `src/frontend/tests/api/conversations.test.ts` — mock `fetch`, assert correct URLs, HTTP methods, request bodies, and return types for all 6 functions.
2. GREEN: Implement `conversations.ts` to pass all tests.
3. REFACTOR: Extract shared error-handling logic.

**Acceptance Criteria:**
- [ ] All 6 functions call the correct endpoint with correct HTTP method
- [ ] Auth token is attached (via shared `apiClient`)
- [ ] Non-2xx responses throw a typed error
- [ ] No `any` types in the module
- [ ] Tests pass: `docker-compose exec frontend npx vitest run tests/api/conversations.test.ts`

---

### TASK 2 — Conversation Store (Zustand)
**Effort:** Small | **Test Type:** Vitest (pure non-UI logic)

**Goal:** Global state for conversations and messages. Manages loading, error, and optimistic message state.

**File to Create:** `src/frontend/src/stores/conversationStore.ts`

**State Shape:**
```typescript
interface ConversationState {
  conversations: Conversation[];
  activeConversation: ConversationDetail | null;
  isLoadingConversations: boolean;
  isLoadingMessages: boolean;
  isSendingMessage: boolean;
  error: string | null;
  // Actions
  fetchConversations: (documentId: string) => Promise<void>;
  createConversation: (documentId: string, title?: string) => Promise<Conversation>;
  loadConversation: (conversationId: string) => Promise<void>;
  sendMessage: (conversationId: string, content: string) => Promise<void>;
  deleteConversation: (conversationId: string) => Promise<void>;
  clearActiveConversation: () => void;
  clearError: () => void;
}
```

**Key Behavior:**
- `sendMessage` must perform **optimistic update**: append user message immediately to `activeConversation.messages` with a temp `id`, then append the real assistant response on success, or roll back + set `error` on failure.
- `createConversation` appends the new conversation to `conversations` without a full refetch.

**TDD Steps:**
1. RED: `src/frontend/tests/stores/conversationStore.test.ts` — mock the API module, test optimistic update, rollback on error, and all state transitions.
2. GREEN: Implement store.
3. REFACTOR: Ensure no direct `fetch` calls inside store — delegate to `conversations.ts`.

**Acceptance Criteria:**
- [ ] Optimistic user message appears before API responds
- [ ] On API error, optimistic message is removed and `error` is set
- [ ] `isSendingMessage` is `true` during the request and `false` after
- [ ] Store does not call `fetch` directly
- [ ] Tests pass: `docker-compose exec frontend npx vitest run tests/stores/conversationStore.test.ts`

---

### TASK 3 — ConversationSidebar Component
**Effort:** Medium | **Test Type:** Visual First → Playwright after approval

**Goal:** Left sidebar listing all conversations for the current document. Allows creating, selecting, and deleting conversations.

**File to Create:** `src/frontend/src/components/chat/ConversationSidebar.tsx`

**Props:**
```typescript
interface Props {
  documentId: string;
  activeConversationId: string | null;
  onSelect: (conversationId: string) => void;
}
```

**UI Requirements:**
1. **Header:** "Conversations" title + "New Chat" button (`PlusIcon` from lucide-react).
2. **List:** Each item shows `title` (or "Untitled Chat" if null) + `updated_at` as relative time ("2 hours ago") + a `Trash2` delete icon visible on hover.
3. **Active State:** Selected item: `bg-primary/10 text-primary` + left border accent.
4. **Empty State:** Centered text: "No conversations yet. Start by clicking 'New Chat'."
5. **Loading State:** 3 animate-pulse skeleton divs while `isLoadingConversations` is true.
6. **Delete Flow:** Inline confirmation (no modal): "Delete? [Yes] [No]" — Yes calls `deleteConversation`, No cancels.
7. **"New Chat" action:** Calls `createConversation(documentId)` then calls `onSelect` with new id.

**Styling:** Use shadcn/ui `ScrollArea` for the list. TailwindCSS only — no inline styles.

**Visual First Steps:**
1. Implement component. Wire to store.
2. Integrate into a test route or Document Detail page.
3. STOP — wait for user browser approval.
4. Write Playwright tests: `src/frontend/tests/components/ConversationSidebar.spec.ts`

**Playwright Test Scenarios (write AFTER approval):**
- [ ] Renders skeleton loaders while loading
- [ ] Renders conversation list after load
- [ ] Clicking conversation calls `onSelect`
- [ ] Hover reveals delete icon
- [ ] Delete confirmation — Yes deletes, No cancels
- [ ] "New Chat" creates conversation and triggers `onSelect`
- [ ] Empty state shown when list is empty

---

### TASK 4 — MessageBubble Component
**Effort:** Medium | **Test Type:** Visual First → Playwright after approval

**Goal:** Renders a single chat message for both user and assistant roles, with source citations.

**File to Create:** `src/frontend/src/components/chat/MessageBubble.tsx`

**Props:**
```typescript
interface Props {
  message: Message;
  isStreaming?: boolean;
}
```

**UI Requirements:**

**User Message:**
- Right-aligned bubble, `bg-primary text-primary-foreground`, `rounded-2xl rounded-tr-none`.

**Assistant Message:**
- Left-aligned, no bubble, full width.
- Render content as Markdown (`react-markdown` — install via `docker-compose exec frontend npm install react-markdown`).
- If `isStreaming=true`, append blinking cursor `▌` to end of content.

**Source Citations (assistant only, non-empty `sources`):**
- Collapsible section (default: collapsed) using shadcn/ui `Collapsible`.
- Toggle: "Show X sources ▼" / "Hide sources ▲".
- Each source rendered as shadcn/ui `Card`:
  - `📄 Pages {page_start}–{page_end}` and `Score: {Math.round(relevance_score * 100)}%`
  - `content_preview` as muted paragraph.

**Token Usage:** Tiny muted text below: `~{total_tokens.toLocaleString()} tokens used`.

**Timestamp:** Small muted text formatted as `HH:mm`.

**Visual First Steps:**
1. Install `react-markdown`.
2. Implement component with hardcoded mock props to verify layout.
3. STOP — wait for user browser approval.
4. Write Playwright tests: `src/frontend/tests/components/MessageBubble.spec.ts`

**Playwright Test Scenarios (write AFTER approval):**
- [ ] User message is right-aligned
- [ ] Assistant message renders markdown (bold, code blocks)
- [ ] Streaming cursor visible when `isStreaming=true`
- [ ] Sources section collapsed by default
- [ ] Sources expand on toggle click
- [ ] Source card shows correct page range and score percentage

---

### TASK 5 — MessageInput Component
**Effort:** Small | **Test Type:** Visual First → Playwright after approval

**Goal:** Auto-growing textarea at bottom of chat for composing and submitting questions.

**File to Create:** `src/frontend/src/components/chat/MessageInput.tsx`

**Props:**
```typescript
interface Props {
  onSend: (content: string) => void;
  isDisabled?: boolean;
  placeholder?: string;
}
```

**UI Requirements:**
1. shadcn/ui `Textarea` — auto-grows up to 5 lines, then scrolls.
2. Send button (`SendHorizontal` icon) — disabled when input is empty OR `isDisabled=true`.
3. `Enter` submits. `Shift+Enter` adds newline.
4. After send: input clears, focus returns to textarea.
5. While `isDisabled`: textarea disabled, send button shows `Loader2` spinner (`animate-spin`), placeholder = "Waiting for response...".
6. Character counter `X / 10,000` appears in muted text bottom-right when length > 500.

**Visual First Steps:**
1. Implement component.
2. STOP — wait for user browser approval.
3. Write Playwright tests: `src/frontend/tests/components/MessageInput.spec.ts`

**Playwright Test Scenarios (write AFTER approval):**
- [ ] Enter key submits and clears input
- [ ] Shift+Enter adds newline without submitting
- [ ] Send button disabled when empty
- [ ] Spinner shown when `isDisabled=true`
- [ ] Counter appears after 500 chars
- [ ] Counter hidden below 500 chars

---

### TASK 6 — ChatWindow Component (Orchestrator)
**Effort:** Large | **Test Type:** Visual First → Playwright after approval

**Goal:** Main chat panel. Composes `MessageBubble` + `MessageInput`. Manages scroll, loading, and error states.

**File to Create:** `src/frontend/src/components/chat/ChatWindow.tsx`

**Props:**
```typescript
interface Props { conversationId: string; }
```

**UI Requirements:**

1. **Initial Load:** Calls `loadConversation(conversationId)` on mount and on `conversationId` change. Shows full-panel skeleton while `isLoadingMessages`.

2. **Message List:**
   - shadcn/ui `ScrollArea`.
   - Renders `MessageBubble` per message.
   - Last assistant message gets `isStreaming={isSendingMessage}`.
   - **Auto-scroll:** `useEffect` + `messagesEndRef` div — scroll to bottom on every new message.

3. **Empty State (0 messages):**
   - Centered: large document icon + "Ask your first question about this document".
   - 3 clickable starter chips: "What is the main conclusion?", "Summarize the key findings.", "What methodology was used?"
   - Clicking a chip populates `MessageInput`.

4. **Sending Flow:**
   - `onSend` triggers `store.sendMessage(conversationId, content)`.
   - Optimistic user message appears immediately.
   - Temporary `MessageBubble` with `isStreaming=true` and empty content shows as last item.

5. **Error Handling (non-blocking `Alert` above input):**
   - `429`: "Rate limit reached. Please wait a moment."
   - `502`: "The AI service is temporarily unavailable."
   - Other: generic error message.
   - "Try again" button calls `store.clearError()`.

**Visual First Steps:**
1. Implement. Wire to store.
2. STOP — wait for user browser approval.
3. Write Playwright tests: `src/frontend/tests/components/ChatWindow.spec.ts`

**Playwright Test Scenarios (write AFTER approval):**
- [ ] Loading skeleton shown on mount
- [ ] Messages render after load
- [ ] Optimistic user bubble appears immediately on send
- [ ] Streaming "thinking" bubble appears while waiting
- [ ] Auto-scroll to bottom on new message
- [ ] Empty state shows starter chips
- [ ] Clicking chip populates input
- [ ] Error alert appears on 502 response
- [ ] Rate limit error shows correct message
- [ ] "Try again" dismisses error

---

### TASK 7 — ChatPage Route & Layout Integration
**Effort:** Medium | **Test Type:** Visual First → Playwright E2E after approval

**Goal:** Full-page chat route. Integrates `ConversationSidebar` + `ChatWindow` into router and layout shell.

**Files to Create/Modify:**
- `src/frontend/src/pages/ChatPage.tsx` ← **create**
- `src/frontend/src/router.tsx` (or `App.tsx`) ← **modify** to add route
- `src/frontend/src/pages/DocumentDetailPage.tsx` ← **modify** to add "Chat" button

**Route:** `/documents/:documentId/chat` and `/documents/:documentId/chat/:conversationId`

**Two-panel layout:**
```
┌─────────────────────────────────────────────────────┐
│  App Header (from E08 layout shell)                  │
├───────────────┬─────────────────────────────────────┤
│               │                                     │
│  Conversation │           Chat Window               │
│   Sidebar     │                                     │
│   (250px)     │                                     │
│               │                                     │
└───────────────┴─────────────────────────────────────┘
```

**Behavior:**
- On mount: load conversations for `documentId`.
- If `conversationId` URL param exists, immediately load that conversation.
- Selecting conversation in sidebar navigates to `/documents/:documentId/chat/:conversationId` via `useNavigate`.
- **Mobile (< `md`):** Sidebar hidden; "☰ Chats" button in chat header opens a slide-over drawer.

**DocumentDetailPage change:**
- Add "Chat with Document" button (`MessageSquare` icon) — only visible when `document.status === 'completed'`.
- Links to `/documents/:documentId/chat`.

**Visual First Steps:**
1. Implement `ChatPage.tsx` and update router.
2. Add "Chat with Document" link in `DocumentDetailPage`.
3. STOP — wait for user browser approval of full flow.
4. Write E2E tests: `src/frontend/tests/e2e/chat.spec.ts`

**Playwright E2E Test Scenarios (write AFTER approval):**
- [ ] `/documents/:id/chat` renders two-panel layout
- [ ] Sidebar shows existing conversations
- [ ] "New Chat" creates conversation and loads ChatWindow
- [ ] Full send → receive message flow end-to-end
- [ ] Refreshing page with `conversationId` in URL restores conversation
- [ ] "Chat with Document" button absent when `status !== 'completed'`
- [ ] Mobile: sidebar hidden by default, opens on "Chats" button click

---

### TASK 8 — Accessibility, Polish & Error Boundaries
**Effort:** Small | **Test Type:** Visual First → Playwright after approval

**Goal:** Production-readiness pass. Error boundaries, ARIA, focus management.

**Files to Create/Modify:**
- `src/frontend/src/components/chat/ChatErrorBoundary.tsx` ← **create**
- All chat components ← **audit and fix**

**Requirements:**
1. **Error Boundary:** Wrap `ChatWindow`. On crash: "Something went wrong in the chat. [Reload]".
2. **ARIA Labels:**
   - Textarea: `aria-label="Ask a question"`
   - Send button: `aria-label="Send message"`
   - Sidebar items: `aria-label="Conversation: {title}"`
   - Delete button: `aria-label="Delete conversation {title}"`
3. **Focus Management:** After sending, focus returns to textarea automatically.
4. Message list container: `aria-live="polite"` + `aria-busy="true"` while loading.
5. **Page Title:** `document.title = "Chat — {document_title} | DocuChat"` when active.

**Visual First Steps:**
1. Implement all changes.
2. STOP — manual browser accessibility audit.
3. Write Playwright accessibility tests after approval.

---

## Execution Order

```
T1 (API Layer) → T2 (Store) → T3, T4, T5 (parallel) → T6 (ChatWindow) → T7 (Page) → T8 (Polish)
```

- T1 and T2: start immediately (pure logic).
- T3, T4, T5: independent of each other, start after T2.
- T6: requires T3 + T4 + T5.
- T7: requires T6.
- T8: requires T7.

---

## Epic Completion Checklist

- [ ] T1: Conversation API module — typed, Vitest-tested
- [ ] T2: Zustand store with optimistic updates — Vitest-tested
- [ ] T3: ConversationSidebar — approved, Playwright-tested
- [ ] T4: MessageBubble with markdown + citations — approved, Playwright-tested
- [ ] T5: MessageInput with keyboard behavior — approved, Playwright-tested
- [ ] T6: ChatWindow orchestrator — approved, Playwright-tested
- [ ] T7: ChatPage route + integration — approved, E2E Playwright-tested
- [ ] T8: Error boundary + accessibility — approved, Playwright-tested
- [ ] No `any` TypeScript types in new files
- [ ] No React Testing Library used anywhere
- [ ] All tests pass: `docker-compose exec frontend npx playwright test`
- [ ] `wip-context.md` updated after every micro-task
- [ ] No DB schema changes, no new API endpoints

---
*Generated by Architect AI — Save to `docs/active-task/current-prd.md`*