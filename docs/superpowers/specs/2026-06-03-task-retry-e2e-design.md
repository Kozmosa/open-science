# Task Retry E2E Test Design

## Goal

Verify the task retry UI flow end-to-end using Playwright with `page.route()` API mocks — no real backend required.

## Scope

Backend retry logic is already covered by pytest integration tests (`test_retry_task_archives_old_and_creates_new`, `test_retry_task_invalid_status_returns_409`). This spec covers the **frontend interaction layer only**:

- Retry button visibility rules
- Click triggers correct API call
- Success path: toast appears, task list refreshes, new task selected
- Error path: error toast appears
- i18n: button label and toast messages in both EN and ZH

Out of scope: real backend, real task execution, WebSocket streaming.

---

## Approach: `page.route()` Mock

All `/api/tasks*` requests are intercepted via Playwright's `page.route()`. The test controls exactly what data the frontend sees. No server needs to be running on port 8000.

The Playwright config already has `reuseExistingServer: true` and the frontend Vite dev server is started automatically if not already up. The frontend fetches `/api/tasks` through its Vite proxy (`/api` → `localhost:8000`), so we intercept at the `/api/tasks` path level.

---

## Mock Data

### Failed task (shows Retry button)

```typescript
const FAILED_TASK = {
  task_id: 'task-failed-001',
  project_id: 'proj-001',
  title: 'Failed research task',
  task_profile: 'default',
  status: 'failed',
  workspace_summary: {
    workspace_id: 'ws-001',
    label: 'Default',
    description: null,
    default_workdir: null,
  },
  environment_summary: {
    environment_id: 'env-001',
    alias: 'local',
    display_name: 'Local',
    host: 'localhost',
    default_workdir: null,
  },
  created_at: '2026-06-03T10:00:00Z',
  updated_at: '2026-06-03T10:05:00Z',
}
```

### Cancelled task (also shows Retry button)

Same shape as above with `task_id: 'task-cancelled-001'`, `status: 'cancelled'`, `title: 'Cancelled research task'`.

### Running task (no Retry button)

Same shape with `task_id: 'task-running-001'`, `status: 'running'`, `title: 'Running research task'`.

### Retry response

```typescript
const RETRY_RESPONSE = {
  new_task: {
    ...FAILED_TASK,
    task_id: 'task-new-001',
    status: 'queued',
    title: 'Failed research task',
    created_at: '2026-06-03T10:10:00Z',
    updated_at: '2026-06-03T10:10:00Z',
  },
  archived_task_id: 'task-failed-001',
  edge_id: 'edge-001',
}
```

---

## Route Interception Strategy

Each test uses `page.route()` to mock these endpoints:

| Route pattern | Mock response |
|---|---|
| `**/api/tasks?*` (GET) | `{ items: [...], total: N }` |
| `**/api/tasks/task-failed-001/retry` (POST) | `RETRY_RESPONSE` |
| `**/api/tasks/task-failed-001/retry` (POST, error case) | HTTP 500 |
| `**/api/auth/refresh` (POST) | 401 (forces auth redirect, used to gate tests) |

The tasks page requires authentication. Tests navigate to `/tasks` after mocking the tasks API. If the page redirects to `/login`, the test skips gracefully (the page is protected and the mock environment doesn't have a real auth session).

To handle auth, tests mock the `/api/auth/me` (or equivalent user-info endpoint) to return a valid user, allowing the tasks page to render.

---

## Test Cases

### File: `__tests__/e2e/task-retry.spec.ts`

#### Test 1: Retry button visible on failed task, hidden on running task

Mock tasks list with one failed task and one running task. Hover over the failed task row — Retry button should appear. Hover over the running task row — no Retry button.

#### Test 2: Click Retry calls the correct API and shows success toast

Mock tasks list with failed task. Mock `POST /tasks/task-failed-001/retry` to return `RETRY_RESPONSE`. Mock the subsequent GET tasks to return the new task list (with new task, without old task). Click Retry. Assert:
- `POST .../retry` was called exactly once
- Toast with text "Task retried successfully" appears
- Task list refreshes (old task gone, new task present)

#### Test 3: Retry API failure shows error toast

Mock `POST /tasks/task-failed-001/retry` to return HTTP 500. Click Retry. Assert toast with text "Failed to retry task" appears.

#### Test 4: Retry button shows correct label in Chinese

Switch locale to ZH via `[data-testid="locale-switcher"]` button with `aria-pressed`. Hover failed task row. Assert Retry button label is "重试". Assert success toast shows "任务已重试".

#### Test 5: Retry button absent on cancelled task in archived view

Mock `showArchived=true` query. Even if task status is `cancelled`, no Retry button shown (matches `!showArchived` guard in `canRetry`).

---

## Test Helpers

A shared `setupTasksMock(page, tasks, options)` helper sets up all the standard route intercepts for a given task list, so each test doesn't repeat the boilerplate. Defined at the top of the spec file (not a separate file, YAGNI).

---

## Locator Strategy

No `data-testid` attributes exist on task row action buttons. Locators use semantic attributes:

- Task row: `[data-task-id="task-failed-001"]` — **requires adding `data-task-id` to the task row `<li>` element in `TaskList.tsx`**
- Retry button within row: `.getByRole('button', { name: /retry/i })` scoped to the row locator
- Toast: `page.locator('text=Task retried successfully')` or `page.getByText('Task retried successfully')`
- Locale switcher ZH button: `page.locator('[data-testid="locale-switcher"] button[aria-pressed]').filter({ hasText: 'ZH' })`

The one required frontend change is adding `data-task-id={task.task_id}` to the task row element in `TaskList.tsx`. This is a minimal, non-breaking addition.

---

## Files Changed

| File | Action |
|---|---|
| `frontend/__tests__/e2e/task-retry.spec.ts` | Create — 5 test cases |
| `frontend/src/pages/tasks/TaskList.tsx` | Modify — add `data-task-id` to row element |

No other files touched.

---

## Running the Tests

```bash
cd frontend
npx playwright test __tests__/e2e/task-retry.spec.ts
# or all e2e:
npx playwright test
```

The Vite dev server starts automatically via `webServer` config if not already running. Backend is not needed (all API calls are mocked).
