import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { createQueryClient } from './queryClient'
import { routes } from './router'

const state = vi.hoisted(() => ({ crash: false }))

vi.mock('./pages/HomePage', () => ({
  HomePage: () => {
    if (state.crash) throw new Error('secret-render-crash-xyz')
    return <p>home ok</p>
  },
}))

function renderRealWiring(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return render(
    <AppErrorBoundary>
      <QueryClientProvider client={createQueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AppErrorBoundary>,
  )
}

describe('real app wiring: boundary + router (UX §2, §4, AC 10)', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    state.crash = false
    vi.restoreAllMocks()
  })

  it('renders the page normally when nothing throws', () => {
    renderRealWiring('/')
    expect(screen.getByText('home ok')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a render crash in the page shows the app fallback, not the router default error page', async () => {
    state.crash = true
    renderRealWiring('/')

    const h1 = await screen.findByRole('heading', {
      level: 1,
      name: 'Something went wrong',
    })
    expect(screen.getByRole('alert')).toContainElement(h1)
    expect(
      screen.getByRole('button', { name: 'Reload page' }),
    ).toBeInTheDocument()
    await waitFor(() => expect(h1).toHaveFocus())
    expect(document.body).not.toHaveTextContent('Unexpected Application Error')
    expect(document.body).not.toHaveTextContent('secret-render-crash-xyz')
  })

  it('an unknown path shows the app fallback, not the router 404 page', async () => {
    renderRealWiring('/nope')

    const h1 = await screen.findByRole('heading', {
      level: 1,
      name: 'Something went wrong',
    })
    expect(screen.getByRole('alert')).toContainElement(h1)
    expect(
      screen.getByRole('button', { name: 'Reload page' }),
    ).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent('404')
    expect(document.body).not.toHaveTextContent('Not Found')
  })
})
