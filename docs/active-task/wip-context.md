# WIP Context — E08-T4: Route Structure & Auth Guards

## What Was Just Completed

E08-T4 is fully complete. All 5 files have been created/modified and both TypeScript check (`npx tsc --noEmit`) and Vite build (`npx vite build`) pass with zero errors.

### Files Created

| # | File | Purpose |
|---|------|---------|
| 1 | `src/frontend/src/components/auth/PrivateRoute.tsx` | Auth guard — shows spinner while loading, redirects to `/login` if unauthenticated, renders `<Outlet />` for children |
| 2 | `src/frontend/src/components/auth/PublicRoute.tsx` | Reverse auth guard — shows spinner while loading, redirects to `/dashboard` if already authenticated, renders `<Outlet />` for children |
| 3 | `src/frontend/src/pages/DashboardPage.tsx` | Placeholder dashboard page — renders `<h1>Dashboard</h1>` |

### Files Modified

| # | File | Change |
|---|------|--------|
| 4 | `src/frontend/src/App.tsx` | Complete rewrite — replaced landing page with `createBrowserRouter` + `RouterProvider` route config |
| 5 | `src/frontend/src/main.tsx` | Added `useAuthStore.getState().initializeAuth()` call before `ReactDOM.createRoot` to initialize auth on app mount |
| 6 | `src/frontend/src/App.test.tsx` | Removed unused `render`/`screen` imports that caused TS error `TS6192` |

### Route Structure

```
/                  → Navigate to /dashboard
/login             → PublicRoute → <div>Login Page</div> (placeholder)
/register          → PublicRoute → <div>Register Page</div> (placeholder)
/dashboard         → PrivateRoute → DashboardPage
* (404)            → Navigate to /dashboard
```

### Key Implementation Details

- **`PrivateRoute.tsx`**: Uses `useAuthStore` with selector functions (`s.isAuthenticated`, `s.isLoading`) for optimal re-render behavior. Shows full-screen centered `Loader2` spinner while auth is initializing. Uses `<Navigate to="/login" replace />` — `replace` prevents back-button from returning to the protected page.
- **`PublicRoute.tsx`**: Same spinner pattern. Redirects already-authenticated users to `/dashboard` (prevents logged-in users from seeing login/register pages).
- **`App.tsx`**: Uses `createBrowserRouter` (React Router v6/v7 compatible). `PublicRoute` and `PrivateRoute` use `<Outlet />` internally. `/login` and `/register` use placeholder `<div>` elements (to be replaced by T5/T6). `AppShell` wrapper is commented out (to be added in T7).
- **`main.tsx`**: `initializeAuth()` is called **before** `ReactDOM.createRoot` — starts auth initialization immediately, preventing flash of unauthenticated content on page refresh.

### Verification

- `npx tsc --noEmit` — zero errors
- `npx vite build` — builds successfully (dist/ directory created)

## Next Step

Proceed to E08-T5 (Login Page) or E08-T6 (Register Page).
