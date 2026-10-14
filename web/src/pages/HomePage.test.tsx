import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_URL } from '../test/handlers'
import { renderApp } from '../test/render'
import { server } from '../test/server'

const HEALTH = `${API_URL}/health`
const pending = () => new Promise<Response>(() => {})

const ERROR_TITLE = "Couldn't check the API"
const HTTP_MSG =
  'The API responded with an error (HTTP 500). Try again in a moment.'
const NETWORK_MSG =
  "Couldn't connect to the API. Check your connection, or that the API is running, then try again."
const INVALID_MSG = "The API sent a response this app doesn't understand."

const failures: Record<string, () => void> = {
  'HTTP 500': () =>
    server.use(http.get(HEALTH, () => new HttpResponse(null, { status: 500 }))),
  'network failure': () =>
    server.use(http.get(HEALTH, () => HttpResponse.error())),
  'body missing version': () =>
    server.use(
      http.get(HEALTH, () =>
        HttpResponse.json({ status: 'ok', git_sha: 'abc', env: 'test' }),
      ),
    ),
}

describe('HomePage loading state (UX AC 1, 9)', () => {
  it('shows "Checking the API…" in a status and no alert or Version while pending', async () => {
    server.use(http.get(HEALTH, pending))
    renderApp()
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Checking the API…',
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('Version')).not.toBeInTheDocument()
  })
})

describe('HomePage success state (UX AC 2, 9)', () => {
  it('shows "API is online." and the health details from /health', async () => {
    renderApp()
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('API is online.'),
    )
    const expected: [string, string][] = [
      ['Status', 'OK'],
      ['Version', '1.2.3'],
      ['Environment', 'test'],
      ['Commit', 'abc1234'],
    ]
    for (const [term, value] of expected) {
      const dt = screen.getByText(term, { selector: 'dt' })
      expect(dt.nextElementSibling).toHaveTextContent(value)
    }
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('HomePage error states (UX AC 3, 4, 5, 6)', () => {
  it('shows the HTTP error copy when /health returns 500', async () => {
    failures['HTTP 500']?.()
    renderApp()
    const alert = await screen.findByRole('alert')
    expect(
      within(alert).getByRole('heading', { name: ERROR_TITLE }),
    ).toBeInTheDocument()
    expect(alert).toHaveTextContent(HTTP_MSG)
  })

  it('shows the network error copy when /health fails to connect', async () => {
    failures['network failure']?.()
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent(NETWORK_MSG)
  })

  it('shows the unexpected-response copy when the body is missing version', async () => {
    failures['body missing version']?.()
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent(INVALID_MSG)
    expect(screen.queryByText('Version')).not.toBeInTheDocument()
  })

  it('shows the unexpected-response copy when status is not "ok"', async () => {
    server.use(
      http.get(HEALTH, () =>
        HttpResponse.json({
          status: 'degraded',
          version: '1.2.3',
          git_sha: 'abc',
          env: 'test',
        }),
      ),
    )
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent(INVALID_MSG)
    expect(screen.queryByText('Version')).not.toBeInTheDocument()
  })

  it('shows the unexpected-response copy when the body is not JSON', async () => {
    server.use(http.get(HEALTH, () => new HttpResponse('<html>nope</html>')))
    renderApp()
    expect(await screen.findByRole('alert')).toHaveTextContent(INVALID_MSG)
  })

  it.each(Object.keys(failures))(
    'offers "Try again" after %s and recovers once the API is back',
    async (name) => {
      failures[name]?.()
      renderApp()
      const user = userEvent.setup()
      await screen.findByRole('alert')
      const button = screen.getByRole('button', { name: 'Try again' })

      server.resetHandlers()
      await user.click(button)

      await waitFor(() =>
        expect(screen.getByRole('status')).toHaveTextContent('API is online.'),
      )
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    },
  )
})

describe('HomePage focus (UX AC 7)', () => {
  it('moves focus to the "API status" heading after Try again while pending', async () => {
    failures['HTTP 500']?.()
    renderApp()
    const user = userEvent.setup()
    await screen.findByRole('alert')

    server.use(http.get(HEALTH, pending))
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 2, name: 'API status' }),
      ).toHaveFocus(),
    )
    expect(screen.getByRole('status')).toHaveTextContent('Checking the API…')
  })

  it('does not steal focus on first load when an error appears', async () => {
    failures['HTTP 500']?.()
    renderApp()
    await screen.findByRole('alert')
    expect(
      screen.getByRole('heading', { level: 2, name: 'API status' }),
    ).not.toHaveFocus()
  })
})

describe('HomePage structure (UX AC 8)', () => {
  it('has one banner, one main, h1 "Hike Prep" and h2 "API status"', async () => {
    renderApp()
    expect(await screen.findAllByRole('banner')).toHaveLength(1)
    expect(screen.getAllByRole('main')).toHaveLength(1)
    expect(
      screen.getByRole('heading', { level: 1, name: 'Hike Prep' }),
    ).toBeInTheDocument()
    const h2 = screen.getByRole('heading', { level: 2, name: 'API status' })
    expect(h2).toHaveAttribute('tabindex', '-1')
  })
})
