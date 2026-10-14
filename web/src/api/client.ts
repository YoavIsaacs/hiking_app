import createClient, { type Client } from 'openapi-fetch'
import type { components, paths } from './schema'

export function getApiBaseUrl(): string {
  const url = import.meta.env.VITE_API_URL
  if (!url) throw new Error('VITE_API_URL is not set')
  return url.replace(/\/+$/, '')
}

export type ApiErrorKind = 'http' | 'network' | 'invalid'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    if (status !== undefined) this.status = status
  }
}

type FieldGuards<T> = { [K in keyof T]-?: (v: unknown) => v is T[K] }

function hasShape<T>(value: unknown, guards: FieldGuards<T>): value is T {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (Object.keys(guards) as (keyof T & string)[]).every((key) =>
    guards[key](v[key]),
  )
}

const isString = (v: unknown): v is string => typeof v === 'string'

const healthGuards = {
  status: (v): v is 'ok' => v === 'ok',
  version: isString,
  git_sha: isString,
  env: isString,
} satisfies FieldGuards<components['schemas']['HealthResponse']>

// Per-attempt timeout. With one retry after 1 s (queryClient.ts) the worst
// case is 2 x 4 s + 1 s = 9 s, inside the 10 s target in UX 0.3 section 4.
export const HEALTH_TIMEOUT_MS = 4000

function createApiClient(baseUrl: string): Client<paths> {
  return createClient<paths>({ baseUrl, fetch: classifyingFetch })
}

// Reads globalThis.fetch at call time so test stubs and MSW keep working.
async function classifyingFetch(request: Request): Promise<Response> {
  try {
    return await globalThis.fetch(request)
  } catch (cause) {
    // An abort (caller or timeout) is classified by withTimeout.
    if (request.signal.aborted) throw cause
    throw new ApiError('network', 'Could not reach the API')
  }
}

async function withTimeout<T>(
  ms: number,
  signal: AbortSignal | undefined,
  run: (s: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, ms)
  const onCallerAbort = (): void => controller.abort()
  if (signal?.aborted) controller.abort()
  else signal?.addEventListener('abort', onCallerAbort, { once: true })

  try {
    return await run(controller.signal)
  } catch (cause) {
    if (signal?.aborted) throw cause
    if (timedOut)
      throw new ApiError('network', 'The API did not respond in time')
    throw cause
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onCallerAbort)
  }
}

export async function fetchHealth(
  signal?: AbortSignal,
): Promise<components['schemas']['HealthResponse']> {
  // Built before any try so a config error is not misclassified as network.
  const client = createApiClient(getApiBaseUrl())
  return withTimeout(HEALTH_TIMEOUT_MS, signal, async (s) => {
    let result
    try {
      result = await client.GET('/health', { signal: s })
    } catch (cause) {
      if (cause instanceof SyntaxError)
        throw new ApiError('invalid', 'API response was not JSON')
      throw cause
    }
    const { data, response } = result
    if (!response.ok) {
      throw new ApiError(
        'http',
        `API responded with HTTP ${response.status}`,
        response.status,
      )
    }
    if (!hasShape(data, healthGuards)) {
      throw new ApiError('invalid', 'API response had an unexpected shape')
    }
    return data
  })
}
