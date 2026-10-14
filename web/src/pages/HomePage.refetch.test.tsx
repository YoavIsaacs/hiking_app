import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_URL } from '../test/handlers'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { renderApp } from '../test/render'
import { routes } from '../router'
import { server } from '../test/server'

const HEALTH = `${API_URL}/health`

describe('HomePage live regions and background refetch (UX §4, §6)', () => {
  it('leaves the status line empty while the alert is shown (no double announcement)', async () => {
    server.use(http.get(HEALTH, () => new HttpResponse(null, { status: 500 })))
    renderApp()
    const alert = await screen.findByRole('alert')
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    expect(screen.getByRole('status')).not.toHaveTextContent(
      alert.textContent ?? 'x',
    )
    expect(screen.getAllByRole('alert')).toHaveLength(1)
  })

  it('keeps the status region in the DOM across loading, error and success', async () => {
    renderApp()
    expect(screen.getByRole('status')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('API is online.'),
    )
  })

  it('shows the error state and drops the stale details when a refetch fails after a success', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider
          router={createMemoryRouter(routes, { initialEntries: ['/'] })}
        />
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('API is online.'),
    )
    server.use(http.get(HEALTH, () => new HttpResponse(null, { status: 503 })))
    await act(() => queryClient.refetchQueries({ queryKey: ['health'] }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('HTTP 503')
    expect(screen.getByRole('status')).not.toHaveTextContent('API is online.')
    expect(screen.queryByText('Version')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Try again' }),
    ).toBeInTheDocument()
  })
})
