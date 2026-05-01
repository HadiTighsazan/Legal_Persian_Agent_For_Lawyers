# WIP Context — E08-T3: Zustand Auth Store

## What Was Just Completed

E08-T3 is fully complete. Both files have been created and all 10 tests pass.

### Files Created

| # | File | Purpose |
|---|------|---------|
| 1 | `src/frontend/src/stores/authStore.ts` | Zustand auth store with state + actions |
| 2 | `src/frontend/tests/auth/authStore.test.ts` | 10 test cases for all store actions |

### File Details

#### `src/frontend/src/stores/authStore.ts`
- **State**: `user: User | null`, `isAuthenticated: boolean`, `isLoading: boolean`
- **Actions**:
  - `login(payload)`: Calls `loginApi`, saves tokens to localStorage, sets user + isAuthenticated
  - `register(payload)`: Calls `registerApi`, saves tokens to localStorage, sets user + isAuthenticated
  - `logout()`: Calls `logoutApi` with refresh token (errors swallowed), then calls `clearAuth()`
  - `clearAuth()`: Removes tokens from localStorage, resets state to initial
  - `initializeAuth()`: Sets `isLoading: true`, calls `getMeApi()`, on success sets user, on failure clears auth
  - `setUser(user)`: Optimistic update — directly sets the user object
- **Key decisions**:
  - No `zustand/middleware/persist` — only tokens go to localStorage, user object stays in memory
  - `logout` swallows API errors so local logout always proceeds
  - `clearAuth` is called via `getState()` inside async actions to avoid stale closures
  - All other API errors propagate to the caller

#### `src/frontend/tests/auth/authStore.test.ts`
- Uses `vi.mock('@/api/authApi')` at top level with auto-mocking
- Uses `globals: true` (no explicit imports from vitest to avoid collection-phase conflicts)
- Manually resets Zustand store state via `useAuthStore.setState(...)` in `resetStore()` helper
- Uses `vi.spyOn(Storage.prototype, 'setItem'|'removeItem')` instead of mocking localStorage globally
- 10 test cases:
  1. `login` — success: calls API, saves tokens, updates state
  2. `login` — error: propagates error, state unchanged
  3. `register` — success: calls API, saves tokens, updates state
  4. `register` — error: propagates error, state unchanged
  5. `logout` — success: calls API with refresh token, clears auth
  6. `logout` — API failure: clears auth anyway, no throw
  7. `clearAuth` — removes tokens, resets state
  8. `initializeAuth` — success: sets user, isAuthenticated, clears loading
  9. `initializeAuth` — failure: clears auth, stops loading
  10. `setUser` — updates user in store

### Config Changes
- `src/frontend/vitest.config.ts`: Added `resolve.alias` for `@` path (was missing, causing import failures for tests in `tests/` dir)
- `src/frontend/src/test/setup.ts`: Removed `beforeEach`/`afterEach` wrappers that were interfering with jsdom initialization

### Verification
- All 10 tests pass:
  ```
  ✓ tests/auth/authStore.test.ts (10 tests)
  ```

## Next Step

Proceed to E08-T4 (Auth pages — Login, Register) or E08-T5 (Layout components — Sidebar, Header).
