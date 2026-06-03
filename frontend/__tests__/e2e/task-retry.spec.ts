import { test, expect, type Page } from '@playwright/test'

// ── Mock data ────────────────────────────────────────────────────────────────

const WORKSPACE = {
  workspace_id: 'ws-001',
  label: 'Default',
  description: null,
  default_workdir: null,
}

const ENVIRONMENT = {
  id: 'env-001',
  environment_id: 'env-001',
  alias: 'local',
  display_name: 'Local',
  host: 'localhost',
  default_workdir: null,
}

const TASK_RESULT = {
  exit_code: 1,
  failure_category: 'runtime',
  error_summary: 'Task failed',
  completed_at: '2026-06-03T10:05:00Z',
}

const FAILED_TASK_SUMMARY = {
  task_id: 'task-failed-001',
  project_id: 'proj-001',
  workspace_id: 'ws-001',
  environment_id: 'env-001',
  title: 'Failed research task',
  task_profile: 'default',
  researcher_type: 'vanilla',
  harness_engine: 'claude-code',
  prompt: 'Failed prompt',
  owner_user_id: 'user-001',
  exit_code: 1,
  status: 'failed',
  workspace_summary: WORKSPACE,
  environment_summary: ENVIRONMENT,
  created_at: '2026-06-03T10:00:00Z',
  updated_at: '2026-06-03T10:05:00Z',
  started_at: '2026-06-03T10:00:30Z',
  completed_at: '2026-06-03T10:05:00Z',
  error_summary: 'Task failed',
  latest_output_seq: 0,
}

// TaskRecord extends TaskSummary with extra fields — needed for GET /tasks/{id}
const FAILED_TASK_RECORD = {
  ...FAILED_TASK_SUMMARY,
  binding: null,
  prompt_detail: null,
  runtime: null,
  result: TASK_RESULT,
}

const CANCELLED_TASK_SUMMARY = {
  ...FAILED_TASK_SUMMARY,
  task_id: 'task-cancelled-001',
  status: 'cancelled',
  title: 'Cancelled research task',
}

const RUNNING_TASK_SUMMARY = {
  ...FAILED_TASK_SUMMARY,
  task_id: 'task-running-001',
  status: 'running',
  title: 'Running research task',
  exit_code: null,
  completed_at: null,
  error_summary: null,
}

const NEW_TASK_SUMMARY = {
  ...FAILED_TASK_SUMMARY,
  task_id: 'task-new-001',
  status: 'queued',
  created_at: '2026-06-03T10:10:00Z',
  updated_at: '2026-06-03T10:10:00Z',
  started_at: null,
  completed_at: null,
  exit_code: null,
  error_summary: null,
}

const RETRY_RESPONSE = {
  new_task: NEW_TASK_SUMMARY,
  archived_task_id: 'task-failed-001',
  edge_id: 'edge-001',
}

const MOCK_USER = {
  id: 'user-001',
  username: 'testuser',
  display_name: 'Test User',
  role: 'user',
  status: 'active',
}

const EMPTY_LIST = { items: [], total: 0, has_more: false }

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Sets up all route mocks needed for the tasks page to render:
 * - Auth (localStorage refresh token + /auth/refresh + /auth/me)
 * - Auxiliary endpoints (projects, workspaces, skills, environments)
 * - Tasks list GET /tasks?* → returns supplied tasks list
 * - Single task GET /tasks/{id} → returns the matching task record
 * - Optional retry endpoint
 */
async function setupTasksMock(
  page: Page,
  tasks: typeof FAILED_TASK_SUMMARY[],
  options: { retryStatus?: number; retryResponse?: unknown } = {},
) {
  // addInitScript injects before page scripts on every navigation
  await page.addInitScript(() => {
    localStorage.setItem('ainrf.refresh_token', 'fake-refresh-token')
  })

  await page.route('**/api/auth/refresh', (route) => {
    void route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ access_token: 'fake-access-token' }),
    })
  })

  await page.route('**/api/auth/me', (route) => {
    void route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_USER),
    })
  })

  // Auxiliary endpoints TasksPage fetches on mount
  await page.route('**/api/projects**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_LIST) })
  })
  await page.route('**/api/workspaces**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_LIST) })
  })
  await page.route('**/api/skills**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_LIST) })
  })
  await page.route('**/api/environments**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_LIST) })
  })
  await page.route('**/api/settings/**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  })

  // Single task detail: GET /tasks/{id} — page auto-selects first task on load
  // Must be registered BEFORE the tasks list wildcard to take precedence
  await page.route(/\/api\/tasks\/[^/?]+$/, async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    const taskId = route.request().url().split('/api/tasks/')[1]
    const match = tasks.find((t) => t.task_id === taskId)
    if (match) {
      const record = { ...match, binding: null, prompt_detail: null, runtime: null, result: TASK_RESULT }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(record) })
    } else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not found' }) })
    }
  })

  // Task output: GET /tasks/{id}/output — needed to avoid 401 errors in detail panel
  await page.route(/\/api\/tasks\/[^/?]+\/output/, async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], has_more: false, next_seq: 0 }) })
  })

  // Tasks list: GET /tasks?* — must come after more-specific patterns
  await page.route(/\/api\/tasks\?/, async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: tasks, total: tasks.length, has_more: false }),
    })
  })

  if (options.retryStatus !== undefined) {
    await page.route(/\/api\/tasks\/[^/?]+\/retry/, (route) => {
      void route.fulfill({
        status: options.retryStatus!,
        contentType: 'application/json',
        body: options.retryStatus === 200
          ? JSON.stringify(options.retryResponse)
          : JSON.stringify({ detail: 'Internal server error' }),
      })
    })
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Task Retry', () => {
  test('retry button visible on failed task, hidden on running task', async ({ page }) => {
    await setupTasksMock(page, [FAILED_TASK_SUMMARY, RUNNING_TASK_SUMMARY])
    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    const failedRow = page.locator('[data-task-id="task-failed-001"]')
    const runningRow = page.locator('[data-task-id="task-running-001"]')

    await expect(failedRow).toBeVisible({ timeout: 10000 })

    // Hover failed row — Retry button becomes visible
    await failedRow.hover()
    const retryBtn = failedRow.getByRole('button', { name: /retry/i })
    await expect(retryBtn).toBeVisible()

    // Hover running row — no Retry button
    await runningRow.hover()
    const runningRetryBtn = runningRow.getByRole('button', { name: /retry/i })
    await expect(runningRetryBtn).not.toBeVisible()
  })

  test('clicking Retry calls API and shows success toast', async ({ page }) => {
    // Track retry completion — list returns new task only after retry fires
    let retryDone = false

    await page.addInitScript(() => {
      localStorage.setItem('ainrf.refresh_token', 'fake-refresh-token')
    })
    await page.route('**/api/auth/refresh', (route) => {
      void route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ access_token: 'fake-access-token' }) })
    })
    await page.route('**/api/auth/me', (route) => {
      void route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USER) })
    })
    for (const path of ['**/api/projects**', '**/api/workspaces**', '**/api/skills**', '**/api/environments**', '**/api/settings/**']) {
      await page.route(path, async (route) => {
        if (route.request().method() !== 'GET') { await route.continue(); return }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_LIST) })
      })
    }

    // Single task detail — both original and new task must resolve correctly
    await page.route(/\/api\/tasks\/[^/?]+$/, async (route) => {
      if (route.request().method() !== 'GET') { await route.continue(); return }
      const taskId = route.request().url().split('/api/tasks/')[1]
      const taskMap: Record<string, object> = {
        'task-failed-001': FAILED_TASK_RECORD,
        'task-new-001': { ...NEW_TASK_SUMMARY, binding: null, prompt_detail: null, runtime: null, result: TASK_RESULT },
      }
      const record = taskMap[taskId]
      await route.fulfill({ status: record ? 200 : 404, contentType: 'application/json', body: JSON.stringify(record ?? { detail: 'Not found' }) })
    })
    await page.route(/\/api\/tasks\/[^/?]+\/output/, async (route) => {
      if (route.request().method() !== 'GET') { await route.continue(); return }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], has_more: false, next_seq: 0 }) })
    })

    // Tasks list: return failed task until retry fires, then switch to new task
    await page.route(/\/api\/tasks\?/, async (route) => {
      if (route.request().method() !== 'GET') { await route.continue(); return }
      const tasks = retryDone ? [NEW_TASK_SUMMARY] : [FAILED_TASK_SUMMARY]
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: tasks, total: tasks.length, has_more: false }),
      })
    })

    let retryCalled = false
    await page.route(/\/api\/tasks\/[^/?]+\/retry/, async (route) => {
      retryCalled = true
      retryDone = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RETRY_RESPONSE) })
    })

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    const failedRow = page.locator('[data-task-id="task-failed-001"]')
    await expect(failedRow).toBeVisible({ timeout: 10000 })
    await failedRow.hover()

    const retryBtn = failedRow.getByRole('button', { name: /retry/i })
    await retryBtn.click()

    await expect.poll(() => retryCalled).toBe(true)
    await expect(page.getByText('Task retried successfully')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('[data-task-id="task-new-001"]')).toBeVisible({ timeout: 5000 })
  })

  test('Retry API failure shows error toast', async ({ page }) => {
    await setupTasksMock(page, [FAILED_TASK_SUMMARY])

    await page.route(/\/api\/tasks\/[^/?]+\/retry/, (route) => {
      void route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      })
    })

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    const failedRow = page.locator('[data-task-id="task-failed-001"]')
    await expect(failedRow).toBeVisible({ timeout: 10000 })
    await failedRow.hover()

    const retryBtn = failedRow.getByRole('button', { name: /retry/i })
    await retryBtn.click()

    await expect(page.getByText('Failed to retry task')).toBeVisible({ timeout: 5000 })
  })

  test('retry button label is Chinese when locale is ZH', async ({ page }) => {
    let retryDone = false
    await setupTasksMock(page, [FAILED_TASK_SUMMARY])

    await page.route(/\/api\/tasks\/[^/?]+\/retry/, async (route) => {
      retryDone = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RETRY_RESPONSE) })
    })

    // Override tasks list to return new task after retry
    await page.route(/\/api\/tasks\?/, async (route) => {
      if (route.request().method() !== 'GET') { await route.continue(); return }
      const tasks = retryDone ? [NEW_TASK_SUMMARY] : [FAILED_TASK_SUMMARY]
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: tasks, total: tasks.length, has_more: false }) })
    })

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    // Switch to Chinese locale
    const zhButton = page.locator('[data-testid="locale-switcher"]').getByText('中文')
    await expect(zhButton).toBeVisible({ timeout: 10000 })
    await zhButton.click()

    const failedRow = page.locator('[data-task-id="task-failed-001"]')
    await expect(failedRow).toBeVisible({ timeout: 5000 })
    await failedRow.hover()

    // Retry button should read "重试" in Chinese
    const retryBtn = failedRow.getByRole('button', { name: '重试' })
    await expect(retryBtn).toBeVisible()

    await retryBtn.click()
    await expect(page.getByText('任务已重试')).toBeVisible({ timeout: 5000 })
  })

  test('retry button absent in archived view even for cancelled task', async ({ page }) => {
    let showArchived = false
    await setupTasksMock(page, [])

    // Override tasks list: return cancelled task only when archived view is active
    await page.route(/\/api\/tasks\?/, async (route) => {
      if (route.request().method() !== 'GET') { await route.continue(); return }
      const url = route.request().url()
      if (url.includes('include_archived=true') || url.includes('archived=true')) {
        showArchived = true
      }
      const tasks = showArchived ? [CANCELLED_TASK_SUMMARY] : []
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: tasks, total: tasks.length, has_more: false }) })
    })

    await page.route(/\/api\/tasks\/[^/?]+$/, async (route) => {
      if (route.request().method() !== 'GET') { await route.continue(); return }
      const taskId = route.request().url().split('/api/tasks/')[1]
      if (taskId === 'task-cancelled-001') {
        const record = { ...CANCELLED_TASK_SUMMARY, binding: null, prompt_detail: null, runtime: null, result: TASK_RESULT }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(record) })
      } else {
        await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not found' }) })
      }
    })

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    // Toggle "Show archived" checkbox
    const archiveCheckbox = page.getByRole('checkbox', { name: /show archived/i })
    await expect(archiveCheckbox).toBeVisible({ timeout: 10000 })
    await archiveCheckbox.check()

    // Cancelled task should appear
    const cancelledRow = page.locator('[data-task-id="task-cancelled-001"]')
    await expect(cancelledRow).toBeVisible({ timeout: 5000 })

    // Hover — no Retry button (showArchived suppresses it)
    await cancelledRow.hover()
    const retryBtn = cancelledRow.getByRole('button', { name: /retry/i })
    await expect(retryBtn).not.toBeVisible()
  })
})
