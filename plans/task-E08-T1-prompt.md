# Task E08-T1: Install Missing Dependencies & shadcn Components

**Epic:** E08 — Frontend Auth & Layout
**Depends On:** E07 (all backend APIs live)
**Stack:** React 18 + Vite + TailwindCSS + shadcn/ui + React Router v6 + Axios + Zustand

---

## Context (What Already Exists)

The frontend scaffold is already in place at `src/frontend/`:

| File | Status | Notes |
|------|--------|-------|
| `src/frontend/package.json` | ✅ | Has React 18, Vite, TailwindCSS, `lucide-react`, `class-variance-authority`, `clsx`, `tailwind-merge`, `@radix-ui/react-slot` |
| `src/frontend/vite.config.ts` | ✅ | Has `@/` alias, `server.host: true`, polling for Docker |
| `src/frontend/tsconfig.json` | ✅ | Strict mode, path alias `@/*` |
| `src/frontend/tailwind.config.js` | ✅ | shadcn/ui theme colors, forms + typography plugins |
| `src/frontend/src/index.css` | ✅ | Tailwind directives + shadcn CSS variables (light + dark) |
| `src/frontend/src/components/ui/button.tsx` | ✅ | shadcn Button component already exists |
| `src/frontend/src/lib/utils.ts` | ✅ | `cn()` utility using `clsx` + `tailwind-merge` |
| `docker-compose.yml` | ✅ | Frontend service defined at line 224, uses `VITE_API_BASE_URL` env var |
| `docker/frontend/Dockerfile` | ✅ | Node 20 Alpine, npm install with Iranian mirror |

### What's Missing (This Task)

1. **Runtime npm dependencies:** `react-router-dom`, `axios`, `zustand`, `react-hook-form`, `zod`, `@hookform/resolvers`
2. **shadcn/ui components:** `input`, `label`, `form`, `card`, `dropdown-menu`, `avatar`, `toast`, `alert`, `separator`
3. **Environment files:** `.env.development`, `.env.production`
4. **shadcn CLI initialization:** No `components.json` exists yet

---

## Execution Steps (Strict Order)

### Step 1: Initialize shadcn CLI

Run the shadcn CLI init to create `components.json`:

```bash
cd src/frontend && npx shadcn@latest init
```

**Expected inputs for the interactive prompt:**
- Style: `Default`
- Base color: `Slate`
- CSS variables: `Yes`
- `@/` alias: `Yes` (it should auto-detect from tsconfig.json)
- React Server Components: `No`
- TailwindCSS config: `tailwind.config.js`
- CSS import: `src/index.css`
- Utils file: `src/lib/utils.ts`
- Components directory: `src/components/ui`

> **Note:** If the CLI prompts differ from above, use the defaults that match the existing setup (Slate theme, CSS variables enabled, `@/` alias).

### Step 2: Install Runtime Dependencies

```bash
cd src/frontend && npm install react-router-dom axios zustand react-hook-form zod @hookform/resolvers
```

This will update `package.json` and `package-lock.json`.

### Step 3: Add shadcn/ui Components

Add each component one at a time using the CLI:

```bash
cd src/frontend && npx shadcn@latest add input
cd src/frontend && npx shadcn@latest add label
cd src/frontend && npx shadcn@latest add form
cd src/frontend && npx shadcn@latest add card
cd src/frontend && npx shadcn@latest add dropdown-menu
cd src/frontend && npx shadcn@latest add avatar
cd src/frontend && npx shadcn@latest add toast
cd src/frontend && npx shadcn@latest add alert
cd src/frontend && npx shadcn@latest add separator
```

> **Note:** The `toast` component may also install `sonner` or `react-hot-toast` as a peer dependency — that's expected.

### Step 4: Create `.env.development`

Create file `src/frontend/.env.development`:

```env
# Frontend Development Environment
VITE_API_URL=http://localhost:8000/api
VITE_APP_NAME=DocuChat
VITE_APP_DESCRIPTION=AI Document Assistant
```

### Step 5: Create `.env.production`

Create file `src/frontend/.env.production`:

```env
# Frontend Production Environment
VITE_API_URL=/api
VITE_APP_NAME=DocuChat
VITE_APP_DESCRIPTION=AI Document Assistant
```

### Step 6: Update `docker-compose.yml` (if needed)

The `docker-compose.yml` at line 236 currently uses `VITE_API_BASE_URL`. The PRD and implementation plan specify `VITE_API_URL`. Update the env var name in the frontend service section:

```yaml
# Line 236 in docker-compose.yml — change:
VITE_API_BASE_URL: ${VITE_API_BASE_URL:-http://localhost/api}
# To:
VITE_API_URL: ${VITE_API_URL:-http://localhost/api}
```

Also add `VITE_APP_NAME` if not already present (it is at line 237, keep it).

### Step 7: Verify Everything Works

Run the dev server and check for errors:

```bash
cd src/frontend && npm run dev
```

Expected: Vite starts on `http://localhost:5173` with no compilation errors.

Then verify shadcn components are importable by creating a quick smoke test:

```bash
cd src/frontend && npx vitest run
```

If tests pass, the setup is complete.

---

## Files Modified

| File | Action |
|------|--------|
| `src/frontend/package.json` | Modified — new dependencies added |
| `src/frontend/package-lock.json` | Modified — auto-generated |
| `src/frontend/components.json` | **New** — created by shadcn CLI init |
| `src/frontend/.env.development` | **New** |
| `src/frontend/.env.production` | **New** |
| `docker-compose.yml` | Modified — `VITE_API_BASE_URL` → `VITE_API_URL` |

## Files Created by shadcn CLI (auto-generated)

| File | Component |
|------|-----------|
| `src/frontend/src/components/ui/input.tsx` | input |
| `src/frontend/src/components/ui/label.tsx` | label |
| `src/frontend/src/components/ui/form.tsx` | form |
| `src/frontend/src/components/ui/card.tsx` | card |
| `src/frontend/src/components/ui/dropdown-menu.tsx` | dropdown-menu |
| `src/frontend/src/components/ui/avatar.tsx` | avatar |
| `src/frontend/src/components/ui/toast.tsx` | toast |
| `src/frontend/src/components/ui/alert.tsx` | alert |
| `src/frontend/src/components/ui/separator.tsx` | separator |

---

## Acceptance Criteria

1. `npm run dev` starts without errors on `http://localhost:5173`
2. All 9 shadcn components are importable via `import { Input } from "@/components/ui/input"` etc.
3. `package.json` contains all 6 runtime dependencies
4. `.env.development` and `.env.production` exist with correct `VITE_API_URL` values
5. `docker-compose.yml` uses `VITE_API_URL` (not `VITE_API_BASE_URL`)
6. `components.json` exists at `src/frontend/components.json`

---

## Important Notes

- **Docker workflow:** The frontend runs inside Docker via `docker-compose up`. After making these changes, rebuild the frontend container with `docker-compose up --build frontend` to pick up the new dependencies.
- **shadcn CLI mirror:** The Dockerfile uses an Iranian npm mirror (`https://mirror2.chabokan.net/npm`). If running `npx shadcn` on the host, you may need to configure your own npm registry or use the default.
- **Existing button.tsx:** The `button.tsx` component already exists at `src/frontend/src/components/ui/button.tsx`. The shadcn CLI may try to overwrite it — if prompted, choose to **skip/keep existing** since it's already correct.
- **toast component:** shadcn's toast component may install `sonner` as a dependency. This is fine and expected.
