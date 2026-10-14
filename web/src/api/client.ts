export function getApiBaseUrl(): string {
  const url = import.meta.env.VITE_API_URL
  if (!url) throw new Error('VITE_API_URL is not set')
  return url.replace(/\/+$/, '')
}

// Hand-written for 0.3 only; replaced by generated types in 0.4.
export interface Health {
  status: 'ok'
  version: string
  git_sha: string
  env: string
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

function isHealth(value: unknown): value is Health {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    v['status'] === 'ok' &&
    typeof v['version'] === 'string' &&
    typeof v['git_sha'] === 'string' &&
    typeof v['env'] === 'string'
  )
}

// Per-attempt timeout. With one retry after 1 s (queryClient.ts) the worst
// case is 2 x 4 s + 1 s = 9 s, inside the 10 s target in UX 0.3 section 4.
export const HEALTH_TIMEOUT_MS = 4000

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  // Computed before the try so a config error is not misclassified as network.
  const url = `${getApiBaseUrl()}/health`
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, HEALTH_TIMEOUT_MS)
  const onCallerAbort = (): void => controller.abort()
  if (signal?.aborted) controller.abort()
  else signal?.addEventListener('abort', onCallerAbort, { once: true })

  try {
    return await requestHealth(url, controller.signal)
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

async function requestHealth(
  url: string,
  signal: AbortSignal,
): Promise<Health> {
  let response: Response
  try {
    response = await fetch(url, { signal })
  } catch (cause) {
    // An abort (caller or timeout) is classified by fetchHealth.
    if (signal.aborted) throw cause
    throw new ApiError('network', 'Could not reach the API')
  }
  if (!response.ok) {
    throw new ApiError(
      'http',
      `API responded with HTTP ${response.status}`,
      response.status,
    )
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError('invalid', 'API response was not JSON')
  }
  if (!isHealth(body)) {
    throw new ApiError('invalid', 'API response had an unexpected shape')
  }
  return body
}
