# Task E08-T8: Final Integration & QA

## Objective

Wire everything together, run the production build, fix any TypeScript errors, and verify the frontend runs correctly both standalone and inside Docker. Then perform a manual smoke test of all auth flows in the browser.

**Note:** No automated tests need to be written or run for this task. Testing is done manually in the browser.

## Prerequisites

- All E08 tasks (T1 through T7) are fully implemented and verified
- All source files exist:
  - `src/frontend/src/App.tsx` — Router setup with `createBrowserRouter`
  - `src/frontend/src/main.tsx` — Entry point with `initializeAuth()`
  - `src/frontend/src/stores/authStore.ts` — Zustand auth store
  - `src/frontend/src/api/axios.ts` — Axios instance with token refresh interceptor
  - `src/frontend/src/api/authApi.ts` — Typed API functions
  - `src/frontend/src/types/auth.ts` — TypeScript interfaces
  - `src/frontend/src/components/auth/PrivateRoute.tsx` — Auth guard
  - `src/frontend/src/components/auth/PublicRoute.tsx` — Public route guard
  - `src/frontend/src/pages/LoginPage.tsx` — Login form
  - `src/frontend/src/pages/RegisterPage.tsx` — Register form
  - `src/frontend/src/pages/DashboardPage.tsx` — Welcome + stat cards
  - `src/frontend/src/components/layout/AppShell.tsx` — Layout shell
  - `src/frontend/src/components/layout/Sidebar.tsx` — Navigation sidebar
  - `src/frontend/src/components/layout/Topbar.tsx` — Top bar with user dropdown
  - `src/frontend/.env.development` — Dev environment variables
  - `src/frontend/.env.production` — Production environment variables
  - `docker/frontend/Dockerfile` — Frontend Dockerfile
  - `docker-compose.yml` — Frontend service already defined
  - `docker/nginx/nginx.conf` — Nginx with SPA routing

## Execution Steps

### Step 1: Run `npm run build` and Fix TypeScript Errors

Run the production build to check for TypeScript errors:

```bash
cd src/frontend
npm run build
```

The `build` script in `package.json` is `"tsc && vite build"`. This runs TypeScript compiler first, then Vite build.

**If there are TypeScript errors, fix them.** Common issues to check:

1. **Zod v4 import path:** The code uses `zod/v4` — verify this is correct for the installed zod version (`"zod": "^4.3.6"`). If zod v4 uses a different import, update accordingly.

2. **react-router-dom v7 API changes:** The code uses `createBrowserRouter` and `RouterProvider` from `react-router-dom` v7 (`"react-router-dom": "^7.14.2"`). Verify the API is compatible. In v7, `createBrowserRouter` may have moved or changed.

3. **Zustand v5 API:** The code uses `create` from `zustand` v5 (`"zustand": "^5.0.12"`). Verify the store creation API is correct for v5.

4. **Any missing type declarations:** Check for missing `@types/*` packages.

5. **Any unused imports or variables:** The `tsc` strict mode will catch these.

**Acceptance:** `npm run build` exits with code 0, produces `dist/` folder, zero TypeScript errors, zero warnings.

### Step 2: Manual Smoke Test Checklist

After the build succeeds, start the frontend dev server and manually test all flows in the browser.

**Setup for manual testing:**
- Start the backend (Django) — either via `docker compose up` or directly
- Start the frontend dev server: `cd src/frontend && npm run dev`
- Open browser at `http://localhost:5173`

**Smoke Test Items (from PRD Section 10):**

| # | Test Case | Expected Result | Pass/Fail |
|---|-----------|-----------------|-----------|
| 1 | Register a new user | Lands on Dashboard page after registration | |
| 2 | Logout via dropdown menu | Lands on Login page, tokens cleared from localStorage | |
| 3 | Login with registered user | Lands on Dashboard page | |
| 4 | Access `/dashboard` without token (fresh browser tab) | Redirects to `/login` | |
| 5 | Access `/login` while logged in | Redirects to `/dashboard` | |
| 6 | Refresh page while logged in | Stays on current page (initializeAuth restores session) | |
| 7 | Verify responsive layout at 375px width | Sidebar hidden, hamburger visible, content readable | |
| 8 | No `console.error` in browser during happy path flows | Console is clean | |

**Detailed test procedures:**

**Test 1 — Register:**
1. Open `http://localhost:5173` in a fresh browser (no existing tokens)
2. You should be redirected to `/login`
3. Click "Create one" link to go to `/register`
4. Fill in: Full Name, Email, Password (≥8 chars), Confirm Password
5. Click "Create Account"
6. ✅ Verify: Redirected to `/dashboard`, shows "Welcome back, {name}"

**Test 2 — Logout:**
1. While on Dashboard, click the avatar in the top-right corner
2. Click "Sign Out" in the dropdown
3. ✅ Verify: Redirected to `/login`
4. ✅ Verify: `localStorage` has no `access_token` or `refresh_token`

**Test 3 — Login:**
1. On the Login page, enter the email and password from Test 1
2. Click "Sign In"
3. ✅ Verify: Redirected to `/dashboard`, shows "Welcome back, {name}"

**Test 4 — Protected route without token:**
1. Open a new incognito/private browser window
2. Navigate directly to `http://localhost:5173/dashboard`
3. ✅ Verify: Redirected to `/login`

**Test 5 — Public route while authenticated:**
1. In the window where you're logged in (from Test 3)
2. Navigate to `http://localhost:5173/login`
3. ✅ Verify: Redirected to `/dashboard`

**Test 6 — Page refresh while logged in:**
1. While on Dashboard (logged in), press F5 / refresh
2. ✅ Verify: Stays on Dashboard (no flash to login)
3. ✅ Verify: `initializeAuth()` restores session correctly

**Test 7 — Mobile responsive:**
1. Open DevTools (F12) and toggle device toolbar (Ctrl+Shift+M)
2. Set viewport to 375px width
3. ✅ Verify: Sidebar is hidden
4. ✅ Verify: Hamburger menu icon is visible in topbar
5. ✅ Verify: Clicking hamburger opens sidebar with overlay
6. ✅ Verify: Clicking overlay closes sidebar
7. ✅ Verify: Content is readable (no horizontal scroll)

**Test 8 — Console errors:**
1. Keep DevTools Console tab open during all tests above
2. ✅ Verify: No `console.error` or uncaught exceptions during happy path flows

### Step 3: Verify Frontend Runs in Docker

After manual testing passes, verify the frontend works inside Docker:

```bash
# From the project root (c:/Users/hadit/Desktop/rag-project)
docker compose up -d frontend
```

Or run the full stack:

```bash
docker compose up -d
```

**Verify:**
1. `docker compose ps` shows `docuchat_frontend` as `Up`
2. Open `http://localhost:5173` — the app loads without errors
3. The login page renders correctly
4. If the backend is also running, the full auth flow works through Docker

**Note:** In Docker, the frontend uses `VITE_API_URL=http://localhost/api` (set in `docker-compose.yml`), which routes through Nginx at `http://localhost` → Nginx proxies `/api/` to the backend. If Nginx is not running, the frontend will load but API calls will fail — that's expected.

## Potential Issues & Fixes

| Issue | Symptom | Fix |
|-------|---------|-----|
| Zod v4 import error | `Cannot find module 'zod/v4'` | Check zod v4 API; may need `import { z } from 'zod'` or different path |
| react-router-dom v7 API change | `createBrowserRouter` not found | Check v7 migration; may need `RouterProvider` from different path |
| Zustand v5 API change | Store creation error | Check v5 API; `create` may have different signature |
| Build fails with TS errors | `tsc` exits with code 1 | Fix each error — strict mode catches unused vars, missing types, etc. |
| Docker volume permission | Frontend container exits | Check `node_modules` volume mount in docker-compose |
| CORS errors in browser | API calls blocked | Ensure backend CORS settings include the frontend origin |

## Files That May Need Modification

| File | Possible Change |
|------|----------------|
| `src/frontend/src/pages/LoginPage.tsx` | Fix import paths or type errors |
| `src/frontend/src/pages/RegisterPage.tsx` | Fix import paths or type errors |
| `src/frontend/src/stores/authStore.ts` | Fix Zustand v5 API if needed |
| `src/frontend/src/api/axios.ts` | Fix import or type issues |
| `src/frontend/src/api/authApi.ts` | Fix import or type issues |
| `src/frontend/src/App.tsx` | Fix react-router-dom v7 API if needed |
| `src/frontend/src/main.tsx` | Minor fixes if any |
| `src/frontend/package.json` | Update dependency versions if needed |
| `docker-compose.yml` | Minor adjustments if frontend service has issues |

## Definition of Done

- [ ] `npm run build` succeeds with zero TypeScript errors
- [ ] `dist/` folder is produced
- [ ] All 8 manual smoke test items pass in browser
- [ ] Frontend runs in Docker via `docker compose up`
- [ ] No `console.error` in browser during happy path flows
- [ ] Responsive layout works at 375px viewport width
