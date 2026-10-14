export function getApiBaseUrl(): string {
  return import.meta.env.VITE_API_URL.replace(/\/+$/, '')
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

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  let response: Response
  try {
    response = await fetch(
      `${getApiBaseUrl()}/health`,
      signal ? { signal } : {},
    )
  } catch (cause) {
    if (signal?.aborted) throw cause
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
