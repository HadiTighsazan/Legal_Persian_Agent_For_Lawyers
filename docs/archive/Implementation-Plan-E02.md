# Implementation Plan for E-02 Authentication & User Management



## Key Findings & Analysis

### 1. **Current State Assessment**
- **Database**: `users` table already exists with additional fields (`is_active`, `is_staff`) beyond PRD requirements
- **Missing**: `refresh_tokens` table needs to be created
- **Project Structure**: Django backend with existing `users/` app directory
- **API Registry**: Planned endpoints align with PRD requirements
- **Tech Stack**: Django REST Framework, PostgreSQL with pgvector, JWT authentication

### 2. **Compatibility Notes**
- The existing `users` table has extra fields (`is_active`, `is_staff`) - these should be preserved
- Need to add `refresh_tokens` table as specified in PRD
- API endpoints should follow the structure in API registry (no `/api/` prefix internally due to Nginx routing)

## Implementation Plan (Sequential)

### **Phase 1: Database Schema Updates** ✅

**Task 1.1: Create Migration for `refresh_tokens` Table**
- Create Django migration for `refresh_tokens` table with fields:
  - `id` (UUID, PK)
  - `user_id` (UUID, FK → users.id, CASCADE delete)
  - `token_hash` (VARCHAR(255), UNIQUE, NOT NULL)
  - `expires_at` (TIMESTAMP, NOT NULL)
  - `created_at` (TIMESTAMP, DEFAULT NOW())

**Task 1.2: Update `users` Table (if needed)**
- Verify existing `users` table matches PRD + additional fields
- Ensure `email` has UNIQUE constraint
- Add any missing fields from PRD (all appear present)

**Task 1.3: Run Migrations**
- Apply migrations to development database
- Test foreign key constraints

### **Phase 2: Core Authentication Models & Utilities**

**Task 2.1: User Model Enhancement**
- Enhance existing `User` model in `users/models.py`
- Add password hashing methods using `bcrypt` or Django's built-in `make_password`
- Add `verify_password()` method
- Ensure model follows `.clinerules` naming conventions

**Task 2.2: RefreshToken Model**
- Create `RefreshToken` model in `users/models.py`
- Add relationship to User model
- Add methods for token validation and expiration checking

**Task 2.3: JWT Utilities Module**
- Create `users/jwt_utils.py` with:
  - `generate_access_token(user, expires_in=15min)`
  - `generate_refresh_token(user, token_id, expires_in=7d)`
  - `verify_access_token(token)`
  - `verify_refresh_token(token)`
- Use `JWT_SECRET` from environment variables
- Token payloads: 
  - Access: `{ userId, email, type: 'access' }`
  - Refresh: `{ userId, tokenId, type: 'refresh' }`

### **Phase 3: Authentication Endpoints**

**Task 3.1: POST `/auth/register`**
- Location: `users/views.py` or `users/api/views.py`
- Validation: email format, password strength (min 8 chars)
- Check email uniqueness (return 409 Conflict if exists)
- Hash password, create user record
- Generate access + refresh tokens
- Store refresh token hash in `refresh_tokens` table
- Return 201 with `{ user, accessToken, refreshToken }`

**Task 3.2: POST `/auth/login`**
- Validate email/password in request body
- Find user by email, verify password
- Generate new access + refresh tokens
- Store refresh token hash
- Return 200 with `{ user, accessToken, refreshToken }`
- Invalid credentials → 401 Unauthorized

**Task 3.3: Authentication Middleware**
- Create `users/middleware.py` with `JWTAuthenticationMiddleware`
- Extract `Authorization: Bearer <token>` header
- Verify access token, attach `request.user = { userId, email }`
- Return 401 if token missing/invalid/expired
- Integrate with Django REST Framework authentication classes

### **Phase 4: Token Management Endpoints**

**Task 4.1: POST `/auth/refresh`**
- Accept `{ refreshToken }` in request body
- Verify refresh token JWT
- Check token hash exists in `refresh_tokens` and not expired
- Generate new access token (same user)
- Return 200 with `{ accessToken }`
- Invalid/expired token → 401

**Task 4.2: POST `/auth/logout`**
- Require authentication (use middleware)
- Accept `{ refreshToken }` in body
- Delete refresh token hash from `refresh_tokens` table
- Return 204 No Content
- Missing refresh token → 400

### **Phase 5: User Profile Endpoints**

**Task 5.1: GET `/users/me`**
- Require authentication
- Return current user profile: `{ id, email, full_name, created_at, is_active }`
- Unauthenticated → 401

**Task 5.2: PATCH `/users/me`**
- Require authentication
- Accept `{ full_name }` (optional), `{ email }` (optional)
- Validate email uniqueness if changing email
- Update user record
- Return 200 with updated user object
- Email conflict → 409, invalid email → 400

### **Phase 6: Testing & Documentation**

**Task 6.1: Unit Tests**
- Write tests for all authentication endpoints
- Test password hashing and verification
- Test JWT token generation and verification
- Test middleware authentication
- Follow TDD flow: RED → GREEN → REFACTOR

**Task 6.2: API Documentation Updates**
- Update `docs/references/api-registry.md` with implemented endpoints
- Update `docs/references/database-schema.md` with `refresh_tokens` table
- Add Swagger/ReDoc configuration if needed

**Task 6.3: Environment Variables**
- Update `.env.example` with:
  - `JWT_SECRET` (required)
  - `JWT_ACCESS_TOKEN_EXPIRY` (optional, default 15min)
  - `JWT_REFRESH_TOKEN_EXPIRY` (optional, default 7d)

## Technical Decisions & Considerations

### **1. JWT Library Choice**
- **Option A**: `djangorestframework-simplejwt` (batteries-included)
- **Option B**: `PyJWT` + custom implementation (more control)
- **Recommendation**: Use `djangorestframework-simplejwt` for faster implementation with built-in token refresh

### **2. Password Hashing**
- Use Django's `make_password()` and `check_password()` (uses PBKDF2 by default)
- Consider `bcrypt` for additional security if needed

### **3. Error Response Format**
- Consistent JSON structure: `{ error: { message, code } }`
- Follow existing patterns from API registry

### **4. Nginx Routing Note**
- Remember: Nginx routes `/api/` to Django backend
- Backend endpoints don't need `/api/` prefix internally
- Example: `POST /auth/register` not `POST /api/auth/register`

## Dependencies to Install
```bash
# Add to requirements.txt
djangorestframework-simplejwt==5.3.0
# or PyJWT if choosing custom implementation
```

## Risk Mitigation

1. **Database Migration Risk**: Test migrations in development first
2. **Token Security**: Store JWT_SECRET securely, rotate periodically
3. **Backward Compatibility**: Ensure existing health endpoint still works
4. **Performance**: Consider token blacklisting strategy for logout (currently stateless)

### ⚠️ CRITICAL: Network & Package Installation Guidelines
Due to network restrictions, you MUST NEVER skip package installations, create manual placeholder files, or use other workarounds when a network timeout occurs. You MUST use the following internal mirrors for all package installations. If an installation fails, try the next mirror in the priority list until it succeeds.

**1. Python / pip Packages:**
Whenever you need to install a Python package, use the `-i` flag with these mirrors strictly in this order:
* Priority 1: `https://mirror2.chabokan.net/pypi/simple`
* Priority 2: `https://mirror.iranserver.com/pypi/simple`
* Priority 3: `https://mirror-pypi.runflare.com/simple`
*(Example: `python -m pip install <package_name> -i https://mirror2.chabokan.net/pypi/simple`)*

**2. Node.js / npm Packages:**
Whenever you need to install frontend dependencies, you MUST bypass audit/fund and use these mirrors strictly in this order:
* Priority 1: `https://mirror2.chabokan.net/npm`
* Priority 2: `https://mirror-npm.runflare.com`
* Priority 3: `https://mirror.iranserver.com/npm`
*(Example: `npm install <package_name> --registry=https://mirror2.chabokan.net/npm --no-audit --no-fund`)*

## Success Metrics
- All 6 API endpoints implemented and tested
- JWT tokens work with 15min access / 7d refresh expiry
- Authentication middleware protects routes
- Password hashing prevents plain text storage
- All acceptance criteria from PRD met


---

