import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { validHealth } from '../test/handlers'
import { server } from '../test/server'
import { fetchHealth, getApiBaseUrl } from './client'

describe('API base URL handling', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('strips trailing slashes and requests <base>/health', async () => {
    vi.stubEnv('VITE_API_URL', 'http://x.test//')
    expect(getApiBaseUrl()).toBe('http://x.test')
    let requested = ''
    server.use(
      http.get('http://x.test/health', ({ request }) => {
        requested = request.url
        return HttpResponse.json(validHealth)
      }),
    )
    await expect(fetchHealth()).resolves.toEqual(validHealth)
    expect(requested).toBe('http://x.test/health')
  })

  it('throws a clear error when VITE_API_URL is missing or empty', () => {
    vi.stubEnv('VITE_API_URL', '')
    expect(() => getApiBaseUrl()).toThrow('VITE_API_URL is not set')
  })

  it('surfaces the config error from fetchHealth, not as a network ApiError', async () => {
    vi.stubEnv('VITE_API_URL', '')
    const err = await fetchHealth().then(
      () => null,
      (e: unknown) => e,
    )
    expect(err).toBeInstanceOf(Error)
    expect(err).not.toHaveProperty('kind')
    expect(err).toHaveProperty('message', 'VITE_API_URL is not set')
  })
})
