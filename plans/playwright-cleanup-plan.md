# Playwright Cleanup Plan — DocuChat Project

## Overview

This plan removes **Playwright** (E2E UI testing) from the DocuChat project while preserving **Vitest** (unit/logic testing). The user previously used Playwright for UI tests but has decided to stop using it. All UI testing will now be done **manually** per the project's `.clinerules` (Visual First approach).

---

## What We Are Removing

### 1. Playwright Configuration & Dependencies

| File / Config | Reason |
|---|---|
| `src/frontend/playwright.config.ts` | Playwright configuration file |
| `@playwright/test` from `src/frontend/package.json` (devDependencies) | Playwright npm package |
| `test:e2e`, `test:e2e:ui`, `test:e2e:headed` scripts from `package.json` | Playwright-specific npm scripts |

### 2. Playwright Test Files

| File | Reason |
|---|---|
| `src/frontend/tests/upload.spec.ts` | Playwright E2E test for document upload UI flow |

### 3. Playwright Artifacts & Reports

| Path | Reason |
|---|---|
| `src/frontend/playwright-report/` | Generated Playwright test report directory (contains `index.html`) |

### 4. Docker & CI Changes (if applicable)

| File | Change |
|---|---|
| `docker-compose.yml` | No changes needed — the `test` service uses `pytest` (backend), not Playwright |
| `docker/frontend/Dockerfile` | No changes needed — Playwright is only a devDependency, not needed at runtime |

### 5. `.gitignore` Updates

| File | Change |
|---|---|
| `.gitignore` | Add `playwright-report/` entry if not already present (to prevent future artifacts from being committed) |

---

## What We Are Keeping (Vitest Tests)

These **Vitest** test files are **NOT affected** and will remain untouched:

| File | Type |
|---|---|
| `src/frontend/src/App.test.tsx` | Vitest — Placeholder smoke test |
| `src/frontend/src/hooks/useProcessingStatus.test.tsx` | Vitest — Hook logic test |
| `src/frontend/src/test/setup.ts` | Vitest — Test setup (jsdom, matchMedia mock) |
| `src/frontend/tests/api/conversations.test.ts` | Vitest — API logic test |
| `src/frontend/tests/auth/authStore.test.ts` | Vitest — Auth store logic test |
| `src/frontend/tests/auth/axiosInterceptor.test.ts` | Vitest — Axios interceptor logic test |
| `src/frontend/tests/stores/conversationStore.test.ts` | Vitest — Zustand store logic test |
| `src/frontend/vitest.config.ts` | Vitest configuration (keep) |
| `src/frontend/vite.config.ts` | Vite configuration (keep, no changes needed) |

---

## Execution Steps (for Code Mode)

### Step 1: Remove Playwright npm package

- Edit `src/frontend/package.json`
- Remove `"@playwright/test": "^1.59.1"` from `devDependencies`
- Remove these scripts:
  - `"test:e2e": "playwright test"`
  - `"test:e2e:ui": "playwright test --ui"`
  - `"test:e2e:headed": "playwright test --headed"`

### Step 2: Delete Playwright configuration

- Delete `src/frontend/playwright.config.ts`

### Step 3: Delete Playwright test file

- Delete `src/frontend/tests/upload.spec.ts`

### Step 4: Delete Playwright report artifacts

- Delete `src/frontend/playwright-report/` directory (recursively)

### Step 5: Update `.gitignore`

- Add `playwright-report/` to `.gitignore` (in the appropriate section, e.g., under "Test & Coverage Artifacts")

### Step 6: Clean up Docker containers/images (optional but recommended)

- Remove any dangling/stopped containers: `docker container prune -f`
- Remove any dangling images: `docker image prune -f`
- **Note:** No DocuChat-specific containers need to be rebuilt since Playwright was only a devDependency and doesn't affect the Docker build.

### Step 7: Verify Vitest still works

- Run: `docker-compose exec frontend npx vitest run`
- Confirm all Vitest tests pass

---

## Verification Checklist

After cleanup, confirm:

- [ ] `@playwright/test` is removed from `package.json`
- [ ] Playwright scripts are removed from `package.json`
- [ ] `playwright.config.ts` is deleted
- [ ] `tests/upload.spec.ts` is deleted
- [ ] `playwright-report/` directory is deleted
- [ ] `playwright-report/` is added to `.gitignore`
- [ ] `vitest run` passes all remaining tests
- [ ] `npm install` (or `docker-compose build frontend`) succeeds without Playwright

---

## Rollback Plan

If something goes wrong:

1. **Restore `package.json`** from git: `git checkout -- src/frontend/package.json`
2. **Restore deleted files** from git: `git checkout -- src/frontend/playwright.config.ts src/frontend/tests/upload.spec.ts`
3. **Reinstall dependencies**: `docker-compose exec frontend npm install`
