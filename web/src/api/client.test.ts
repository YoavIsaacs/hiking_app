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

  it.each([
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
    'rejects with kind "invalid" for a 200 body that is %s',
    async (_name, resp) => {
      server.use(http.get(HEALTH, resp))
      expect(await failure()).toMatchObject({ kind: 'invalid' })
    },
  )
})
