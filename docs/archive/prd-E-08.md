# PRD: Epic E08 — Frontend Auth & Layout
**File:** `docs/active-task/current-prd.md`  
**Status:** Active  
**Epic:** E08  
**Depends On:** E07 (fully done — all backend APIs are live)  
**Stack:** React 18 + Vite + TailwindCSS + shadcn/ui + React Router v6 + Axios + Zustand  

---

## 1. Overview & Goal

Build the complete frontend shell for the DocuChat application. This epic covers:
- Project scaffolding (Vite + React + Tailwind + shadcn/ui)
- Global layout (sidebar, topbar, responsive shell)
- Auth pages: Login, Register
- Route protection (PrivateRoute / PublicRoute guards)
- Auth state management (Zustand store + Axios interceptors with token refresh)
- User profile dropdown

**No document upload, chat, or search UI** — those belong to E09/E10.

---

## 2. API Contracts Used in This Epic

All endpoints are already live. Frontend must consume:

| Method | Endpoint | Usage |
|--------|----------|-------|
| `POST` | `/auth/register` | Register page form submission |
| `POST` | `/auth/login` | Login page form submission |
| `POST` | `/auth/refresh` | Axios interceptor — silent token refresh |
| `POST` | `/auth/logout` | Profile dropdown logout button |
| `GET` | `/users/me` | Fetch current user on app boot |
| `PATCH` | `/users/me` | (optional in this epic) Profile update |

**Auth header format:** `Authorization: Bearer <accessToken>`  
**Token storage:** `localStorage` — keys: `access_token`, `refresh_token`  
**Error format on 401:** `{"detail": "..."}` (DRF JWTAuthentication format)

---

## 3. Database Changes

**None.** This epic is frontend-only. Zero migrations required.

---

## 4. Tech Stack Constraints

- **React 18** with functional components + hooks only. No class components.
- **Vite** as build tool. Config at `src/frontend/vite.config.ts`.
- **TailwindCSS v3** — utility classes only, no custom CSS files except `index.css` for Tailwind directives.
- **shadcn/ui** — use CLI to add components (`npx shadcn-ui@latest add <component>`). Do not manually write shadcn component internals.
- **React Router v6** — `createBrowserRouter` + `RouterProvider`. No `<Switch>`.
- **Zustand** — single auth store. No Redux, no Context API for auth.
- **Axios** — single instance with interceptors. No fetch() for API calls.
- **React Hook Form + Zod** — all form validation. No manual `useState` for form fields.
- **TypeScript** — strict mode. All files `.tsx` / `.ts`. No `any` types.
- **TDD:** Write Vitest + React Testing Library tests alongside each component (not after).

---

## 5. Folder Structure (Must Follow Exactly)

```
src/frontend/
├── src/
│   ├── api/
│   │   └── axios.ts              # Axios instance + interceptors
│   ├── components/
│   │   ├── ui/                   # shadcn/ui components (auto-generated, do not edit)
│   │   ├── layout/
│   │   │   ├── AppShell.tsx      # Main authenticated layout wrapper
│   │   │   ├── Sidebar.tsx       # Left navigation sidebar
│   │   │   └── Topbar.tsx        # Top navigation bar
│   │   └── auth/
│   │       ├── PrivateRoute.tsx  # Auth guard for protected pages
│   │       └── PublicRoute.tsx   # Redirect logged-in users away from auth pages
│   ├── pages/
│   │   ├── LoginPage.tsx
│   │   ├── RegisterPage.tsx
│   │   └── DashboardPage.tsx     # Placeholder only in this epic
│   ├── stores/
│   │   └── authStore.ts          # Zustand auth store
│   ├── types/
│   │   └── auth.ts               # TypeScript interfaces
│   ├── App.tsx                   # Router setup
│   └── main.tsx                  # Entry point
├── tests/
│   ├── auth/
│   └── layout/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

---

## 6. TypeScript Interfaces (Source of Truth)

```typescript
// src/types/auth.ts

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

export interface AuthResponse {
  user: User;
  accessToken: string;
  refreshToken: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  full_name: string;
}
```

---

## 7. Micro-Tasks

---

### Task E08-T1: Project Scaffolding & Toolchain Setup

**Goal:** Create a working, fully configured frontend project from scratch.

**Steps:**
1. Scaffold Vite + React + TypeScript project at `src/frontend/`:
   ```bash
   npm create vite@latest frontend -- --template react-ts
   ```
2. Install all required dependencies:
   ```bash
   npm install react-router-dom axios zustand react-hook-form zod @hookform/resolvers
   npm install -D tailwindcss postcss autoprefixer vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
   ```
3. Initialize Tailwind:
   ```bash
   npx tailwindcss init -p
   ```
4. Initialize shadcn/ui:
   ```bash
   npx shadcn-ui@latest init
   ```
   Select: TypeScript, Default style, Slate base color, `src/components/ui` for components.
5. Add initial shadcn components needed for this epic:
   ```bash
   npx shadcn-ui@latest add button input label form card dropdown-menu avatar toast
   ```
6. Configure `vite.config.ts`:
   - Set `server.proxy` to forward `/api` → `http://localhost:8000` (matches Nginx config)
   - Configure Vitest: `environment: 'jsdom'`, `setupFiles: ['./tests/setup.ts']`
7. Configure `tsconfig.json`: `"strict": true`, path alias `@/*` → `./src/*`
8. Create `tests/setup.ts` with `@testing-library/jest-dom` import.
9. Add `tailwind.config.ts` content paths: `["./index.html", "./src/**/*.{ts,tsx}"]`

**Acceptance Criteria:**
- [ ] `npm run dev` starts Vite dev server with no errors
- [ ] `npm run test` runs Vitest with zero test failures (empty test suite is OK)
- [ ] `npm run build` produces a `dist/` folder with no TypeScript errors
- [ ] shadcn/ui `<Button>` can be imported and renders in `App.tsx` without error
- [ ] Path alias `@/` resolves correctly

**Files Created/Modified:**
- `src/frontend/` (entire directory)
- `src/frontend/vite.config.ts`
- `src/frontend/tailwind.config.ts`
- `src/frontend/tsconfig.json`
- `src/frontend/package.json`
- `src/frontend/tests/setup.ts`

---

### Task E08-T2: TypeScript Types & Axios API Client

**Goal:** Create the typed API layer with automatic token refresh.

**Steps:**

1. Create `src/types/auth.ts` with all interfaces defined in Section 6 above.

2. Create `src/api/axios.ts`:
   ```typescript
   // Axios instance with:
   // - baseURL: import.meta.env.VITE_API_URL ?? '/api'
   // - default headers: Content-Type: application/json
   ```
3. Implement **request interceptor**: attach `Authorization: Bearer <accessToken>` from `localStorage.getItem('access_token')` to every request.

4. Implement **response interceptor** for token refresh:
   - On `401` response:
     1. Read `refresh_token` from localStorage
     2. If no refresh token → clear storage → redirect to `/login`
     3. POST to `/auth/refresh` with `{ refreshToken }`
     4. On success: save new `access_token` + `refresh_token` to localStorage, retry original request
     5. On failure: clear storage → redirect to `/login`
   - Implement **queue mechanism**: if multiple requests fail with 401 simultaneously, only one refresh call is made; others wait and retry after.

5. Create `src/api/authApi.ts` with typed functions:
   ```typescript
   export const loginApi = (payload: LoginPayload): Promise<AuthResponse>
   export const registerApi = (payload: RegisterPayload): Promise<AuthResponse>
   export const refreshTokenApi = (refreshToken: string): Promise<AuthTokens>
   export const logoutApi = (refreshToken: string): Promise<void>
   export const getMeApi = (): Promise<User>
   ```

**Acceptance Criteria:**
- [ ] All API functions are fully typed — no `any`
- [ ] Request interceptor attaches Bearer token when token exists in localStorage
- [ ] 401 interceptor calls `/auth/refresh` exactly once even if 3 concurrent requests fail
- [ ] On refresh failure, localStorage is cleared and browser is redirected to `/login`
- [ ] Unit test: mock axios, verify interceptor retries request after successful refresh
- [ ] Unit test: mock axios, verify redirect to `/login` after failed refresh

**Files Created:**
- `src/frontend/src/types/auth.ts`
- `src/frontend/src/api/axios.ts`
- `src/frontend/src/api/authApi.ts`
- `src/frontend/tests/auth/axiosInterceptor.test.ts`

---

### Task E08-T3: Zustand Auth Store

**Goal:** Centralized auth state — single source of truth for user session.

**Store Shape:**
```typescript
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;        // true during initial boot check
  
  // Actions
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  initializeAuth: () => Promise<void>;  // called once on app mount
  setUser: (user: User) => void;
  clearAuth: () => void;
}
```

**Implementation rules:**
- `login()`: call `loginApi()`, save tokens to localStorage (`access_token`, `refresh_token`), set `user` in store.
- `register()`: call `registerApi()`, save tokens, set `user`. Same pattern as login.
- `logout()`: call `logoutApi()` with current refresh token, call `clearAuth()` regardless of API success/failure.
- `clearAuth()`: remove `access_token` and `refresh_token` from localStorage, set `user: null`, `isAuthenticated: false`.
- `initializeAuth()`: set `isLoading: true` → call `getMeApi()` → on success set user + `isAuthenticated: true` → on failure call `clearAuth()` → always set `isLoading: false`.
- Persist: do NOT use `zustand/middleware/persist`. Manual localStorage management only (tokens only, never user object in localStorage).

**Acceptance Criteria:**
- [ ] `isLoading` is `true` during `initializeAuth()` and `false` after
- [ ] After `login()`, `isAuthenticated === true` and `user` is populated
- [ ] After `logout()`, localStorage has no `access_token` or `refresh_token`
- [ ] `logout()` does NOT throw even if the API call fails (network error)
- [ ] Unit test: login action saves tokens and sets user
- [ ] Unit test: logout clears all state even on API error
- [ ] Unit test: initializeAuth sets isLoading correctly through the full lifecycle

**Files Created:**
- `src/frontend/src/stores/authStore.ts`
- `src/frontend/tests/auth/authStore.test.ts`

---

### Task E08-T4: Route Structure & Auth Guards

**Goal:** Set up application routing with protected and public route guards.

**Route Map:**
```
/login          → LoginPage      (PublicRoute — redirect to /dashboard if already logged in)
/register       → RegisterPage   (PublicRoute — redirect to /dashboard if already logged in)
/dashboard      → DashboardPage  (PrivateRoute)
/               → redirect to /dashboard
* (404)         → redirect to /dashboard (or a 404 page)
```

**Implementation:**

1. Create `src/components/auth/PrivateRoute.tsx`:
   - Read `isAuthenticated` and `isLoading` from authStore
   - While `isLoading`: render a full-screen centered spinner (use shadcn/ui `Loader2` icon)
   - If `!isAuthenticated`: `<Navigate to="/login" replace />`
   - Otherwise: render `<Outlet />`

2. Create `src/components/auth/PublicRoute.tsx`:
   - While `isLoading`: render same full-screen spinner
   - If `isAuthenticated`: `<Navigate to="/dashboard" replace />`
   - Otherwise: render `<Outlet />`

3. Create `src/App.tsx` using `createBrowserRouter`:
   ```typescript
   const router = createBrowserRouter([
     { path: '/', element: <Navigate to="/dashboard" replace /> },
     {
       element: <PublicRoute />,
       children: [
         { path: '/login', element: <LoginPage /> },
         { path: '/register', element: <RegisterPage /> },
       ]
     },
     {
       element: <PrivateRoute />,
       children: [
         {
           element: <AppShell />,
           children: [
             { path: '/dashboard', element: <DashboardPage /> },
           ]
         }
       ]
     }
   ]);
   ```

4. In `src/main.tsx`: call `authStore.getState().initializeAuth()` before rendering `<RouterProvider>`.

**Acceptance Criteria:**
- [ ] Unauthenticated user visiting `/dashboard` is redirected to `/login`
- [ ] Authenticated user visiting `/login` is redirected to `/dashboard`
- [ ] Full-screen spinner is shown during `isLoading === true` (no flash of wrong content)
- [ ] `initializeAuth()` is called exactly once on app mount
- [ ] Unit test: PrivateRoute redirects unauthenticated users
- [ ] Unit test: PrivateRoute renders outlet for authenticated users
- [ ] Unit test: PublicRoute redirects authenticated users to /dashboard

**Files Created:**
- `src/frontend/src/components/auth/PrivateRoute.tsx`
- `src/frontend/src/components/auth/PublicRoute.tsx`
- `src/frontend/src/App.tsx`
- `src/frontend/src/main.tsx`
- `src/frontend/src/pages/DashboardPage.tsx` (placeholder — `<h1>Dashboard</h1>`)
- `src/frontend/tests/auth/PrivateRoute.test.tsx`
- `src/frontend/tests/auth/PublicRoute.test.tsx`

---

### Task E08-T5: Login Page

**Goal:** A fully functional, validated Login form that calls `/auth/login`.

**UI Specification:**
- Full-page centered card layout (not inside AppShell — auth pages are standalone)
- App logo / name at top of card
- Form fields: `email` (type=email), `password` (type=password)
- Submit button: "Sign In" — shows loading spinner while submitting
- Link to Register page: "Don't have an account? Sign up"
- Error banner (shadcn `Alert` with destructive variant) shown below form on API error
- No field-level error display for API errors — only form-level banner

**Form Validation (Zod schema):**
```typescript
const loginSchema = z.object({
  email: z.string().email("Please enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});
```

**Behavior:**
1. On submit: disable form, show spinner in button
2. Call `authStore.login(payload)`
3. On success: router navigates to `/dashboard` (store + PrivateRoute handles this automatically)
4. On error:
   - `401` from API: show "Invalid email or password"
   - `400` from API: show "Please check your input and try again"
   - Network error: show "Connection error. Please check your network."
   - Re-enable form after error

**Acceptance Criteria:**
- [ ] Form does not submit if email is invalid format
- [ ] Form does not submit if password is empty
- [ ] Button is disabled and shows spinner during submission
- [ ] Successful login navigates to `/dashboard`
- [ ] 401 error shows correct human-readable message
- [ ] Network error is caught and displayed (does not crash)
- [ ] Unit test: renders form fields correctly
- [ ] Unit test: shows validation error on empty submit
- [ ] Unit test: calls authStore.login with correct payload
- [ ] Unit test: displays error banner on 401
- [ ] Unit test: button is disabled during loading

**Files Created:**
- `src/frontend/src/pages/LoginPage.tsx`
- `src/frontend/tests/auth/LoginPage.test.tsx`

---

### Task E08-T6: Register Page

**Goal:** A fully functional, validated Register form that calls `/auth/register`.

**UI Specification:**
- Same card layout as LoginPage (reuse the outer card/layout structure)
- Form fields: `full_name`, `email` (type=email), `password` (type=password), `confirmPassword` (type=password)
- Submit button: "Create Account" — loading spinner during submit
- Link to Login page: "Already have an account? Sign in"
- Error banner for API errors (same pattern as LoginPage)
- Password strength hint: a small text below password field: "Must be at least 8 characters"

**Form Validation (Zod schema):**
```typescript
const registerSchema = z.object({
  full_name: z.string().min(1, "Full name is required").max(255),
  email: z.string().email("Please enter a valid email address"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  confirmPassword: z.string(),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords do not match",
  path: ["confirmPassword"],
});
```

**Behavior:**
1. On submit: call `authStore.register({ email, password, full_name })`
2. `confirmPassword` is NOT sent to the API — it's only for client-side validation
3. On success: router navigates to `/dashboard`
4. On error:
   - `409` from API: show "An account with this email already exists"
   - `400` from API: show "Please check your input and try again"
   - Network error: show "Connection error. Please check your network."

**Acceptance Criteria:**
- [ ] `confirmPassword` mismatch shows inline error under confirmPassword field
- [ ] Password shorter than 8 chars shows validation error
- [ ] `confirmPassword` is NOT included in the API call payload
- [ ] 409 conflict shows correct human-readable message
- [ ] Successful registration navigates to `/dashboard`
- [ ] Unit test: refine validation catches password mismatch
- [ ] Unit test: API payload does not include confirmPassword field
- [ ] Unit test: displays 409 error correctly
- [ ] Unit test: shows loading state on submit

**Files Created:**
- `src/frontend/src/pages/RegisterPage.tsx`
- `src/frontend/tests/auth/RegisterPage.test.tsx`

---

### Task E08-T7: App Shell Layout (Sidebar + Topbar)

**Goal:** The persistent authenticated layout with sidebar navigation and top bar.

**AppShell Structure:**
```
┌─────────────────────────────────────────────────────┐
│  Topbar (h-14, full width, fixed top)               │
├────────────┬────────────────────────────────────────┤
│            │                                        │
│  Sidebar   │  Main Content Area                     │
│  (w-64)    │  <Outlet /> renders here               │
│            │                                        │
│            │                                        │
└────────────┴────────────────────────────────────────┘
```

**Topbar (`src/components/layout/Topbar.tsx`):**
- Left: App name/logo ("DocuChat")
- Right: User avatar + name (from `authStore.user`) as a `DropdownMenu` trigger
- Dropdown items:
  - "My Profile" (disabled/placeholder in this epic)
  - Separator
  - "Sign Out" — calls `authStore.logout()` then navigates to `/login`

**Sidebar (`src/components/layout/Sidebar.tsx`):**
- Fixed left, full height, below topbar
- Navigation items for this epic (placeholder links — pages built in E09/E10):
  - 📄 Documents → `/documents` (disabled/grayed — not built yet)
  - 💬 Conversations → `/conversations` (disabled/grayed — not built yet)
  - 📊 Dashboard → `/dashboard` (active)
- Active item is visually highlighted
- Must be responsive: on mobile (`< md` breakpoint) sidebar is hidden by default, toggled by a hamburger button in Topbar

**AppShell (`src/components/layout/AppShell.tsx`):**
- Wraps Topbar + Sidebar + `<Outlet />`
- Manages sidebar open/close state for mobile via `useState`
- Passes toggle handler to Topbar

**DashboardPage (update from placeholder):**
- Show a proper welcome message: "Welcome back, {user.full_name ?? user.email}"
- Show 3 placeholder stat cards (Documents, Conversations, Queries) all showing "—"
- This gives the layout something to render and validates the shell

**Acceptance Criteria:**
- [ ] Topbar renders user name from authStore correctly
- [ ] Clicking "Sign Out" calls logout and redirects to `/login`
- [ ] Sidebar is visible on desktop (≥768px)
- [ ] Sidebar is hidden on mobile (<768px) and togglable via hamburger button
- [ ] Active route is visually distinguished in sidebar
- [ ] `<Outlet />` content area fills remaining space without overflow
- [ ] Unit test: Topbar renders user email when full_name is null
- [ ] Unit test: clicking Sign Out triggers authStore.logout
- [ ] Unit test: DashboardPage shows welcome with user name

**Files Created/Modified:**
- `src/frontend/src/components/layout/AppShell.tsx`
- `src/frontend/src/components/layout/Sidebar.tsx`
- `src/frontend/src/components/layout/Topbar.tsx`
- `src/frontend/src/pages/DashboardPage.tsx` (updated from placeholder)
- `src/frontend/tests/layout/AppShell.test.tsx`
- `src/frontend/tests/layout/Topbar.test.tsx`

---

### Task E08-T8: Environment Config, Docker Integration & Final QA

**Goal:** Wire everything together for local development and ensure the app runs in Docker.

**Steps:**

1. Create `src/frontend/.env.development`:
   ```
   VITE_API_URL=http://localhost/api
   ```
2. Create `src/frontend/.env.production`:
   ```
   VITE_API_URL=https://api.yourdomain.com/api
   ```
3. Update `docker-compose.yml` to add frontend service:
   ```yaml
   frontend:
     build:
       context: ./src/frontend
       dockerfile: Dockerfile
     ports:
       - "5173:5173"
     volumes:
       - ./src/frontend:/app
       - /app/node_modules
     environment:
       - VITE_API_URL=http://localhost/api
     command: npm run dev -- --host
   ```
4. Create `src/frontend/Dockerfile`:
   ```dockerfile
   FROM node:20-alpine
   WORKDIR /app
   COPY package*.json ./
   RUN npm install
   COPY . .
   EXPOSE 5173
   CMD ["npm", "run", "dev", "--", "--host"]
   ```
5. Update Nginx config to also proxy `/` to the frontend dev server (or serve static build).
6. Run full test suite: `npm run test -- --coverage`. Coverage must be ≥ 70% for `src/stores/`, `src/api/`, `src/components/auth/`.
7. Run `npm run build` — zero TypeScript errors, zero warnings.
8. Manual smoke test checklist:
   - Register a new user → lands on Dashboard
   - Logout → lands on Login
   - Login with registered user → lands on Dashboard
   - Access `/dashboard` without token in a fresh browser tab → redirects to `/login`
   - Access `/login` while logged in → redirects to `/dashboard`
   - Refresh page while logged in → stays on current page (initializeAuth restores session)

**Acceptance Criteria:**
- [ ] `docker compose up` starts frontend service with no errors
- [ ] `npm run test -- --coverage` shows ≥ 70% coverage on auth and store files
- [ ] `npm run build` succeeds with 0 TypeScript errors
- [ ] All 8 items in the manual smoke test pass
- [ ] No console errors in browser during normal user flow

**Files Created/Modified:**
- `src/frontend/.env.development`
- `src/frontend/.env.production`
- `src/frontend/Dockerfile`
- `docker-compose.yml` (add frontend service)
- Nginx config update (if needed)

---

## 8. Task Execution Order

```
E08-T1 → E08-T2 → E08-T3 → E08-T4 → E08-T5 → E08-T6 → E08-T7 → E08-T8
```

Each task must be completed and its tests passing before moving to the next. Do not batch tasks.

---

## 9. Global Rules (from .clinerules)

- **TDD:** Write the test file first (or alongside), never after.
- **No `any` types** in TypeScript. Use `unknown` and narrow, or define proper interfaces.
- **No direct `fetch()`** — always use the configured Axios instance from `src/api/axios.ts`.
- **No inline styles** — Tailwind utility classes only.
- **No hardcoded strings** for API URLs — always read from `import.meta.env.VITE_API_URL`.
- **Component files** must be under 200 lines. Extract sub-components if needed.
- **Forms** must use React Hook Form + Zod. No raw `useState` for form field values.
- **Commits** are per micro-task, not per file.
- shadcn/ui components in `src/components/ui/` are **generated — never edit manually**.

---

## 10. Definition of Done for E08

- [ ] All 8 micro-tasks completed with passing tests
- [ ] `npm run build` produces artifact with 0 errors
- [ ] Coverage ≥ 70% on auth + store modules
- [ ] Frontend runs in Docker via `docker compose up`
- [ ] Login, Register, Logout flows work end-to-end against real backend (E07 APIs)
- [ ] Token refresh interceptor silently renews session (verified via network tab)
- [ ] Responsive layout works on mobile viewport (375px width)
- [ ] No `console.error` in browser during happy path flows