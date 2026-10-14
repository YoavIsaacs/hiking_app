export function getApiBaseUrl(): string {
  return ''
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

export function fetchHealth(signal?: AbortSignal): Promise<Health> {
  void signal
  return Promise.reject(new Error('not implemented'))
}
