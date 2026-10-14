import { QueryClient } from '@tanstack/react-query'

// One automatic retry after 1 s keeps time-to-error well under the 10 s
// target in UX 0.3 §4 (the request itself is bounded by the browser).
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: 1, retryDelay: 1000 } },
  })
}
