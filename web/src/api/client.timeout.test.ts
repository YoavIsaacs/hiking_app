import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, fetchHealth, HEALTH_TIMEOUT_MS } from './client'

const body = { status: 'ok', version: '1', git_sha: 'abc', env: 'test' }

function hangingFetch(): void {
  vi.stubGlobal(
    'fetch',
    (request: Request) =>
      new Promise((_resolve, reject) => {
        request.signal.addEventListener('abort', () =>
          reject(new DOMException('aborted', 'AbortError')),
        )
      }),
  )
}

describe('fetchHealth timeout', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('throws a network ApiError when the request exceeds the timeout', async () => {
    hangingFetch()
    const result = fetchHealth().catch((e: unknown) => e)
    await vi.advanceTimersByTimeAsync(HEALTH_TIMEOUT_MS)
    const error = await result
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).kind).toBe('network')
  })

  it('rethrows the abort when the caller aborts', async () => {
    hangingFetch()
    const controller = new AbortController()
    const result = fetchHealth(controller.signal).catch((e: unknown) => e)
    controller.abort()
    const error = await result
    expect(error).not.toBeInstanceOf(ApiError)
    expect((error as DOMException).name).toBe('AbortError')
  })

  it('clears the timer after a successful response', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(Response.json(body)))
    await fetchHealth()
    expect(vi.getTimerCount()).toBe(0)
  })
})
