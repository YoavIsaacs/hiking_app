import { describe, expect, it } from 'vitest'
import { createQueryClient } from './queryClient'

describe('createQueryClient', () => {
  it('limits automatic retries so the error shows within ~10 s (UX §4)', () => {
    const q = createQueryClient().getDefaultOptions().queries
    expect(q?.retry).toBe(1)
    expect(q?.retryDelay).toBe(1000)
  })
})
