# WIP Context — Phase 3 Task 3: Frontend Navigation Skeleton (Interactive Strategist)

## What Was Just Completed

### Task 3: Frontend Shell

Implemented the frontend navigation skeleton for the Interactive Strategist feature. All changes are on the frontend side.

### Changes Made

#### 1. [`src/frontend/src/pages/StrategistPage.tsx`](../../src/frontend/src/pages/StrategistPage.tsx) — **NEW FILE**

Created a full-height page component following the exact same pattern as [`GlobalRagChatPage.tsx`](../../src/frontend/src/pages/GlobalRagChatPage.tsx):
- Full-screen layout with collapsible desktop sidebar and mobile drawer overlay
- Uses `ConversationSidebar` with `mode="strategist"` to filter conversations
- Uses `ChatWindow` with `mode="strategist"` for messaging
- Empty state (`StrategistEmptyState`) with a "Start New Analysis" button that creates a strategist-mode conversation
- Header with `Scale` icon and "Interactive Strategist" title
- Back navigation to dashboard

#### 2. [`src/frontend/src/App.tsx`](../../src/frontend/src/App.tsx)

Added two new routes (outside AppShell, same pattern as legal-research):
```typescript
{ path: '/strategist', element: <StrategistPage /> },
{ path: '/strategist/:conversationId', element: <StrategistPage /> },
```

#### 3. [`src/frontend/src/components/layout/Sidebar.tsx`](../../src/frontend/src/components/layout/Sidebar.tsx)

- Added `Scale` to lucide-react imports
- Added new nav item: `{ label: 'Strategist', icon: <Scale ... />, href: '/strategist' }` (placed before the disabled "Conversations" item)
- Updated `isActive` detection to use `location.pathname.startsWith('/strategist')`

#### 4. [`src/frontend/src/pages/DashboardPage.tsx`](../../src/frontend/src/pages/DashboardPage.tsx)

- Added `Scale` to lucide-react imports
- Added "Interactive Strategist" quick-action card between "Legal Research" and "Document Chat" cards
- Card navigates to `/strategist` on click
- Description: "Describe your case and get a strategic analysis with success probability, risk assessment, and recommendations."
- Button: "Start Analysis"

#### 5. [`src/frontend/src/components/chat/ConversationSidebar.tsx`](../../src/frontend/src/components/chat/ConversationSidebar.tsx)

- Added `mode?: RagMode` prop to `ConversationSidebarProps`
- Passes `mode` to `fetchConversations(documentId, mode)` on mount
- Passes `mode` to `createConversation(documentId, undefined, mode)` when creating a new chat
- This ensures each page only shows conversations matching its mode

#### 6. [`src/frontend/src/api/conversations.ts`](../../src/frontend/src/api/conversations.ts)

- Extended `RagMode` type: `'local_rag' | 'global_rag' | 'strategist' | 'action_engine'`
- Updated `createConversation()` to accept optional `mode?: RagMode` parameter (sent in POST body)
- Updated `listConversations()` to accept optional `mode?: RagMode` parameter (sent as `?mode=` query param)

#### 7. [`src/frontend/src/stores/conversationStore.ts`](../../src/frontend/src/stores/conversationStore.ts)

- Updated `fetchConversations` signature to accept `mode?: RagMode`
- Updated `createConversation` signature to accept `mode?: RagMode`
- Both pass the mode through to the underlying API functions

## Current State

The frontend navigation skeleton is complete:
- `/strategist` route renders `StrategistPage` with full-height layout
- `/strategist/:conversationId` route renders the same page with an active conversation
- Sidebar has a "Strategist" nav item with active state detection
- Dashboard has an "Interactive Strategist" quick-action card
- `ConversationSidebar` filters conversations by `mode="strategist"`
- `RagMode` type includes `'strategist'` and `'action_engine'` (ready for Phase 4)

## Nginx Rebuild Required

**Important:** The nginx container (`docuchat_nginx`) serves **pre-built** frontend files from the production Docker stage (`COPY --from=builder /app/dist /usr/share/nginx/html`). Unlike the Vite dev server (port 5173) which uses HMR with a volume mount, nginx does **not** have a volume mount for the built files.

Therefore, after any frontend code changes, you must:
1. `docker-compose build nginx` — rebuilds the nginx image with new frontend build
2. `docker-compose up -d --no-deps nginx` — restarts the nginx container with the new image

This has been done for the current changes. Both `localhost:5173` (Vite dev) and `localhost` (nginx) now show the updated Strategist UI.

## Next Step

User will verify the UI navigation works on `localhost`. After verification, proceed to building the full `StrategistPage` with the strategist-specific chat UI and empty state.
