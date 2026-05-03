# WIP Context — Task 1: Conversation API Service Layer

## What Was Just Completed

Created the Conversation API service layer for the frontend, following TDD (RED → GREEN → REFACTOR).

### Files Created

1. **`src/frontend/src/api/conversations.ts`** — API service layer with:
   - 7 TypeScript interfaces: `Conversation`, `MessageSource`, `TokenUsage`, `Message`, `ConversationDetail`, `PaginatedConversations`, `DirectQueryResponse`
   - `ApiError` class for typed error handling
   - 6 API functions: `createConversation`, `listConversations`, `getConversation`, `deleteConversation`, `sendMessage`, `directQuery`
   - All functions follow the existing `authApi.ts` pattern (import `apiClient` from `axios.ts`, use typed generics, destructure `data`)
   - No `any` types anywhere

2. **`src/frontend/tests/api/conversations.test.ts`** — 30 test cases across 6 describe blocks:
   - `createConversation`: 6 tests (call shape, success, 400/403/404 errors, optional title)
   - `listConversations`: 6 tests (call shape with params, success, no filters, doc-only, page-only, 401 error)
   - `getConversation`: 4 tests (call shape, nested messages, 404/403 errors)
   - `deleteConversation`: 4 tests (call shape, void return, 404/403 errors)
   - `sendMessage`: 5 tests (call shape, sources/token_usage, 400/429/502 errors)
   - `directQuery`: 5 tests (call shape, full response, optional topK, 422/502 errors)

### Test Results
- **30/30 tests passing** via `docker-compose exec frontend npx vitest run tests/api/conversations.test.ts`

## Current State of Code

- `src/frontend/src/api/conversations.ts` — Complete, clean, no `any` types
- `src/frontend/tests/api/conversations.test.ts` — Complete, all 30 tests passing
- No changes to existing files (`axios.ts`, `authApi.ts`, `types/document.ts`)

## Next Step

Proceed to **Task 2**: Create the `conversationStore.ts` (Zustand store) that consumes this API layer.
