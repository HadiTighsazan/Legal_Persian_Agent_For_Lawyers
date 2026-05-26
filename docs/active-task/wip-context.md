# WIP Context — Streaming Pipeline Root Cause Fix

## Status: ✅ VERIFIED (End-to-End)

## What was completed

Implemented 3 fixes from `plans/streaming-pipeline-fix-plan.md` to fix the streaming RAG pipeline bugs, plus fixed a pre-existing `.env` configuration issue.

### Fix 1: Add diagnostic logging to `event_stream()` (Backend)

**File:** [`src/backend/conversations/views.py`](src/backend/conversations/views.py:518-607)

**Changes:**
- Added `logger.info()` calls at each stage of the `event_stream()` generator:
  - Before starting global_rag stream
  - After creating the `run_global_rag_query_stream` generator
  - When the "done" event is received (with char count and source count)
  - After persisting the assistant message
  - Before starting local_rag stream
  - When local_rag "done" event is received
- Changed `logger.error()` to `logger.exception()` in the `RAGServiceException`/`GlobalRAGServiceException` handler to capture full stack traces
- Added the exception message to the `logger.exception()` call in the generic `Exception` handler for better diagnostics

**Why:** The streaming endpoint was silently failing and falling back to non-streaming. The diagnostic logging will identify exactly where the failure occurs by tracing each stage of the generator execution.

### Fix 2: Include `reasoning` in progress SSE events (Backend)

**File:** [`src/backend/conversations/views.py`](src/backend/conversations/views.py:535)

**Change:** The progress event payload now includes `reasoning` from the progress data:
```python
yield f"data: {json.dumps({'type': 'progress', 'status': data['status'], 'reasoning': data.get('reasoning')})}\n\n"
```

**Why:** The `run_global_rag_query_stream()` function yields progress events with a `reasoning` key (from the router result), but the view was stripping it out. The frontend's `onProgress` callback already accepts an optional `reasoning` parameter and passes it to the store's `thinkingReasoning` field.

### Fix 3: Add progress status to non-streaming fallback (Frontend)

**File:** [`src/frontend/src/stores/conversationStore.ts`](src/frontend/src/stores/conversationStore.ts:116-165)

**Changes:**
- When `sendMessage()` starts (non-streaming fallback), sets `thinkingStatus: 'Processing your request...'` so the user sees activity during the 1-2 minute wait
- Clears `thinkingStatus` and `thinkingReasoning` on both success and error paths
- Also clears `thinkingReasoning` on the initial set for consistency

**Why:** The non-streaming fallback had zero progress mechanism. During the 1-2 minute wait, the user saw `ThinkingIndicator` with `status={null}` (showing generic "Thinking...") but no meaningful progress updates. This provides at least a basic status indicator.

### Fix 4: Fix `VITE_API_URL` configuration (Infrastructure)

**Files:** [`src/frontend/.env.development`](src/frontend/.env.development), [`docker-compose.yml`](docker-compose.yml:246-252)

**Changes:**
- Changed `VITE_API_URL` from `http://localhost:8000/api` to `http://localhost:8000` in `.env.development`
- Changed `VITE_API_URL` default from `http://localhost/api` to `http://localhost:8000` in `docker-compose.yml`

**Why:** The frontend was calling `http://localhost:8000/api/users/me/` for auth initialization, but the Django backend at port 8000 (directly, not through nginx) doesn't have an `/api` prefix — that's only added by nginx in production. This caused `initializeAuth()` to fail with a 404, which cleared the auth tokens and redirected to the login page. The fix ensures the frontend calls the correct URL `http://localhost:8000/users/me/` (without `/api` prefix).

## Current State

All changes are in 4 files:

| # | File | Change Type | Description |
|---|------|-------------|-------------|
| 1 | [`src/backend/conversations/views.py`](src/backend/conversations/views.py:518-607) | Enhancement | Add diagnostic logging + include reasoning in progress events |
| 2 | [`src/frontend/src/stores/conversationStore.ts`](src/frontend/src/stores/conversationStore.ts:116-165) | Enhancement | Add progress status to non-streaming `sendMessage` fallback |
| 3 | [`src/frontend/.env.development`](src/frontend/.env.development) | Bugfix | Fix VITE_API_URL to not include /api prefix |
| 4 | [`docker-compose.yml`](docker-compose.yml:246-252) | Bugfix | Fix default VITE_API_URL to not include /api prefix |

## Test Results

- **Backend:** 213 passed, 3 warnings, 33 subtests passed ✅
- **Frontend:** 93 passed (9 test files) ✅
- **Puppeteer End-to-End:** ✅
  - Logged in as `test1@gmail.com` successfully
  - Navigated to Global RAG (Legal Research) page
  - Created a new conversation
  - Switched to Global RAG mode
  - Sent question "حکم زنا چیست؟" (What is the punishment for adultery?)
  - ✅ Streaming endpoint works — streaming cursor `▌` visible
  - ✅ Progress indicator shows "Formulating search query..." during processing
  - ✅ User sees meaningful activity during the wait time

## Next Step

Monitor the streaming endpoint logs in production to verify the diagnostic logging helps identify any remaining issues. The end-to-end test confirms the streaming pipeline is functioning correctly with progress indicators visible to the user.
