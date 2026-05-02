# Prompt for Code Mode: T01 Test Migration to Playwright E2E

## Context

The `.clinerules` have been updated to replace Jest/React Testing Library with Playwright E2E for all frontend testing, following a **"Visual First"** approach. We need to transition T01 (Document Upload Page & Flow) tests accordingly.

## Current State

- T01 components (`DropZone.tsx`, `UploadPage.tsx`, `lib/api/documents.ts`, `types/document.ts`) are already implemented and working.
- No Jest/RTL test files exist for T01 components — they were listed in the PRD but never created.
- Existing Vitest tests (`App.test.tsx`, `tests/auth/authStore.test.ts`, `tests/auth/axiosInterceptor.test.ts`) test **non-UI logic** and should remain untouched.
- The frontend runs at `http://localhost:5173` (Vite dev server, per `vite.config.ts`).

## Execution Steps

### Step 1: Verify No Stale Jest/RTL Test Files

Check if any of these files exist and delete them if found:
- `src/frontend/src/components/documents/DropZone.test.tsx`
- `src/frontend/src/pages/documents/UploadPage.test.tsx`
- `src/frontend/src/pages/documents/UploadPage.test.ts`
- Any other `.test.ts`/`.test.tsx` files inside `src/frontend/src/components/documents/` or `src/frontend/src/pages/documents/`

If none exist, report that and move on.

### Step 2: Install `@playwright/test` in `src/frontend`

Run these commands from the workspace root:

```bash
cd src/frontend && npm install -D @playwright/test
cd src/frontend && npx playwright install chromium
```

### Step 3: Create `src/frontend/playwright.config.ts`

Create the file with this content:

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
```

### Step 4: Create `src/frontend/tests/upload.spec.ts`

Create the E2E test file with the following 5 test cases. Use `test.describe` to group them under "T01 — Document Upload Flow".

**Important implementation notes:**
- The file input in `DropZone.tsx` is hidden (`className="hidden"`). Use `page.locator('input[type="file"]')` to target it directly with `setInputFiles()`.
- For mocking the upload API, use `page.route()` to intercept `POST **/api/documents/upload/` and return a mock response.
- The toast component uses shadcn's toast pattern — toasts appear in a `[data-sonner-toaster]` or `[role="status"]` region. Inspect the actual DOM to find the correct selector.
- The upload button has `disabled` attribute — use `await expect(button).toBeDisabled()` and `await expect(button).toBeEnabled()`.
- For file selection tests, create a minimal valid PDF buffer using `Buffer.from('%PDF-1.4 ...')` or use Playwright's built-in file picker.

**Test cases:**

1. **Upload button is disabled when no file or title is provided**
   - Navigate to `/documents/upload`
   - Assert the Upload button is disabled
   - Type a title, assert button still disabled (no file)
   - Select a PDF file, assert button becomes enabled

2. **Invalid file selection shows error for non-PDF**
   - Navigate to `/documents/upload`
   - Select a `.txt` file using `setInputFiles()` with a dummy text file
   - Assert error message "Only PDF files are allowed." is visible
   - Assert no file preview is shown

3. **Valid PDF file selection shows file preview**
   - Navigate to `/documents/upload`
   - Select a valid PDF file
   - Assert the file name is displayed in the DropZone
   - Assert the file size is displayed
   - Assert no error message is shown

4. **Successful upload flow with mocked API**
   - Navigate to `/documents/upload`
   - Fill in title and select a PDF file
   - Mock `POST /api/documents/upload/` to return status 201 with `{ id: 'doc-123', title: 'Test', original_filename: 'test.pdf', file_size: 1024, total_pages: null, status: 'uploaded', created_at: new Date().toISOString() }`
   - Click Upload button
   - Assert progress bar appears
   - Assert redirect to `/documents/doc-123`

5. **Upload error shows toast and stays on page**
   - Navigate to `/documents/upload`
   - Fill in title and select a PDF file
   - Mock `POST /api/documents/upload/` to return status 500
   - Click Upload button
   - Assert error toast with "Server error" is visible
   - Assert URL is still `/documents/upload`

### Step 5: Add Playwright Scripts to `package.json`

In `src/frontend/package.json`, add these scripts under the `"scripts"` section:

```json
"test:e2e": "playwright test",
"test:e2e:ui": "playwright test --ui",
"test:e2e:headed": "playwright test --headed"
```

### Step 6: Verify Vitest Config

Open `src/frontend/vitest.config.ts` and confirm the `include` pattern is:
```typescript
include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
```
This already excludes `.spec.ts` files (Playwright convention), so no change is needed. Just verify and report.

## Files to Create/Modify

| Action | File |
|--------|------|
| Create | `src/frontend/playwright.config.ts` |
| Create | `src/frontend/tests/upload.spec.ts` |
| Modify | `src/frontend/package.json` (add 3 scripts) |

## Files to NOT Touch

- `src/frontend/vitest.config.ts` — keep as-is
- `src/frontend/src/test/setup.ts` — keep as-is
- `src/frontend/src/App.test.tsx` — keep as-is
- `src/frontend/tests/auth/authStore.test.ts` — keep as-is
- `src/frontend/tests/auth/axiosInterceptor.test.ts` — keep as-is

## Verification

After implementation, run:
```bash
cd src/frontend && npx playwright test --list
```
This should list 5 tests without running them (no server needed).

## WIP Update

After completing all steps, update `docs/active-task/wip-context.md` with:
1. What was completed (all 6 steps)
2. Current state (Playwright installed, config created, 5 E2E tests written)
3. Next step (manual visual verification of upload flow, then run E2E tests against running dev server)
