# PRD: E-02 Authentication & User Management

**Epic ID:** E-02  
**Status:** ⏳ Todo  

---

## Overview
Implement JWT-based authentication system with user registration, login, token refresh, logout, profile management, and middleware guards.

---

## Database Changes Required

**Table:** `users`  
- `id` (UUID, PK)
- `email` (VARCHAR, UNIQUE, NOT NULL)
- `password_hash` (VARCHAR, NOT NULL)
- `full_name` (VARCHAR)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

**Table:** `refresh_tokens`  
- `id` (UUID, PK)
- `user_id` (UUID, FK → users.id)
- `token_hash` (VARCHAR, UNIQUE, NOT NULL)
- `expires_at` (TIMESTAMP, NOT NULL)
- `created_at` (TIMESTAMP)

---

## API Endpoints Required

1. `POST /api/auth/register`
2. `POST /api/auth/login`
3. `POST /api/auth/refresh`
4. `POST /api/auth/logout`
5. `GET /api/users/me`
6. `PATCH /api/users/me`

---

## Micro-Tasks (Sequential)

### **Task 1: Database Schema Setup**
- Create migration for `users` table with fields above
- Create migration for `refresh_tokens` table
- Run migrations
- **Acceptance Criteria:**
  - Both tables exist in database
  - Foreign key constraint on `refresh_tokens.user_id` works
  - Unique constraint on `users.email` enforced

---

### **Task 2: User Model & Password Hashing**
- Create `User` model mapped to `users` table
- Implement password hashing utility (bcrypt/argon2)
- Add method to verify password
- **Acceptance Criteria:**
  - Passwords never stored in plain text
  - `User.verifyPassword(plain)` returns boolean
  - Model follows `.clinerules` naming conventions

---

### **Task 3: JWT Utilities**
- Create JWT signing function (access token: 15min, refresh token: 7d)
- Create JWT verification function
- Store secret in environment variable `JWT_SECRET`
- **Acceptance Criteria:**
  - Access token payload includes `{ userId, email }`
  - Refresh token payload includes `{ userId, tokenId }`
  - Tokens can be verified and decoded

---

### **Task 4: POST /api/auth/register**
- Validate email format and password strength (min 8 chars)
- Check email uniqueness
- Hash password, create user record
- Return `{ user: { id, email, full_name }, accessToken, refreshToken }`
- Store refresh token hash in `refresh_tokens` table
- **Acceptance Criteria:**
  - Duplicate email returns 409 Conflict
  - Weak password returns 400 Bad Request
  - Success returns 201 with tokens

---

### **Task 5: POST /api/auth/login**
- Validate email/password in request body
- Find user by email
- Verify password
- Generate access + refresh tokens
- Store refresh token hash
- Return `{ user, accessToken, refreshToken }`
- **Acceptance Criteria:**
  - Invalid credentials return 401 Unauthorized
  - Success returns 200 with tokens
  - Old refresh tokens for same user remain valid (no revocation yet)

---

### **Task 6: Authentication Middleware**
- Create `authMiddleware` that extracts `Authorization: Bearer <token>`
- Verify access token
- Attach `req.user = { userId, email }` to request
- Return 401 if token missing/invalid/expired
- **Acceptance Criteria:**
  - Protected routes reject requests without valid token
  - `req.user` populated on success
  - Middleware follows `.clinerules` error handling

---

### **Task 7: POST /api/auth/refresh**
- Accept `{ refreshToken }` in body
- Verify refresh token JWT
- Check token hash exists in `refresh_tokens` and not expired
- Generate new access token (same user)
- Return `{ accessToken }`
- **Acceptance Criteria:**
  - Invalid/expired refresh token returns 401
  - Success returns 200 with new access token
  - Refresh token itself is NOT rotated (reusable until expiry)

---

### **Task 8: POST /api/auth/logout**
- Require authentication (use `authMiddleware`)
- Accept `{ refreshToken }` in body
- Delete refresh token hash from `refresh_tokens` table
- Return 204 No Content
- **Acceptance Criteria:**
  - Logged-out refresh token cannot be reused
  - Access token remains valid until expiry (stateless)
  - Missing refresh token returns 400

---

### **Task 9: GET /api/users/me**
- Require authentication
- Return current user profile: `{ id, email, full_name, created_at }`
- **Acceptance Criteria:**
  - Unauthenticated request returns 401
  - Returns correct user data for token owner

---

### **Task 10: PATCH /api/users/me**
- Require authentication
- Accept `{ full_name }` (optional), `{ email }` (optional, validate uniqueness)
- Update user record
- Return updated user object
- **Acceptance Criteria:**
  - Email conflict returns 409
  - Invalid email format returns 400
  - Success returns 200 with updated user

---

## Global Acceptance Criteria
- All endpoints follow REST conventions from `.clinerules`
- All errors return consistent JSON structure: `{ error: { message, code } }`
- All timestamps in ISO 8601 format
- No sensitive data (password_hash, token_hash) in API responses
- All database queries use parameterized statements (SQL injection safe)
- Environment variables documented in `.env.example`

---

## Dependencies
- JWT library (e.g., `jsonwebtoken`)
- Password hashing library (e.g., `bcrypt`)
- Database migration tool

---

