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

const MOCK_USER = {
  id: 'user-001',
  username: 'testuser',
  display_name: 'Test User',
  role: 'user',
  status: 'active',
}

const EMPTY_LIST = { items: [], total: 0, has_more: false }

const VANILLA_TASK_SUMMARY = {
  task_id: 'task-vanilla-001',
  project_id: 'proj-001',
  workspace_id: 'ws-001',
  environment_id: 'env-001',
  title: 'Vanilla research task',
  task_profile: 'claude-code',
  researcher_type: 'vanilla',
  harness_engine: 'claude-code',
  prompt: 'Research the latest advances in LLM reasoning',
  owner_user_id: 'user-001',
  exit_code: null,
  status: 'queued' as const,
  workspace_summary: WORKSPACE,
  environment_summary: ENVIRONMENT,
  created_at: '2026-06-03T10:00:00Z',
  updated_at: '2026-06-03T10:00:00Z',
  started_at: null,
  completed_at: null,
  error_summary: null,
  latest_output_seq: 0,
}

const ARIS_TASK_SUMMARY = {
  task_id: 'task-aris-001',
  project_id: 'proj-001',
  workspace_id: 'ws-001',
  environment_id: 'env-001',
  title: 'ARIS research task',
  task_profile: 'agent-sdk',
  researcher_type: 'aris-researcher',
  harness_engine: 'agent-sdk',
  prompt: 'Analyze the ARIS framework for agentic research',
  owner_user_id: 'user-001',
  exit_code: null,
  status: 'queued' as const,
  workspace_summary: WORKSPACE,
  environment_summary: ENVIRONMENT,
  created_at: '2026-06-03T10:01:00Z',
  updated_at: '2026-06-03T10:01:00Z',
  started_at: null,
  completed_at: null,
  error_summary: null,
  latest_output_seq: 0,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Sets up all route mocks needed for the tasks page to render:
 * - Auth (localStorage refresh token + /auth/refresh + /auth/me)
 * - Auxiliary endpoints (projects, workspaces, skills, environments)
 * - Tasks list GET /tasks?* → returns supplied tasks list
 * - Single task GET /tasks/{id} → returns the matching task record
 * - POST /tasks → returns a newly created task summary
 */
async function setupTasksMock(
  page: Page,
  tasks: typeof VANILLA_TASK_SUMMARY[],
  options: { createResponse?: typeof VANILLA_TASK_SUMMARY } = {},
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
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [{ project_id: 'proj-001', name: 'Default', description: null, default_workspace_id: 'ws-001', default_environment_id: 'env-001', created_at: '2026-06-03T10:00:00Z', updated_at: '2026-06-03T10:00:00Z' }], total: 1 }) })
  })
  await page.route('**/api/workspaces**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [WORKSPACE], total: 1 }) })
  })
  await page.route('**/api/skills**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_LIST) })
  })
  await page.route('**/api/environments**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [ENVIRONMENT], total: 1 }) })
  })
  await page.route('**/api/settings/**', async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  })

  // Single task detail: GET /tasks/{id}
  await page.route(/\/api\/tasks\/[^/?]+$/, async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    const taskId = route.request().url().split('/api/tasks/')[1]
    const match = tasks.find((t) => t.task_id === taskId)
    if (match) {
      const record = {
        ...match,
        binding: null,
        prompt_detail: null,
        runtime: null,
        result: { exit_code: null, failure_category: null, error_summary: null, completed_at: null },
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(record) })
    } else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not found' }) })
    }
  })

  // Task output: GET /tasks/{id}/output
  await page.route(/\/api\/tasks\/[^/?]+\/output/, async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], has_more: false, next_seq: 0 }) })
  })

  // Tasks list: GET /tasks?*
  await page.route(/\/api\/tasks\?/, async (route) => {
    if (route.request().method() !== 'GET') { await route.continue(); return }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: tasks, total: tasks.length, has_more: false }),
    })
  })

  // Create task: POST /tasks
  if (options.createResponse) {
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(options.createResponse),
      })
    })
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('AgenticResearcher', () => {
  test('creating a vanilla researcher task', async ({ page }) => {
    let createPayload: object | null = null

    await setupTasksMock(page, [VANILLA_TASK_SUMMARY], {
      createResponse: VANILLA_TASK_SUMMARY,
    })

    // Override POST /tasks to capture payload
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return }
      createPayload = await route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(VANILLA_TASK_SUMMARY),
      })
    })

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    // Click "New Task" button to open create dialog
    const newTaskBtn = page.getByRole('button', { name: /new task/i })
    await expect(newTaskBtn).toBeVisible({ timeout: 10000 })
    await newTaskBtn.click()

    // Fill in the create form
    const promptTextarea = page.locator('textarea[placeholder*="research prompt"]')
    await expect(promptTextarea).toBeVisible()
    await promptTextarea.fill('Research the latest advances in LLM reasoning')

    // Vanilla researcher type should be selected by default
    const vanillaRadio = page.locator('input[type="radio"][value="vanilla"]')
    await expect(vanillaRadio).toBeChecked()

    // Fill in skills for vanilla researcher
    const skillsInput = page.locator('input[placeholder*="skill1"]')
    await expect(skillsInput).toBeVisible()
    await skillsInput.fill('web-search, citation')

    // Fill in title — use placeholder to target the title field specifically
    const titleField = page.locator('input[type="text"][placeholder*="Optional"]')
    await titleField.fill('Vanilla research task')

    // Submit the form
    const createBtn = page.getByRole('button', { name: 'Create task' })
    await createBtn.click()

    // Verify the create API was called with correct payload
    await expect.poll(() => createPayload).toBeTruthy()
    expect(createPayload).toMatchObject({
      researcher_type: 'vanilla',
      harness_engine: 'claude-code',
      prompt: 'Research the latest advances in LLM reasoning',
      skills: ['web-search', 'citation'],
      project_id: 'proj-001',
      workspace_id: 'ws-001',
      environment_id: 'env-001',
    })

    // Verify the new task appears in the list
    await expect(page.locator('[data-task-id="task-vanilla-001"]')).toBeVisible({ timeout: 5000 })
  })

  test('creating an aris researcher task', async ({ page }) => {
    let createPayload: object | null = null

    await setupTasksMock(page, [ARIS_TASK_SUMMARY], {
      createResponse: ARIS_TASK_SUMMARY,
    })

    // Override POST /tasks to capture payload
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST') { await route.continue(); return }
      createPayload = await route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(ARIS_TASK_SUMMARY),
      })
    })

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    // Click "New Task" button to open create dialog
    const newTaskBtn = page.getByRole('button', { name: /new task/i })
    await expect(newTaskBtn).toBeVisible({ timeout: 10000 })
    await newTaskBtn.click()

    // Fill in the create form
    const promptTextarea = page.locator('textarea[placeholder*="research prompt"]')
    await expect(promptTextarea).toBeVisible()
    await promptTextarea.fill('Analyze the ARIS framework for agentic research')

    // Select ARIS researcher type
    const arisRadio = page.locator('input[type="radio"][value="aris-researcher"]')
    await expect(arisRadio).toBeVisible()
    await arisRadio.click()

    // Verify vanilla radio is no longer selected
    const vanillaRadio = page.locator('input[type="radio"][value="vanilla"]')
    await expect(vanillaRadio).not.toBeChecked()
    await expect(arisRadio).toBeChecked()

    // Skills field should be hidden for aris researcher
    const skillsInput = page.locator('input[placeholder*="skill1"]')
    await expect(skillsInput).not.toBeVisible()

    // Change execution engine — scoped to the dialog to avoid matching the sidebar sort select
    const engineSelect = page.getByRole('dialog').locator('select')
    await engineSelect.selectOption('agent-sdk')

    // Fill in title — use placeholder to target the title field specifically
    const titleField = page.locator('input[type="text"][placeholder*="Optional"]')
    await titleField.fill('ARIS research task')

    // Submit the form
    const createBtn = page.getByRole('button', { name: 'Create task' })
    await createBtn.click()

    // Verify the create API was called with correct payload
    await expect.poll(() => createPayload).toBeTruthy()
    expect(createPayload).toMatchObject({
      researcher_type: 'aris-researcher',
      harness_engine: 'agent-sdk',
      prompt: 'Analyze the ARIS framework for agentic research',
      skills: [],
      project_id: 'proj-001',
      workspace_id: 'ws-001',
      environment_id: 'env-001',
    })

    // Verify the new task appears in the list
    await expect(page.locator('[data-task-id="task-aris-001"]')).toBeVisible({ timeout: 5000 })
  })

  test('task list displays researcher tasks correctly', async ({ page }) => {
    const tasks = [VANILLA_TASK_SUMMARY, ARIS_TASK_SUMMARY]
    await setupTasksMock(page, tasks)

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    // Both tasks should be visible in the list
    const vanillaRow = page.locator('[data-task-id="task-vanilla-001"]')
    const arisRow = page.locator('[data-task-id="task-aris-001"]')

    await expect(vanillaRow).toBeVisible({ timeout: 10000 })
    await expect(arisRow).toBeVisible({ timeout: 10000 })

    // Verify task titles are displayed
    await expect(vanillaRow.getByText('Vanilla research task')).toBeVisible()
    await expect(arisRow.getByText('ARIS research task')).toBeVisible()

    // Verify task statuses are displayed
    await expect(vanillaRow.getByText('queued', { exact: false })).toBeVisible()
    await expect(arisRow.getByText('queued', { exact: false })).toBeVisible()
  })

  test('cancel button closes create dialog without creating task', async ({ page }) => {
    let createCalled = false

    await setupTasksMock(page, [])

    // Track if POST /tasks is called
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() === 'POST') {
        createCalled = true
      }
      await route.continue()
    })

    await page.goto('/tasks')
    await page.waitForLoadState('networkidle')

    // Open create dialog
    const newTaskBtn = page.getByRole('button', { name: /new task/i })
    await expect(newTaskBtn).toBeVisible({ timeout: 10000 })
    await newTaskBtn.click()

    // Verify dialog is open
    const promptTextarea = page.locator('textarea[placeholder*="research prompt"]')
    await expect(promptTextarea).toBeVisible()

    // Click Cancel
    const cancelBtn = page.getByRole('button', { name: 'Cancel' })
    await cancelBtn.click()

    // Verify dialog is closed
    await expect(promptTextarea).not.toBeVisible()

    // Verify no create API call was made
    expect(createCalled).toBe(false)
  })
})
