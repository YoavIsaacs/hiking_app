// Live mode (post-deploy smoke): E2E_API_URL points the specs at a deployed API.
// Unset, the specs use the local server that playwright.config.ts starts.
export const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'
