import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_URL, validHealth } from '../test/handlers'
import { server } from '../test/server'
import { ApiError, fetchHealth, getApiBaseUrl } from './client'

const HEALTH = `${API_URL}/health`

async function failure(): Promise<unknown> {
  return fetchHealth().then(
    () => {
      throw new Error('expected fetchHealth to reject')
    },
    (e: unknown) => e,
  )
}

describe('getApiBaseUrl', () => {
  it('returns VITE_API_URL', () => {
    expect(getApiBaseUrl()).toBe(API_URL)
  })
})

describe('fetchHealth classification (UX §4 error causes)', () => {
  it('resolves with the health body on a valid 200', async () => {
    await expect(fetchHealth()).resolves.toEqual(validHealth)
  })

  it('rejects with kind "http" and the status on a non-2xx', async () => {
    server.use(http.get(HEALTH, () => new HttpResponse(null, { status: 503 })))
    const err = await failure()
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ kind: 'http', status: 503 })
  })

  it('rejects with kind "network" when the request fails', async () => {
    server.use(http.get(HEALTH, () => HttpResponse.error()))
    expect(await failure()).toMatchObject({ kind: 'network' })
  })

  it('rejects with kind "http" 500 for an HTML error page', async () => {
    server.use(
      http.get(
        HEALTH,
        () =>
          new HttpResponse('<html>boom</html>', {
            status: 500,
            headers: { 'Content-Type': 'text/html' },
          }),
      ),
    )
    const err = await failure()
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ kind: 'http', status: 500 })
  })

  it('rejects with kind "http" 502 for a JSON error body', async () => {
    server.use(
      http.get(HEALTH, () =>
        HttpResponse.json({ detail: 'bad gateway' }, { status: 502 }),
      ),
    )
    expect(await failure()).toMatchObject({ kind: 'http', status: 502 })
  })

  it.each([
    ['an empty body', () => new HttpResponse('', { status: 200 })],
    ['a 204 no-content', () => new HttpResponse(null, { status: 204 })],
    ['JSON null', () => HttpResponse.json(null)],
    [
      'an HTML page',
      () => new HttpResponse('<html>hi</html>', { status: 200 }),
    ],
    ['not JSON', () => new HttpResponse('<html></html>')],
    [
      'missing version',
      () => HttpResponse.json({ status: 'ok', git_sha: 'a', env: 'e' }),
    ],
    [
      'status not ok',
      () => HttpResponse.json({ ...validHealth, status: 'down' }),
    ],
    [
      'wrong field type',
      () => HttpResponse.json({ ...validHealth, version: 3 }),
    ],
  ])(
    'rejects with kind "invalid" for a 2xx response that is %s',
    async (_name, resp) => {
      server.use(http.get(HEALTH, resp))
      expect(await failure()).toMatchObject({ kind: 'invalid' })
    },
  )
})
