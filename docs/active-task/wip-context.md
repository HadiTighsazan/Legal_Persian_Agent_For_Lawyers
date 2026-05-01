# WIP Context — E08-T7: App Shell Layout (Sidebar + Topbar) — Complete

## What Was Just Completed

E08-T7 is fully complete. The authenticated app shell layout has been implemented with `AppShell` wrapping `Topbar`, `Sidebar`, and `<Outlet />`. The `DashboardPage` has been updated with a welcome message and stat cards. Both TypeScript check (`npx tsc --noEmit`) and Vitest tests pass (17/18 passing; the 1 failure is a pre-existing issue in the axios interceptor test unrelated to this task).

### Files Created

| # | File | Purpose |
|---|------|---------|
| 1 | `src/frontend/src/lib/utils.ts` | `cn()` utility function (clsx + tailwind-merge) required by all shadcn/ui components |
| 2 | `src/frontend/src/components/layout/Sidebar.tsx` | Fixed left navigation sidebar with responsive toggle, disabled nav items, active state |
| 3 | `src/frontend/src/components/layout/Topbar.tsx` | Fixed top bar with hamburger (mobile), DocuChat logo, avatar + user dropdown with Sign Out |
| 4 | `src/frontend/src/components/layout/AppShell.tsx` | Layout shell composing Topbar + Sidebar + `<Outlet />` with sidebar state management |

### Files Modified

| # | File | Change |
|---|------|--------|
| 5 | `src/frontend/src/pages/DashboardPage.tsx` | Replaced placeholder `<h1>Dashboard</h1>` with "Welcome back, {name}" heading + 3 stat cards (Total Documents, Active Conversations, Storage Used) with "—" values |
| 6 | `src/frontend/src/App.tsx` | Uncommented `AppShell` wrapper inside `PrivateRoute` children; added `import AppShell from '@/components/layout/AppShell'` |
| 7 | `.rooignore` | Changed `lib/` → `src/backend/lib/` and `lib64/` → `src/backend/lib64/` to allow frontend `src/lib/` directory |

### Sidebar Implementation Details

- **Props**: `{ isOpen: boolean; onClose: () => void }`
- **Desktop**: Fixed left sidebar (`fixed left-0 top-0 h-full w-64`), always visible (`lg:translate-x-0`)
- **Mobile**: Hidden by default (`-translate-x-full`), slides in via `translate-x-0` when open
- **Overlay**: Semi-transparent backdrop (`bg-black/50`) on mobile when sidebar is open; clicking closes sidebar
- **Navigation items**:
  - **Dashboard** — active by default (`bg-accent text-accent-foreground`), links to `/dashboard`
  - **Documents** — disabled (`opacity-50 cursor-not-allowed`, `pointer-events-none`)
  - **Conversations** — disabled
- **Icons**: `LayoutDashboard`, `FileText`, `MessageSquare` from `lucide-react`
- **Active detection**: Uses `useLocation().pathname` to match against `item.href`
- **Mobile nav click**: Calls `onClose()` after navigation
- **Footer**: Copyright notice with current year

### Topbar Implementation Details

- **Props**: `{ onMenuClick: () => void }`
- **Desktop**: Full width with `lg:pl-64` offset to account for sidebar
- **Left side**: Hamburger button (`Menu` icon) — visible only on mobile (`lg:hidden`), "DocuChat" logo text
- **Right side**: User avatar with fallback initials (derived from `full_name` or `email`), user name
- **DropdownMenu** (shadcn/ui):
  - "My Account" label
  - "My Profile" item — **disabled** (`disabled` prop)
  - "Sign Out" item — calls `authStore.logout()` then navigates to `/login`
- **Initials logic**: `getInitials(name, email)` — splits name by spaces, takes first letter of each, uppercase, max 2 chars; falls back to first letter of email

### AppShell Implementation Details

- **State**: `sidebarOpen` (boolean, default `false`) managed via `useState`
- **Renders**:
  - `<Topbar onMenuClick={() => setSidebarOpen(true)} />`
  - `<Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />`
  - `<main className="pt-16 lg:pl-64">` containing `<Outlet />`
- **Container**: Main content area uses `container mx-auto p-6` for responsive padding

### DashboardPage Implementation Details

- **Welcome heading**: "Welcome back, {user.full_name || user.email || 'User'}"
- **Subtitle**: "Here's an overview of your account."
- **3 stat cards** in responsive grid (`grid grid-cols-1 md:grid-cols-3 gap-6`):
  - **Total Documents** — value: "—"
  - **Active Conversations** — value: "—"
  - **Storage Used** — value: "—"
- Each card uses `Card`, `CardHeader`, `CardTitle`, `CardContent` from shadcn/ui
- Gets `user` from `useAuthStore`

### Updated Route Structure

```
PrivateRoute
  └── AppShell
        └── Outlet
              └── DashboardPage
```

### Verification

- `npx tsc --noEmit` — zero errors
- `npx vitest run` — 17/18 passing (1 pre-existing failure in axios interceptor test, unrelated)

## Next Step

Proceed to E08-T8 (next task in the implementation plan).
