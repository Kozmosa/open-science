import { test, expect } from '@playwright/test'

test.describe('Auth E2E', () => {
  test('login page loads with form fields', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('input[placeholder*="username" i]')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('input[placeholder*="password" i]')).toBeVisible()
  })

  test('navigates to register page from login', async ({ page }) => {
    await page.goto('/login')
    const registerLink = page.locator('a[href="/register"]')
    if (await registerLink.isVisible()) {
      await registerLink.click()
      await expect(page).toHaveURL(/register/)
    }
  })

  test('register page loads with form fields', async ({ page }) => {
    await page.goto('/register')
    await expect(page.locator('input[placeholder*="username" i]')).toBeVisible({ timeout: 10000 })
  })
})
