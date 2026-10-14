import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { http } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../queryClient'
import { routes } from '../router'
import { API_URL } from '../test/handlers'
import { server } from '../test/server'

describe('HomePage when /health never responds (UX §4)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  // UX §4: "the user must never wait silently longer than that [~10 s]".
  it('shows the error state within 10 s instead of "Checking the API…" forever', async () => {
    vi.useFakeTimers()
    server.use(http.get(`${API_URL}/health`, () => new Promise(() => {})))
    render(
      <QueryClientProvider client={createQueryClient()}>
        <RouterProvider
          router={createMemoryRouter(routes, { initialEntries: ['/'] })}
        />
      </QueryClientProvider>,
    )
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
