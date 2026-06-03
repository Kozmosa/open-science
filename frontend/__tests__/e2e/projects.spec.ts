import { test, expect } from '@playwright/test'

test.describe('Projects E2E', () => {
  test('projects page loads', async ({ page }) => {
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
        body: JSON.stringify({
          id: 'user-001',
          username: 'testuser',
          display_name: 'Test User',
          role: 'user',
          status: 'active',
        }),
      })
    })
    await page.route('**/api/projects/proj-001/tasks**', (route) => {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      })
    })
    await page.route('**/api/projects/proj-001/task-edges**', (route) => {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [] }),
      })
    })
    await page.route('**/api/projects/proj-001', (route) => {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          project_id: 'proj-001',
          name: 'Default',
          description: null,
          default_workspace_id: 'ws-001',
          default_environment_id: 'env-001',
          created_at: '2026-06-03T10:00:00Z',
          updated_at: '2026-06-03T10:00:00Z',
        }),
      })
    })
    await page.route('**/api/projects**', (route) => {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{
            project_id: 'proj-001',
            name: 'Default',
            description: null,
            default_workspace_id: 'ws-001',
            default_environment_id: 'env-001',
            created_at: '2026-06-03T10:00:00Z',
            updated_at: '2026-06-03T10:00:00Z',
          }],
        }),
      })
    })
    await page.route('**/api/workspaces**', (route) => {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{
            workspace_id: 'ws-001',
            project_id: 'proj-001',
            label: 'Default',
            description: null,
            default_workdir: null,
            workspace_prompt: '',
            created_at: '2026-06-03T10:00:00Z',
            updated_at: '2026-06-03T10:00:00Z',
          }],
        }),
      })
    })
    await page.route('**/api/environments**', (route) => {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{
            id: 'env-001',
            alias: 'local',
            display_name: 'Local',
            host: 'localhost',
            default_workdir: null,
          }],
        }),
      })
    })
    await page.goto('/projects')
    await expect(page.getByRole('button', { name: 'New Task' })).toBeVisible({ timeout: 10000 })
  })
})
