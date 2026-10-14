import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

function Bomb(): never {
  throw new Error('boom')
}

describe('AppErrorBoundary Reload page (UX AC 10, §4)', () => {
  const original = window.location
  const reload = vi.fn()

  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...original, reload },
    })
  })
  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: original,
    })
    reload.mockReset()
    vi.restoreAllMocks()
  })

  it('reloads the current page when "Reload page" is clicked', async () => {
    render(
      <AppErrorBoundary>
        <Bomb />
      </AppErrorBoundary>,
    )
    expect(reload).not.toHaveBeenCalled()
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'Reload page' }))
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('logs the thrown error to the console only', () => {
    render(
      <AppErrorBoundary>
        <Bomb />
      </AppErrorBoundary>,
    )
    const logged = vi
      .mocked(console.error)
      .mock.calls.some((args) =>
        args.some((a) => a instanceof Error && a.message === 'boom'),
      )
    expect(logged).toBe(true)
  })
})
