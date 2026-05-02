# WIP Context — T01: Document Upload Page & Flow

## What was just completed

### T01 Test Migration to Playwright E2E (All 6 Steps)

1. **Step 1 — Verify no stale Jest/RTL test files:** Confirmed no `.test.ts`/`.test.tsx` files exist in `src/frontend/src/components/documents/` or `src/frontend/src/pages/documents/`.

2. **Step 2 — Install `@playwright/test`:** Installed `@playwright/test` (v1.59.1) via npm. Chromium browser downloaded manually by the user.

3. **Step 3 — Create `playwright.config.ts`:** Created at [`src/frontend/playwright.config.ts`](src/frontend/playwright.config.ts) with `testDir: './tests'`, `testMatch: '**/*.spec.ts'`, base URL `http://localhost:5173`, and Chromium project.

4. **Step 4 — Create `tests/upload.spec.ts`:** Created at [`src/frontend/tests/upload.spec.ts`](src/frontend/tests/upload.spec.ts) with 5 E2E test cases under `test.describe('T01 — Document Upload Flow')`:
   - Upload button disabled when no file/title
   - Invalid file (non-PDF) shows error
   - Valid PDF shows file preview
   - Successful upload with mocked API (redirects to `/documents/doc-123`)
   - Upload error (500) shows toast and stays on page

5. **Step 5 — Add Playwright scripts:** Added `test:e2e`, `test:e2e:ui`, `test:e2e:headed` scripts to [`src/frontend/package.json`](src/frontend/package.json).

6. **Step 6 — Verify Vitest config:** Confirmed [`src/frontend/vitest.config.ts`](src/frontend/vitest.config.ts) uses `include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}']` — no conflict with `.spec.ts` Playwright convention.

7. **Verification:** `npx playwright test --list` outputs all 5 tests successfully.

## Current state of the code
- Playwright installed and configured
- 5 E2E tests written for the document upload flow
- Vitest tests (`App.test.tsx`, `authStore.test.ts`, `axiosInterceptor.test.ts`) remain untouched
- `testMatch` in Playwright config excludes `.test.ts` files to avoid conflicts with Vitest

## Next step
Manual visual verification of the upload flow, then run E2E tests against the running dev server:
```bash
cd src/frontend && npx playwright test
```
