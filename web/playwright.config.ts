import { defineConfig, devices } from '@playwright/test'
import { API_URL } from './e2e/constants.js'

// The API only allows CORS from http://localhost:5173 (api/app/config.py), so
// the web origin is pinned to that port and must not drift (strictPort).
const WEB_URL = 'http://localhost:5173'

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : [['html', { open: 'never' }]],
  use: { baseURL: WEB_URL, trace: 'on-first-retry' },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'pixel-7', use: { ...devices['Pixel 7'] } },
    { name: 'iphone-14', use: { ...devices['iPhone 14'] } },
  ],
  webServer: [
    {
      // create_app is a factory; there is no module-level `app`.
      command:
        'uv run --frozen uvicorn app.main:create_app --factory --port 8000',
      cwd: '../api',
      url: `${API_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // Dev server: no build step, so the run stays fast and starts the same
      // way on Windows and Linux. A production-build check belongs to CI.
      command: 'pnpm exec vite --host localhost --port 5173 --strictPort',
      url: WEB_URL,
      env: { VITE_API_URL: API_URL },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
