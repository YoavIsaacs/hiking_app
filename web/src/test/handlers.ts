import { http, HttpResponse, type HttpHandler } from 'msw'
import type { components } from '../api/schema'

export const API_URL = 'http://api.test'

export const validHealth = {
  status: 'ok',
  version: '1.2.3',
  git_sha: 'abc1234',
  env: 'test',
} as const satisfies components['schemas']['HealthResponse']

export const handlers: HttpHandler[] = [
  http.get(`${API_URL}/health`, () => HttpResponse.json(validHealth)),
]
