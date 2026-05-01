# WIP Context — E08-T2: TypeScript Types & Axios API Client

## What Was Just Completed

E08-T2 is fully complete. All 4 files have been created and all 8 tests pass.

### Files Created

| # | File | Purpose |
|---|------|---------|
| 1 | `src/frontend/src/types/auth.ts` | TypeScript interfaces for auth domain |
| 2 | `src/frontend/src/api/axios.ts` | Axios instance with request/response interceptors + token refresh queue |
| 3 | `src/frontend/src/api/authApi.ts` | Typed API functions wrapping axios instance |
| 4 | `src/frontend/tests/auth/axiosInterceptor.test.ts` | 6 tests for interceptor behavior |

### File Details

#### `src/frontend/src/types/auth.ts`
- `User`: `{ id, email, full_name (string | null), is_active, created_at, updated_at }`
- `AuthTokens`: `{ accessToken, refreshToken }`
- `AuthResponse`: `{ user, accessToken, refreshToken }`
- `LoginPayload`: `{ email, password }`
- `RegisterPayload`: `{ email, password, full_name }`

#### `src/frontend/src/api/axios.ts`
- **Axios instance**: `baseURL` from `VITE_API_URL ?? '/api'`, `Content-Type: application/json`, `withCredentials: false`
- **Request interceptor**: Reads `access_token` from localStorage, attaches `Authorization: Bearer <token>` header
- **Response interceptor (token refresh queue)**:
  - On 401: checks if request is to `/auth/refresh` itself → rejects immediately (avoids infinite loop)
  - Uses module-level `refreshPromise: Promise<boolean> | null` for queue mechanism
  - If no refresh in progress → starts one (POST `/auth/refresh` with stored refresh token)
  - If refresh already in progress → awaits the existing promise
  - On success: saves new tokens to localStorage, retries original request
  - On failure: clears localStorage, redirects to `/login`
- **Export**: named export `apiClient`

#### `src/frontend/src/api/authApi.ts`
- `loginApi(payload: LoginPayload): Promise<AuthResponse>`
- `registerApi(payload: RegisterPayload): Promise<AuthResponse>`
- `refreshTokenApi(refreshToken: string): Promise<AuthTokens>`
- `logoutApi(refreshToken: string): Promise<void>`
- `getMeApi(): Promise<User>`
- All functions fully typed — no `any`

#### `src/frontend/tests/auth/axiosInterceptor.test.ts`
- Mocks `axios` at module level using `vi.mock()`
- Uses `vi.resetModules()` in `beforeEach` to force fresh imports per test
- Uses `Object.assign(vi.fn(), {...})` for callable mock AxiosInstance
- 6 test cases covering:
  1. Request interceptor attaches Bearer token
  2. Request interceptor omits token when not in localStorage
  3. 401 triggers `/auth/refresh` and retries original request
  4. Queue mechanism: 3 concurrent 401s → only 1 refresh call
  5. Refresh failure clears localStorage and redirects to `/login`
  6. `/auth/refresh` 401 does NOT trigger another refresh (avoids loop)

### Config Changes
- `src/frontend/vitest.config.ts`: Added `'tests/**/*.test.{ts,tsx}'` to `include` array

### Verification
- All 8 tests pass (2 test files, 8 tests):
  ```
  ✓ src/App.test.tsx (2 tests)
  ✓ tests/auth/axiosInterceptor.test.ts (6 tests)
  ```

## Next Step

Proceed to E08-T3 (Auth pages — Login, Register) or E08-T4 (Layout components — Sidebar, Header).
