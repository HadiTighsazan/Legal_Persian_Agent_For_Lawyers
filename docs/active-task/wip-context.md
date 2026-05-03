# WIP Context — Vitest Test Fixes

## What was just completed

### Fixed Vitest Test Failures (3 root causes identified and resolved)

**Root Cause 1 — `import.meta.env` not available in Vitest:**
- [`src/frontend/src/api/axios.ts`](src/frontend/src/api/axios.ts:10) uses `import.meta.env.VITE_API_URL` at module scope
- Vitest's `jsdom` environment does NOT automatically load `.env` files
- **Fix:** Added `env` config to [`src/frontend/vitest.config.ts`](src/frontend/vitest.config.ts) with `VITE_API_URL` and `VITE_APP_NAME`

**Root Cause 2 — Axios mock mismatch in `axiosInterceptor.test.ts`:**
- The test mocked `axios.default.post` but the actual `refreshTokens()` function calls `axios.post` (not `axios.default.post`)
- The mock never intercepted the refresh token API call
- **Fix:** Updated the mock in [`src/frontend/tests/auth/axiosInterceptor.test.ts`](src/frontend/tests/auth/axiosInterceptor.test.ts) to provide `axios.post` directly (not `axios.default.post`)

**Root Cause 3 — Missing `vi.resetModules()` in `authStore.test.ts`:**
- Module state could leak between tests because `vi.resetModules()` was never called
- **Fix:** Added `vi.resetModules()` in `beforeEach` in [`src/frontend/tests/auth/authStore.test.ts`](src/frontend/tests/auth/authStore.test.ts)

**Additional fix — `window.location` stub missing `pathname`:**
- The `redirectToLogin()` function in [`axios.ts`](src/frontend/src/api/axios.ts:32) checks `window.location.pathname`
- The test stub only had `{ href: '' }`, causing `undefined.startsWith()` to throw
- **Fix:** Added `pathname: ''` to the location stub

## Current state of the code

- All 3 Vitest test files pass: **18 tests, 3 test files, all passing** ✅
  - `src/App.test.tsx` — 2 tests ✅
  - `tests/auth/authStore.test.ts` — 10 tests ✅
  - `tests/auth/axiosInterceptor.test.ts` — 6 tests ✅
- Playwright E2E tests remain unchanged and working
- No breaking changes to any source code

## Files modified

| File | Change |
|------|--------|
| [`src/frontend/vitest.config.ts`](src/frontend/vitest.config.ts) | Added `env` config with `VITE_API_URL` and `VITE_APP_NAME` |
| [`src/frontend/tests/auth/axiosInterceptor.test.ts`](src/frontend/tests/auth/axiosInterceptor.test.ts) | Fixed axios mock structure (`axios.post` not `axios.default.post`); added `pathname` to location stub |
| [`src/frontend/tests/auth/authStore.test.ts`](src/frontend/tests/auth/authStore.test.ts) | Added `vi.resetModules()` in `beforeEach` |

## Next step

N/A — Task complete. Vitest tests are now fully passing.
