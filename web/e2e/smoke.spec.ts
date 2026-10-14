import { expect, test } from '@playwright/test'

const API_URL = 'http://localhost:8000'

test('home page shows the API version from the real /health (UX AC 12)', async ({
  page,
  request,
}) => {
  const res = await request.get(`${API_URL}/health`)
  expect(res.ok()).toBe(true)
  const health = (await res.json()) as { version: string }

  await page.goto('/')

  await expect(page.getByRole('status')).toHaveText('API is online.')
  const version = page
    .locator('dt', { hasText: /^Version$/ })
    .locator('xpath=following-sibling::dd[1]')
  await expect(version).toHaveText(health.version)
  await expect(page).toHaveTitle('Hike Prep')
})

test('html element declares lang="en" (UX AC 13)', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
})
