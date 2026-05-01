# WIP Context — E08-T5: Login Page (with infinite redirect fix)

## What Was Just Completed

E08-T5 is fully complete. The login page at `/login` has been implemented with React Hook Form + Zod v4 validation, centered card layout, error handling, and a link to the registration page. Both TypeScript check (`npx tsc --noEmit`) and Vite build (`npx vite build`) pass with zero errors.

### Files Created

| # | File | Purpose |
|---|------|---------|
| 1 | `src/frontend/src/pages/LoginPage.tsx` | Full login form with Zod validation, error handling, loading state, and centered card layout |

### Files Modified

| # | File | Change |
|---|------|--------|
| 2 | `src/frontend/src/App.tsx` | Added `import LoginPage from '@/pages/LoginPage'` and replaced `<div>Login Page</div>` placeholder with `<LoginPage />` |
| 3 | `src/frontend/src/stores/authStore.ts` | **Fix:** `initializeAuth()` now checks for `access_token` in localStorage before calling `getMeApi()`. If no token exists, it sets `isLoading: false` and returns early — prevents unnecessary 401 API call that triggered the refresh loop. |
| 4 | `src/frontend/src/api/axios.ts` | **Fix:** Extracted `redirectToLogin()` helper that checks `window.location.pathname` before redirecting. Only performs hard redirect (`window.location.href = '/login'`) if the user is NOT already on `/login` or `/register`. Applied to both `refreshTokens` failure paths (no refresh token + refresh API failure). |

### LoginPage Implementation Details

- **Zod Schema (`zod/v4`)**: Validates `email` (required + email format) and `password` (required only)
- **Form State**: `useForm` with `zodResolver`, default values as empty strings
- **Submit Flow**: Calls `authStore.login(values)` → on success navigates to `/dashboard` with `replace: true`; on failure sets appropriate error message
- **Error Handling (4 cases)**:
  - **401** → `"Invalid email or password"`
  - **400** → Shows `response.data.detail` or generic `"Invalid input. Please check your credentials."`
  - **Network error** → `"Unable to connect to the server. Please check your connection."`
  - **Other** → `"An unexpected error occurred. Please try again."`
- **Loading State**: `isSubmitting` disables all inputs and button; `Loader2` spinner appears inside the button
- **Error Banner**: shadcn `Alert` with `variant="destructive"` and `AlertCircle` icon; cleared on each new submit
- **Layout**: Centered card using `flex min-h-screen items-center justify-center` — standalone auth page, no AppShell
- **Accessibility**: `autoComplete="email"` / `autoComplete="current-password"`, `disabled` on inputs during submission
- **Register Link**: React Router `<Link to="/register">` styled as `text-primary hover:underline`

### Infinite Redirect Loop Fix

**Root cause:** `main.tsx` calls `initializeAuth()` on mount → `getMeApi()` fires with no token → 401 → Axios response interceptor catches it → refresh fails → `window.location.href = '/login'` → hard page reload → loop restarts.

**Fix 1 — `authStore.ts`:** `initializeAuth()` now checks `localStorage.getItem('access_token')` first. If absent, it sets `isLoading: false` and returns immediately without making any API call.

**Fix 2 — `axios.ts`:** Both hard redirects in `refreshTokens()` now go through `redirectToLogin()`, which guards against redirecting when already on `/login` or `/register`.

### Updated Route Structure

```
/login             → PublicRoute → LoginPage (replaced placeholder)
```

### Verification

- `npx tsc --noEmit` — zero errors
- `npx vite build` — builds successfully (dist/ directory created)

## Next Step

Proceed to E08-T6 (Register Page).
