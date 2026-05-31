# WIP Context — Login Connection Error Fix

## What Was Just Completed

Implemented the fix for the login connection error. The root cause was that the production frontend build (served by nginx at `http://localhost`) had `VITE_API_URL=http://localhost:8000` hardcoded in the JS bundle, causing cross-origin requests that failed CORS preflight.

### Changes Made

#### 1. [`docker/frontend/Dockerfile`](../../docker/frontend/Dockerfile) — Refactored builder stage

**Problem:** The `builder` stage inherited from `dev` (`FROM dev AS builder`), which copies the entire `src/frontend/` directory including `.env.development`. When `npm run build` ran, Vite read `.env.development` and used `VITE_API_URL=http://localhost:8000`.

**Fix:** Refactored into 4 stages:
- **`dev`** — Unchanged, for `npm run dev` (hot-reload)
- **`deps`** — NEW stage: installs production dependencies only (clean `node:20-alpine`, no source copy)
- **`builder`** — Now inherits from `deps` (not `dev`), copies `src/frontend/`, and explicitly sets `ARG VITE_API_URL=/api` + `ENV VITE_API_URL=/api` to override any `.env` file
- **`production`** — Unchanged, serves via nginx

#### 2. [`docker-compose.yml`](../../docker-compose.yml) — Updated nginx service

**Problem:** The nginx service built from `./docker/nginx` context with its own Dockerfile, and mounted `./src/frontend/dist` as a host volume. This meant:
1. The nginx Dockerfile didn't have access to the frontend builder stage
2. The host's `dist/` (which was stale from May 26) was served, not the image's built-in dist

**Fix:** Changed nginx service to:
- Build from project root context (`.`)
- Use `dockerfile: ./docker/frontend/Dockerfile` with `target: production`
- Removed the `./src/frontend/dist:/usr/share/nginx/html:ro` volume mount (the dist is now baked into the image)

Now the nginx container gets the frontend assets directly from the multi-stage build, with `VITE_API_URL=/api` baked in.

### Request Flow After Fix

```
Browser → nginx :80 → /api/auth/login/ → proxy_pass http://backend/ → Django
                                              ^ strips /api prefix
Same-origin request (http://localhost → http://localhost), no CORS needed
```

## Current State

All code changes are complete. The fix needs to be built and verified.

## Next Step

Rebuild and verify:
1. `docker-compose build nginx` (rebuilds frontend with correct VITE_API_URL)
2. `docker-compose up -d nginx` (restarts nginx)
3. Open `http://localhost` in browser
4. Try to log in with invalid credentials → should show "Invalid email or password"
5. Check browser DevTools → Network tab → verify request goes to `/api/auth/login/`
