# Task E08-T7: App Shell Layout (Sidebar + Topbar)

## Objective

Implement the persistent authenticated layout shell — `AppShell` wrapping `Topbar`, `Sidebar`, and `<Outlet />` — plus update `DashboardPage` with welcome message and stat cards.

## Prerequisites

- All existing UI components are already in place: `Avatar`, `Button`, `Card`, `DropdownMenu`, `Separator`, `Input`, `Label`, `Form`, `Toast`, `Alert`
- `authStore` provides `user: User | null`, `logout()`, `isAuthenticated`
- `PrivateRoute` already wraps authenticated routes
- `react-router-dom` v7 with `<Outlet />` pattern
- `lucide-react` icons available
- `@/` path alias configured in Vite

## Files to Create

### 1. `src/frontend/src/components/layout/Sidebar.tsx`

**Purpose:** Fixed left navigation sidebar with responsive toggle.

**Key Details:**
- Fixed position on desktop (`fixed left-0 top-0 h-full w-64`)
- Contains app logo/brand at top
- Navigation items:
  - **Dashboard** — active by default, links to `/dashboard`
  - **Documents** — disabled state (greyed out, `pointer-events-none`)
  - **Conversations** — disabled state
- Mobile: hidden by default (`-translate-x-full`), toggled via `isOpen` prop + overlay backdrop
- Uses `lucide-react` icons: `LayoutDashboard`, `FileText`, `MessageSquare`
- Props interface: `{ isOpen: boolean; onClose: () => void }`
- On mobile, clicking a nav item should call `onClose`
- Active item has `bg-accent text-accent-foreground` styling
- Disabled items have `opacity-50 cursor-not-allowed`

### 2. `src/frontend/src/components/layout/Topbar.tsx`

**Purpose:** Top bar with logo, hamburger menu (mobile), and user dropdown.

**Key Details:**
- Left side:
  - Hamburger button (`Menu` icon from `lucide-react`) — visible only on mobile (`lg:hidden`)
  - "DocuChat" logo text
- Right side:
  - User avatar (from `@/components/ui/avatar`) with fallback initials
  - User full name
  - `DropdownMenu` with:
    - "My Profile" item — **disabled** (`disabled` prop)
    - "Sign Out" item — calls `logout()` from `authStore`, then navigates to `/login`
- Props interface: `{ onMenuClick: () => void }`
- Fixed top bar with `h-16` height, `border-b`, `bg-background`

### 3. `src/frontend/src/components/layout/AppShell.tsx`

**Purpose:** Wraps Topbar + Sidebar + `<Outlet />` for all authenticated pages.

**Key Details:**
- Manages `sidebarOpen` state (boolean, default `false`)
- Renders:
  - `<Topbar onMenuClick={() => setSidebarOpen(true)} />`
  - `<Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />`
  - Main content area: `<main className="pt-16 lg:pl-64">` containing `<Outlet />`
- On desktop: sidebar is always visible (`lg:translate-x-0`)
- On mobile: sidebar slides in/out

### 4. `src/frontend/src/pages/DashboardPage.tsx` (Update)

**Purpose:** Replace placeholder with welcome message + stat cards.

**Key Details:**
- "Welcome back, {user.full_name || user.email}" heading
- 3 stat cards in a responsive grid (`grid grid-cols-1 md:grid-cols-3 gap-6`):
  - **Total Documents** — value: "—"
  - **Active Conversations** — value: "—"
  - **Storage Used** — value: "—"
- Each card uses `Card`, `CardHeader`, `CardTitle`, `CardContent` from `@/components/ui/card`
- Gets `user` from `useAuthStore`

### 5. `src/frontend/src/App.tsx` (Update)

**Purpose:** Wire `AppShell` into the router.

**Key Details:**
- Uncomment the `AppShell` wrapper inside the `PrivateRoute` children
- The route structure becomes:
  ```
  PrivateRoute
    └── AppShell
          └── Outlet
                └── DashboardPage
  ```

## Implementation Steps (Execution Order)

1. **Create `Sidebar.tsx`** — Navigation sidebar with responsive toggle, disabled nav items, active state
2. **Create `Topbar.tsx`** — Top bar with hamburger, logo, avatar, user dropdown with Sign Out
3. **Create `AppShell.tsx`** — Layout shell composing Topbar + Sidebar + Outlet
4. **Update `DashboardPage.tsx`** — Welcome message + 3 stat cards with "—" values
5. **Update `App.tsx`** — Uncomment AppShell wrapper in router

## Component Tree

```
App
└── RouterProvider
    └── BrowserRouter
        ├── PublicRoute
        │   ├── LoginPage
        │   └── RegisterPage
        └── PrivateRoute
            └── AppShell
                ├── Topbar (fixed top)
                │   ├── Hamburger button (mobile only)
                │   ├── "DocuChat" logo
                │   └── Avatar + Name + DropdownMenu
                │       ├── My Profile (disabled)
                │       └── Sign Out
                ├── Sidebar (fixed left)
                │   ├── Brand/Logo
                │   ├── Dashboard (active)
                │   ├── Documents (disabled)
                │   └── Conversations (disabled)
                └── main content area
                    └── Outlet
                        └── DashboardPage
                            ├── "Welcome back, {name}"
                            └── Stat Cards Grid
                                ├── Total Documents: —
                                ├── Active Conversations: —
                                └── Storage Used: —
```

## Mobile Responsive Behavior

| Element | Desktop (lg+) | Mobile |
|---------|---------------|--------|
| Sidebar | Always visible, `translate-x-0` | Hidden by default, slides in via `translate-x-0` when open |
| Hamburger | Hidden (`lg:hidden`) | Visible |
| Overlay | None | Semi-transparent backdrop when sidebar open |
| Topbar | Full width with `lg:pl-64` offset | Full width |
| Main content | `lg:pl-64` offset | No offset |

## Data Flow

- `authStore.user` → `Topbar` (avatar initials, name) + `DashboardPage` (welcome message)
- `authStore.logout()` → `Topbar` Sign Out action
- `Sidebar` state (`isOpen`/`onClose`) → managed in `AppShell` via `useState`
- `Topbar.onMenuClick` → opens sidebar on mobile
- `Sidebar.onClose` → closes sidebar (via overlay click or nav item click)

## Manual Testing Checklist

After implementation, verify in browser:

1. **Desktop layout:**
   - [ ] Sidebar visible on left (w-64)
   - [ ] Topbar visible at top with "DocuChat" logo
   - [ ] Dashboard nav item is highlighted
   - [ ] Documents and Conversations are greyed out/disabled
   - [ ] Avatar + name shown in topbar
   - [ ] Dropdown menu opens with "My Profile" (disabled) and "Sign Out"
   - [ ] Main content area shows DashboardPage with welcome + stat cards

2. **Mobile layout (resize to <1024px):**
   - [ ] Sidebar hidden by default
   - [ ] Hamburger button visible in topbar
   - [ ] Clicking hamburger opens sidebar with overlay
   - [ ] Clicking overlay closes sidebar
   - [ ] Clicking a nav item closes sidebar

3. **Sign Out flow:**
   - [ ] Clicking "Sign Out" in dropdown logs out and redirects to /login

4. **DashboardPage:**
   - [ ] Shows "Welcome back, {user's name}"
   - [ ] Shows 3 stat cards with "—" values
