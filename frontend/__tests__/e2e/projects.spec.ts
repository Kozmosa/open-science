import { test, expect } from '@playwright/test'

test.describe('Projects E2E', () => {
  test('projects page loads', async ({ page }) => {
    await page.goto('/projects')
    await expect(page.locator('text=New Task').or(page.locator('.react-flow'))).toBeVisible({ timeout: 10000 })
  })
})
