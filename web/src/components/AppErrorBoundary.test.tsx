import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

function Bomb(): never {
  throw new Error('secret-internal-detail-xyz')
}

describe('AppErrorBoundary (UX AC 10)', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the fallback with focus on the h1, a Reload button, and no error detail', async () => {
    expect(() =>
      render(
        <AppErrorBoundary>
          <Bomb />
        </AppErrorBoundary>,
      ),
    ).not.toThrow()
    const alert = screen.getByRole('alert')
    const h1 = screen.getByRole('heading', {
      level: 1,
      name: 'Something went wrong',
    })
    expect(alert).toContainElement(h1)
    expect(alert).toHaveTextContent(
      'Hike Prep hit an unexpected problem. Reload the page to continue.',
    )
    expect(
      screen.getByRole('button', { name: 'Reload page' }),
    ).toBeInTheDocument()
    await waitFor(() => expect(h1).toHaveFocus())
    expect(document.body).not.toHaveTextContent('secret-internal-detail-xyz')
  })

  it('renders children untouched when nothing throws', () => {
    render(
      <AppErrorBoundary>
        <p>fine</p>
      </AppErrorBoundary>,
    )
    expect(screen.getByText('fine')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
