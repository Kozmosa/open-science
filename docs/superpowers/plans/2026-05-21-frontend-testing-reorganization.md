# Frontend Testing Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize 25 existing test files into `__tests__/` directory, add 5 new page integration tests with msw, introduce Playwright E2E framework, and update vitest config.

**Architecture:** Four-layer test pyramid: unit (pure functions) → component (UI interaction) → page (integration with msw) → e2e (Playwright). New dir `frontend/__tests__/` with `unit/`, `components/`, `pages/`, `e2e/` subdirs.

**Tech Stack:** vitest, @testing-library/react, @testing-library/user-event, msw, @playwright/test

---

### Task 1: Foundation — Install Dependencies and Create Directory Structure

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/__tests__/` (all subdirs)
- Modify: `frontend/vitest.config.ts` (update paths)

- [ ] **Step 1: Install msw and Playwright**

```bash
cd frontend
npm install --save-dev msw @playwright/test
npx playwright install chromium
```

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p __tests__/unit/{api,i18n,settings,hooks,utils}
mkdir -p __tests__/components/{ui,project,terminal,token,common,environment}
mkdir -p __tests__/pages
mkdir -p __tests__/e2e
```

- [ ] **Step 3: Update `vitest.config.ts`**

Read `frontend/vitest.config.ts`. Add test directory include:

```typescript
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./__tests__/setup.ts'],
    include: ['__tests__/**/*.test.{ts,tsx}', 'src/**/*.test.{ts,tsx}'],
    css: true,
  },
})
```

Note: Keep `src/**/*.test.{ts,tsx}` in include for the migration period; remove after all files moved.

- [ ] **Step 4: Create `__tests__/setup.ts`** — shared test setup

```typescript
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
```

- [ ] **Step 5: Verify vitest still runs**

```bash
npx vitest run --config vitest.config.ts
```

Expected: all 119 tests pass.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json __tests__/ vitest.config.ts
git commit -m "test: add msw, Playwright, __tests__/ directory structure, setup file"
```

---

### Task 2: Migrate Unit Tests (9 files)

**Files:**
- Move 9 files from `src/` to `__tests__/unit/`

- [ ] **Step 1: Move files with git mv**

```bash
cd frontend
git mv src/api/client.test.ts __tests__/unit/api/client.test.ts
git mv src/api/endpoints.test.ts __tests__/unit/api/endpoints.test.ts
git mv src/api/environments.test.ts __tests__/unit/api/environments.test.ts
git mv src/queryClient.test.ts __tests__/unit/api/queryClient.test.ts
git mv src/settings/storage.test.ts __tests__/unit/settings/storage.test.ts
git mv src/hooks/useCardLayout.test.ts __tests__/unit/hooks/useCardLayout.test.ts
git mv src/i18n/LocaleSwitcher.test.tsx __tests__/unit/i18n/LocaleSwitcher.test.tsx
git mv src/terminal-contract.test.ts __tests__/unit/utils/terminal-contract.test.ts
git mv src/vite-proxy.test.ts __tests__/unit/utils/vite-proxy.test.ts
```

- [ ] **Step 2: Fix imports in each moved file**

For each moved file, update relative imports to use `../` or `@/` paths:

Example for `__tests__/unit/api/client.test.ts`:
```typescript
// Old: import { api } from './client'
// New: 
import { api } from '../../../src/api/client'
```

- [ ] **Step 3: Run unit tests**

```bash
npx vitest run __tests__/unit/
```

Expected: all 9 unit tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: migrate 9 unit tests to __tests__/unit/"
```

---

### Task 3: Migrate Component Tests (6 files)

**Files:**
- Move 6 files + App.test.tsx from `src/components/` to `__tests__/components/`

- [ ] **Step 1: Move files with git mv**

```bash
cd frontend
git mv src/components/ui/Button.test.tsx __tests__/components/ui/Button.test.tsx
git mv src/components/ui/SkillToggleGroup.test.tsx __tests__/components/ui/SkillToggleGroup.test.tsx
git mv src/components/project/ProjectCanvas.test.tsx __tests__/components/project/ProjectCanvas.test.tsx
git mv src/components/terminal/TerminalBenchCard.test.tsx __tests__/components/terminal/TerminalBenchCard.test.tsx
git mv src/components/terminal/TerminalSessionConsole.test.tsx __tests__/components/terminal/TerminalSessionConsole.test.tsx
git mv src/components/token/TokenFlowBar.test.tsx __tests__/components/token/TokenFlowBar.test.tsx
git mv src/components/environment/EnvironmentSelectorPanel.test.tsx __tests__/components/environment/EnvironmentSelectorPanel.test.tsx
git mv src/App.test.tsx __tests__/App.test.tsx
```

- [ ] **Step 2: Fix imports**

Update each file's imports to point to the correct source file paths.

- [ ] **Step 3: Run component tests**

```bash
npx vitest run __tests__/components/
```

Expected: all component tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: migrate 8 component tests to __tests__/components/"
```

---

### Task 4: Migrate Page Tests (8 files)

**Files:**
- Move 8 files from `src/pages/` to `__tests__/pages/`

- [ ] **Step 1: Move files with git mv**

```bash
cd frontend
git mv src/pages/EnvironmentsPage.test.tsx __tests__/pages/EnvironmentsPage.test.tsx
git mv src/pages/ResourcesPage.test.tsx __tests__/pages/ResourcesPage.test.tsx
git mv src/pages/SessionsPage.test.tsx __tests__/pages/SessionsPage.test.tsx
git mv src/pages/SettingsPage.test.tsx __tests__/pages/SettingsPage.test.tsx
git mv src/pages/TasksPage.test.tsx __tests__/pages/TasksPage.test.tsx
git mv src/pages/TerminalPage.test.tsx __tests__/pages/TerminalPage.test.tsx
git mv src/pages/TimelinePage.test.tsx __tests__/pages/TimelinePage.test.tsx
git mv src/pages/WorkspacesPage.test.tsx __tests__/pages/WorkspacesPage.test.tsx
```

- [ ] **Step 2: Fix imports**

- [ ] **Step 3: Run page tests**

```bash
npx vitest run __tests__/pages/
```

Expected: all 8 page tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: migrate 8 page tests to __tests__/pages/"
```

---

### Task 5: Add New Page Integration Tests (5 files)

**Files:**
- Create: `__tests__/pages/LoginPage.test.tsx`
- Create: `__tests__/pages/RegisterPage.test.tsx`
- Create: `__tests__/pages/ChangePasswordPage.test.tsx`
- Create: `__tests__/pages/ProjectsPage.test.tsx`
- Create: `__tests__/pages/FileBrowserPage.test.tsx`
- Create: `__tests__/mocks/handlers.ts` (msw API mock handlers)

- [ ] **Step 1: Create `__tests__/mocks/handlers.ts`** — shared msw handlers

```typescript
import { http, HttpResponse } from 'msw'

const BASE = 'http://localhost:8000'

export const handlers = [
  // Auth
  http.post(`${BASE}/auth/login`, async ({ request }) => {
    const body = await request.json() as { username: string; password: string }
    if (body.username === 'admin' && body.password === 'admin') {
      return HttpResponse.json({
        access_token: 'mock-access-token',
        refresh_token: 'mock-refresh-token',
        user: { id: 'u1', username: 'admin', display_name: 'Admin', role: 'admin', status: 'active' },
      })
    }
    return HttpResponse.json({ detail: 'Invalid username or password' }, { status: 401 })
  }),

  http.post(`${BASE}/auth/register`, () => {
    return HttpResponse.json({ message: 'Registration submitted' }, { status: 201 })
  }),

  http.get(`${BASE}/auth/me`, () => {
    return HttpResponse.json({
      id: 'u1', username: 'admin', display_name: 'Admin', role: 'admin', status: 'active',
    })
  }),

  // Projects
  http.get(`${BASE}/projects`, () => {
    return HttpResponse.json({
      items: [{ project_id: 'default', name: 'Default Project', description: '', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', owner_user_id: 'u1' }],
    })
  }),

  http.get(`${BASE}/projects/default/tasks`, () => {
    return HttpResponse.json({ items: [] })
  }),

  http.get(`${BASE}/projects/default/task-edges`, () => {
    return HttpResponse.json({ items: [] })
  }),

  // Files
  http.get(`${BASE}/files/list`, () => {
    return HttpResponse.json({ entries: [], path: '/' })
  }),
]
```

- [ ] **Step 2: Write `__tests__/pages/LoginPage.test.tsx`**

```typescript
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { createAppQueryClient } from '../../src/queryClient'
import LoginPage from '../../src/pages/LoginPage'
import { AuthProvider } from '../../src/contexts/AuthContext'

function renderLoginPage() {
  const queryClient = createAppQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginPage', () => {
  it('renders login form', () => {
    renderLoginPage()
    expect(screen.getByPlaceholderText(/username/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Write remaining 4 page tests**

Following the same pattern (render with providers + MemoryRouter):

- `RegisterPage.test.tsx` — renders form with display_name, username, password, confirm_password fields
- `ChangePasswordPage.test.tsx` — renders old_password, new_password fields
- `ProjectsPage.test.tsx` — renders with mock tasks, shows "New Task" button, canvas area
- `FileBrowserPage.test.tsx` — renders file tree and preview area

- [ ] **Step 4: Run all page tests**

```bash
npx vitest run __tests__/pages/
```

Expected: 13 page tests (8 migrated + 5 new) pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: add 5 new page integration tests with msw handlers"
```

---

### Task 6: Playwright E2E Tests

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `__tests__/e2e/auth.spec.ts`
- Create: `__tests__/e2e/projects.spec.ts`

- [ ] **Step 1: Create `playwright.config.ts`**

```typescript
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '__tests__/e2e',
  timeout: 30000,
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
  },
})
```

- [ ] **Step 2: Write `__tests__/e2e/auth.spec.ts`**

```typescript
import { test, expect } from '@playwright/test'

test.describe('Auth E2E', () => {
  test('login page loads', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('input[placeholder*="username" i]')).toBeVisible()
  })

  test('navigates to register page', async ({ page }) => {
    await page.goto('/login')
    await page.click('text=Register')
    await expect(page).toHaveURL(/register/)
  })
})
```

- [ ] **Step 3: Write `__tests__/e2e/projects.spec.ts`**

```typescript
import { test, expect } from '@playwright/test'

test.describe('Projects E2E', () => {
  test('projects page loads with canvas', async ({ page }) => {
    await page.goto('/projects')
    await expect(page.locator('.react-flow')).toBeVisible()
  })
})
```

- [ ] **Step 4: Run Playwright tests**

```bash
npx playwright test
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: add Playwright E2E framework with auth and projects specs"
```

---

### Task 7: Integration Verification

- [ ] **Step 1: Run full vitest suite**

```bash
npx vitest run
```

Expected: all 124+ tests pass.

- [ ] **Step 2: Run TypeScript check**

```bash
node_modules/.bin/tsc -b
```

- [ ] **Step 3: Run Playwright**

```bash
npx playwright test
```

- [ ] **Step 4: Clean up old `src/**/*.test.*` includes from vitest config**

Remove `'src/**/*.test.{ts,tsx}'` from `vitest.config.ts` include (all tests are now in `__tests__/`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: finalize test migration — update config, verify full suite"
```

---

## Verification Checklist

1. `npx vitest run` — 124+ tests pass
2. `npx playwright test` — E2E suite passes
3. `node_modules/.bin/tsc -b` — type check passes
4. No `*.test.*` files remain in `src/`
5. All import paths in moved files are correct
