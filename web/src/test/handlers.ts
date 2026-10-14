import { http, HttpResponse, type HttpHandler } from 'msw'

export const API_URL = 'http://api.test'

export const validHealth = {
  status: 'ok',
  version: '1.2.3',
  git_sha: 'abc1234',
  env: 'test',
} as const

export const handlers: HttpHandler[] = [
  http.get(`${API_URL}/health`, () => HttpResponse.json(validHealth)),
]
