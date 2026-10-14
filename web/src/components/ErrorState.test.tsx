import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ErrorState } from './ErrorState'

describe('ErrorState (UX AC 11)', () => {
  it('renders the title as an h3 by default inside an alert, with the message', () => {
    render(<ErrorState title="Oops" message="It broke. Try later." />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('It broke. Try later.')
    expect(
      screen.getByRole('heading', { level: 3, name: 'Oops' }),
    ).toBeInTheDocument()
  })

  it('renders the title at the requested heading level', () => {
    render(<ErrorState title="Oops" message="m" headingLevel={1} />)
    expect(
      screen.getByRole('heading', { level: 1, name: 'Oops' }),
    ).toBeInTheDocument()
  })

  it('renders a button named by action.label that calls onAction on click', async () => {
    const onAction = vi.fn()
    render(
      <ErrorState
        title="Oops"
        message="m"
        action={{ label: 'Try again', onAction }}
      />,
    )
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'Try again' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('renders no button when there is no action', () => {
    render(<ErrorState title="Oops" message="m" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
