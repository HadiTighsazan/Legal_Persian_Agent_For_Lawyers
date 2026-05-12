# WIP Context — Phase 3 Implementation (Frontend UI Refactoring & Global RAG Chat Interface)

## Status: ✅ COMPLETED (2026-05-12)

## Summary

Implemented Phase 3 — Frontend UI Refactoring & Global RAG Chat Interface. This phase made `Conversation.document` nullable in the backend to support Global RAG conversations (no document needed), updated the frontend API types and store to support optional document IDs and RAG mode selection, created new frontend components (`GlobalRagChatPage`, `ModeSelector`, `HubStatusBadge`, `GlobalRagEmptyState`), added new routes (`/legal-research`, `/legal-research/:conversationId`), refactored existing components (`ChatWindow`, `MessageInput`, `MessageBubble`, `ConversationSidebar`), and updated `Sidebar`, `DashboardPage`, and `App.tsx`. All 200 non-pre-existing backend tests pass and all 93 frontend tests pass.

---

## What Was Built

### Step 1: Backend — Make Conversation.document Nullable

**Files modified:**
- [`src/backend/conversations/models.py`](src/backend/conversations/models.py) — Made `document` ForeignKey nullable (`null=True, blank=True`). Updated `__str__` to handle null document (returns `"Global RAG Conversation ({user.email})"` when no document).
- [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) — `ConversationListSerializer`: Added `allow_null=True` to `document_id` and `document_title`. `ConversationCreateSerializer`: Made `document_id` optional (`required=False`), updated `validate_document_id` to return `None` when value is `None`.
- [`src/backend/conversations/views.py`](src/backend/conversations/views.py) — `ConversationListCreateView.post()`: Changed `validated_data["document_id"]` to `validated_data.get("document_id")`, added conditional logging. `ConversationMessageView.post()` and `ConversationMessageStreamView.post()`: Added validation that `local_rag` mode requires a document (returns 400 if document is None).

**Migration:**
- [`src/backend/conversations/migrations/0003_make_document_nullable.py`](src/backend/conversations/migrations/0003_make_document_nullable.py) — Created migration to make `document_id` nullable. Depends on `('documents', '0015_document_hub_type_documentchunk_hub_type_and_more')`.

### Step 2: Frontend — API Types & Store Updates

**File:** [`src/frontend/src/api/conversations.ts`](src/frontend/src/api/conversations.ts)

Changes:
- Added `RagMode` type: `export type RagMode = 'local_rag' | 'global_rag';`
- Made `document_id` and `document_title` nullable in `Conversation` and `ConversationDetail` interfaces
- Made `documentId` optional in `createConversation` function
- Added `mode?: RagMode` parameter to `sendMessage` and `sendMessageStream` functions

**File:** [`src/frontend/src/stores/conversationStore.ts`](src/frontend/src/stores/conversationStore.ts)

Changes:
- Added `ragMode: RagMode` to `ConversationState`
- Added `setRagMode: (mode: RagMode) => void` to `ConversationActions`
- Made `documentId` optional in `fetchConversations` and `createConversation`
- Added `mode?: RagMode` to `sendMessage` and `sendMessageStream`
- Added `ragMode: 'local_rag'` to `initialState`
- Passes `mode` to `apiSendMessage` and `apiSendMessageStream` calls
- Added `setRagMode` action implementation

### Step 3: New Frontend Components

**File:** [`src/frontend/src/components/rag/ModeSelector.tsx`](src/frontend/src/components/rag/ModeSelector.tsx)

Toggle component that switches between `local_rag` (سند جاری) and `global_rag` (تحقیق سراسری). Uses `useConversationStore` to read/set `ragMode`. Styled as a segmented control with radio role. Shows a brief description below the toggle explaining each mode.

**File:** [`src/frontend/src/components/rag/HubStatusBadge.tsx`](src/frontend/src/components/rag/HubStatusBadge.tsx)

Badge component showing hub type with color coding:
- `legislation` → blue (`bg-blue-100`, `text-blue-800`)
- `judicial_precedent` → emerald (`bg-emerald-100`, `text-emerald-800`)
- `advisory_opinion` → orange (`bg-orange-100`, `text-orange-800`)

Uses Lucide icons per hub type (`Scale`, `Gavel`, `BookOpen`). Supports dark mode with `dark:` variants.

**File:** [`src/frontend/src/components/rag/GlobalRagEmptyState.tsx`](src/frontend/src/components/rag/GlobalRagEmptyState.tsx)

Empty state for Global RAG chat with:
- Hub overview cards (3 cards showing legislation, judicial precedent, advisory opinion with icons and descriptions in Persian)
- 4 suggested questions in Persian (e.g., "مجازات جعل اسناد رسمی چیست؟")
- Accepts `onSend` callback for suggested questions

### Step 4: Page & Routing

**File:** [`src/frontend/src/pages/GlobalRagChatPage.tsx`](src/frontend/src/pages/GlobalRagChatPage.tsx)

Full chat page for legal research (no `documentId` needed). Includes:
- `ModeSelector` in the desktop header
- `ConversationSidebar` without `documentId` prop
- Responsive layout with mobile sidebar drawer
- Routes: `/legal-research` and `/legal-research/:conversationId`

**File:** [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx)

Added routes:
- `/legal-research` → `GlobalRagChatPage` (outside AppShell)
- `/legal-research/:conversationId` → `GlobalRagChatPage` (outside AppShell)

**File:** [`src/frontend/src/components/layout/Sidebar.tsx`](src/frontend/src/components/layout/Sidebar.tsx)

Added "Legal Research" nav item with `Search` icon, href `/legal-research`. Updated `isActive` logic to handle `/legal-research` prefix matching.

**File:** [`src/frontend/src/pages/DashboardPage.tsx`](src/frontend/src/pages/DashboardPage.tsx)

Added "Quick Actions" section with:
- Legal Research card (Search icon, navigates to `/legal-research`)
- Document Chat card (FileText icon, navigates to `/documents`)
- Added "Overview" heading above stat cards

### Step 5: Component Refactoring

**File:** [`src/frontend/src/components/chat/ConversationSidebar.tsx`](src/frontend/src/components/chat/ConversationSidebar.tsx)

Made `documentId` optional in `ConversationSidebarProps`. When `documentId` is undefined, `fetchConversations` is called without a document filter (returns all conversations).

**File:** [`src/frontend/src/components/chat/ChatWindow.tsx`](src/frontend/src/components/chat/ChatWindow.tsx)

Added `ragMode` from store. Passes `ragMode` to `sendMessageStream` and `sendMessage`. Dynamic placeholder text based on `ragMode` (Persian for global_rag, English for local_rag).

**File:** [`src/frontend/src/components/chat/MessageBubble.tsx`](src/frontend/src/components/chat/MessageBubble.tsx)

Added `HubStatusBadge` import. Replaced inline hub header rendering with `<HubStatusBadge hubType={hubType} />`. Removed unused `config` variable.

### Step 6: Testing & Verification

**Backend tests:** 200 passed, 2 failed (both pre-existing failures unrelated to Phase 3):
- Embedding dimension mismatch (expects 1024, got 768) in integration tests
- `top_k` default value changed from 5 to 15 in serializer tests

**Frontend tests:** All 93 tests passed across 9 test files.

### Step 7: Updated Reference Documentation

- [`docs/active-task/wip-context.md`](docs/active-task/wip-context.md): This file — recorded Phase 3 completion
- [`docs/references/database-schema.md`](docs/references/database-schema.md): Updated `conversations` table schema to show `document_id` as nullable
- [`docs/references/api-registry.md`](docs/references/api-registry.md): Updated conversation API endpoint docs to reflect optional `document_id`, nullable response fields, and `mode` parameter

---

## Files Modified

| File | Description |
|---|---|
| [`src/backend/conversations/models.py`](src/backend/conversations/models.py) | Made `document` ForeignKey nullable, updated `__str__` for null document |
| [`src/backend/conversations/serializers.py`](src/backend/conversations/serializers.py) | Made `document_id` optional in create serializer, added `allow_null` to list serializer |
| [`src/backend/conversations/views.py`](src/backend/conversations/views.py) | Handle null document in create, add mode validation (local_rag requires document) |
| [`src/backend/conversations/migrations/0003_make_document_nullable.py`](src/backend/conversations/migrations/0003_make_document_nullable.py) | Migration to make `document_id` nullable |
| [`src/frontend/src/api/conversations.ts`](src/frontend/src/api/conversations.ts) | Added `RagMode` type, made `document_id`/`document_title` nullable, added `mode` param |
| [`src/frontend/src/stores/conversationStore.ts`](src/frontend/src/stores/conversationStore.ts) | Added `ragMode` state/actions, made `documentId` optional, passes `mode` to API calls |
| [`src/frontend/src/components/chat/ConversationSidebar.tsx`](src/frontend/src/components/chat/ConversationSidebar.tsx) | Made `documentId` optional in props |
| [`src/frontend/src/components/chat/ChatWindow.tsx`](src/frontend/src/components/chat/ChatWindow.tsx) | Added `ragMode` from store, passes mode to send functions, dynamic placeholder |
| [`src/frontend/src/components/chat/MessageBubble.tsx`](src/frontend/src/components/chat/MessageBubble.tsx) | Replaced inline hub header with `HubStatusBadge` component |
| [`src/frontend/src/App.tsx`](src/frontend/src/App.tsx) | Added `/legal-research` and `/legal-research/:conversationId` routes |
| [`src/frontend/src/components/layout/Sidebar.tsx`](src/frontend/src/components/layout/Sidebar.tsx) | Added "Legal Research" nav item with Search icon |
| [`src/frontend/src/pages/DashboardPage.tsx`](src/frontend/src/pages/DashboardPage.tsx) | Added Quick Actions section with Legal Research and Document Chat cards |

## Files Created

| File | Description |
|---|---|
| [`src/frontend/src/components/rag/ModeSelector.tsx`](src/frontend/src/components/rag/ModeSelector.tsx) | Toggle between local_rag and global_rag modes |
| [`src/frontend/src/components/rag/HubStatusBadge.tsx`](src/frontend/src/components/rag/HubStatusBadge.tsx) | Badge showing hub type with color coding and icons |
| [`src/frontend/src/components/rag/GlobalRagEmptyState.tsx`](src/frontend/src/components/rag/GlobalRagEmptyState.tsx) | Empty state for Global RAG with hub cards and suggested questions |
| [`src/frontend/src/pages/GlobalRagChatPage.tsx`](src/frontend/src/pages/GlobalRagChatPage.tsx) | Full chat page for legal research (no documentId needed) |

## Next Steps

1. **End-to-end verification**: Navigate to `/legal-research`, create a Global RAG conversation, send a query, and verify the response includes `hub_metadata` with `partial_answer` fields
2. **Streaming support for Global RAG**: The streaming endpoint (`POST /conversations/{id}/messages/stream/`) currently supports the `mode` parameter but Global RAG streaming is not yet implemented in the backend
3. **Mobile responsiveness**: Verify the new pages and components work correctly on mobile viewports

---

## Bug Fix: TypeScript Build Error (2026-05-12)

**Problem:** `docker-compose exec frontend npm run build` failed with:
```
error TS6133: 'HUB_CONFIG' is declared but its value is never read.
```

**Root Cause:** During Phase 3 refactoring, the inline hub header rendering was replaced with the `<HubStatusBadge>` component, but the `HUB_CONFIG` constant (and its `HubConfig` interface) were left behind as dead code. The `tsconfig.json` has `"noUnusedLocals": true`, causing the build to fail.

**Fix Applied:**
1. Removed unused `HubConfig` interface and `HUB_CONFIG` constant from [`src/frontend/src/components/chat/MessageBubble.tsx`](src/frontend/src/components/chat/MessageBubble.tsx)
2. Removed unused `Scale`, `Gavel`, `BookOpen` icon imports from the same file (they were only used by `HUB_CONFIG`)
3. Rebuilt frontend: `docker-compose exec frontend npm run build` ✅ succeeded
4. Restarted Nginx: `docker-compose restart nginx` ✅

**Why changes weren't visible:** The TypeScript build error prevented `vite build` from completing, so the `dist/` directory contained stale files from the previous successful build. Nginx serves from `dist/`, so users saw the old frontend.
