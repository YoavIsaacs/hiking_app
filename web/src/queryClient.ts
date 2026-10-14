import { QueryClient } from '@tanstack/react-query'

// One automatic retry after 1 s, plus the per-attempt timeout in
// fetchHealth (HEALTH_TIMEOUT_MS), bounds time-to-error to 2 x 4 s + 1 s = 9 s,
// inside the 10 s target in UX 0.3 section 4.
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: 1, retryDelay: 1000 } },
  })
}
