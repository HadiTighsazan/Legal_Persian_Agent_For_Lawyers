# Plan: Fix Vitest Test Failures in Frontend

## Problem Statement

Vitest tests (`authStore.test.ts`, `axiosInterceptor.test.ts`, `App.test.tsx`) are failing when run inside Docker via `docker-compose exec frontend npm test`, while Playwright E2E tests pass successfully.

---

## Root Cause Analysis

Based on thorough code review of the project, I've identified **5 potential root causes** that could be causing Vitest failures:

### 1. `import.meta.env` Not Mocked in Vitest Environment

**File affected:** [`src/frontend/src/api/axios.ts`](src/frontend/src/api/axios.ts:10)

The [`axios.ts`](src/frontend/src/api/axios.ts) module uses `import.meta.env.VITE_API_URL` at module scope (line 10). When Vitest runs with `jsdom` environment, `import.meta.env` is **not automatically populated** with Vite env variables unless Vitest is configured to load them. This causes the `normalizeBaseUrl()` call to receive `undefined`, resulting in a base URL of `/api` (the fallback), which may cause subtle issues.

**More critically:** The [`axiosInterceptor.test.ts`](src/frontend/tests/auth/axiosInterceptor.test.ts) test imports `../../src/api/axios` which triggers module-level code that reads `import.meta.env`. If `VITE_API_URL` is not defined in the Vitest environment, the `axios.post` call inside `refreshTokens()` (line 52) will use `/api` as the base URL, and the test assertions check for `expect.stringContaining('/auth/refresh')` — this may or may not match depending on how the URL resolves.

### 2. `axiosInterceptor.test.ts` — Mock Structure Mismatch

**File affected:** [`src/frontend/tests/auth/axiosInterceptor.test.ts`](src/frontend/tests/auth/axiosInterceptor.test.ts)

The test mocks `axios` with a custom structure (lines 37-43), but the mock may not perfectly replicate the actual `axios` API. Specifically:

- The mock provides `axios.default.post` (line 39), but the actual code in [`axios.ts`](src/frontend/src/api/axios.ts) line 51 uses `axios.post` (not `axios.default.post`). The test imports `axios` and accesses `axios.default.post` (line 142), but the actual `refreshTokens` function calls `axios.post` directly. This is a **critical mismatch** — the mock may not intercept the actual `axios.post` call made by `refreshTokens()`.

- The `apiClient` is created via `axios.create()` which returns `mockAxiosInstance`. But `mockAxiosInstance` is a `vi.fn()` that is also callable. The test sets `mockAxiosInstance.mockResolvedValue({ data: 'retried' })` (line 154) for the retry, but the actual retry logic calls `apiClient(originalRequest)` (line 97 of axios.ts) — this should work if the mock is set up correctly.

### 3. `authStore.test.ts` — Dynamic Import Timing Issues

**File affected:** [`src/frontend/tests/auth/authStore.test.ts`](src/frontend/tests/auth/authStore.test.ts)

The test uses `vi.mock('@/api/authApi', ...)` at the top level (line 2), then dynamically imports the store inside `resetStore()` (line 48). The `vi.mock` call is hoisted by Vitest, but the dynamic `import()` inside `resetStore()` may have race conditions:

- `resetStore()` is called inside each test **after** the mock setup, but the `import()` is async. If the store module has already been cached from a previous test, the mock may not be applied correctly.
- The test relies on `vi.resetModules()` in `axiosInterceptor.test.ts` but **NOT** in `authStore.test.ts`. This means module state can leak between tests.

### 4. Missing `@testing-library/jest-dom` Vitest Setup

**File affected:** [`src/frontend/src/test/setup.ts`](src/frontend/src/test/setup.ts)

The setup file imports `@testing-library/jest-dom/vitest` (line 1), which is correct for the installed version (`"@testing-library/jest-dom": "^6.6.3"`). However, if the `vitest` version (`^1.2.2`) is incompatible with the `jest-dom` matchers extension mechanism, this could cause failures. This is less likely but worth verifying.

### 5. Docker Environment — Missing `node_modules` or Incorrect Path Resolution

**File affected:** [`docker/frontend/Dockerfile`](docker/frontend/Dockerfile)

The Dockerfile (line 24) copies `src/frontend/` to `/app`, but the `vitest.config.ts` uses `path.resolve(__dirname, './src')` for the `@` alias. Inside Docker, `__dirname` resolves to `/app`, so `@` maps to `/app/src`. This should work, but if there's a path resolution issue with the Docker volume mount (`- ./src/frontend:/app`), it could cause problems.

---

## Diagnostic Steps (to confirm root cause)

Before applying fixes, run these diagnostic commands to identify the exact failure:

| # | Command | What It Checks |
|---|---------|----------------|
| 1 | `docker-compose exec frontend npx vitest run --reporter=verbose` | Full test output with pass/fail per test |
| 2 | `docker-compose exec frontend npx vitest run --reporter=verbose src/App.test.tsx` | Isolate `App.test.tsx` (simplest test) |
| 3 | `docker-compose exec frontend npx vitest run --reporter=verbose tests/auth/authStore.test.ts` | Isolate authStore tests |
| 4 | `docker-compose exec frontend npx vitest run --reporter=verbose tests/auth/axiosInterceptor.test.ts` | Isolate axios interceptor tests |
| 5 | `docker-compose exec frontend node -e "console.log(process.env.VITE_API_URL)"` | Check if env vars are available in container |

---

## Fix Plan

### Step 1: Fix `import.meta.env` in Vitest

**Problem:** `import.meta.env.VITE_API_URL` is undefined in Vitest's `jsdom` environment.

**Solution:** Add `env` configuration to [`src/frontend/vitest.config.ts`](src/frontend/vitest.config.ts) to load `.env` files:

```ts
// In vitest.config.ts, add to the `test` object:
env: {
  VITE_API_URL: 'http://localhost:8000/api',
  VITE_APP_NAME: 'DocuChat',
},
// OR use envDir to point to the .env files:
envDir: './',
```

This ensures `import.meta.env.VITE_API_URL` resolves correctly when [`axios.ts`](src/frontend/src/api/axios.ts) is imported during tests.

### Step 2: Fix `axiosInterceptor.test.ts` — Mock `axios.post` Correctly

**Problem:** The test mocks `axios.default.post` but the actual code calls `axios.post`.

**Solution:** Update the mock in [`src/frontend/tests/auth/axiosInterceptor.test.ts`](src/frontend/tests/auth/axiosInterceptor.test.ts) to ensure `axios.post` is properly mocked:

```ts
vi.mock('axios', () => {
  const mockPost = vi.fn();
  return {
    default: {
      create: vi.fn(() => mockAxiosInstance),
      post: mockPost,
    },
    create: vi.fn(() => mockAxiosInstance),
    post: mockPost,
  };
});
```

Then in tests, use `const axios = await import('axios');` and access `axios.post` (not `axios.default.post`).

### Step 3: Fix `authStore.test.ts` — Add `vi.resetModules()` and Stabilize Imports

**Problem:** Module caching between tests can cause mock state leakage.

**Solution:** Add `vi.resetModules()` in `beforeEach` in [`src/frontend/tests/auth/authStore.test.ts`](src/frontend/tests/auth/authStore.test.ts):

```ts
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.resetModules(); // Add this line
});
```

Also, ensure the `vi.mock('@/api/authApi', ...)` call uses a factory that returns fresh mock functions each time, or use `vi.hoisted()` if needed for Vitest v1.

### Step 4: Verify and Fix `@testing-library/jest-dom` Setup

**Problem:** Potential version incompatibility.

**Solution:** Verify the installed versions are compatible:

```bash
docker-compose exec frontend npm ls @testing-library/jest-dom vitest
```

If incompatible, update `@testing-library/jest-dom` to a version compatible with Vitest v1. The current setup (`@testing-library/jest-dom@^6.6.3` with `vitest@^1.2.2`) should be compatible, but verify the import path `@testing-library/jest-dom/vitest` exists.

### Step 5: Run and Verify All Tests

After applying fixes:

```bash
docker-compose exec frontend npm test
```

Expected outcome: All 3 test files pass (`App.test.tsx`, `authStore.test.ts`, `axiosInterceptor.test.ts`).

---

## Execution Order

```
Step 1 (vitest.config.ts env) 
  → Step 2 (axiosInterceptor.test.ts mock fix) 
    → Step 3 (authStore.test.ts resetModules) 
      → Step 4 (verify jest-dom setup) 
        → Step 5 (run all tests and verify)
```

---

## Rollback Plan

If fixes break existing functionality:
1. Revert `vitest.config.ts` changes
2. Revert test file changes
3. Run `docker-compose exec frontend npm test` to confirm original state

---

## Files to Modify

| File | Change |
|------|--------|
| [`src/frontend/vitest.config.ts`](src/frontend/vitest.config.ts) | Add `env` or `envDir` config |
| [`src/frontend/tests/auth/axiosInterceptor.test.ts`](src/frontend/tests/auth/axiosInterceptor.test.ts) | Fix axios mock structure |
| [`src/frontend/tests/auth/authStore.test.ts`](src/frontend/tests/auth/authStore.test.ts) | Add `vi.resetModules()` in `beforeEach` |
