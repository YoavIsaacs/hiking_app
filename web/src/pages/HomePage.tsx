import { useQuery } from '@tanstack/react-query'
import { useRef, type JSX } from 'react'
import { ApiError, fetchHealth } from '../api/client'
import { ErrorState } from '../components/ErrorState'

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.kind === 'http') {
    return `The API responded with an error (HTTP ${error.status}). Try again in a moment.`
  }
  if (error instanceof ApiError && error.kind === 'invalid') {
    return "The API sent a response this app doesn't understand. Try again; if it keeps happening, the app and API versions may not match."
  }
  return "Couldn't connect to the API. Check your connection, or that the API is running, then try again."
}

export function HomePage(): JSX.Element {
  const query = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => fetchHealth(signal),
  })
  const headingRef = useRef<HTMLHeadingElement>(null)

  const showError = query.isError && !query.isFetching
  const health = query.data
  let summary = ''
  if (health && !query.isError) summary = 'API is online.'
  else if (!showError) summary = 'Checking the API…'

  return (
    <>
      <header>
        <h1>Hike Prep</h1>
      </header>
      <main>
        <h2 ref={headingRef} tabIndex={-1}>
          API status
        </h2>
        <p role="status">{summary}</p>
        {health && !query.isError ? (
          <dl>
            <dt>Status</dt>
            <dd>OK</dd>
            <dt>Version</dt>
            <dd>{health.version}</dd>
            <dt>Environment</dt>
            <dd>{health.env}</dd>
            <dt>Commit</dt>
            <dd>{health.git_sha}</dd>
          </dl>
        ) : null}
        {showError ? (
          <ErrorState
            title="Couldn't check the API"
            message={errorMessage(query.error)}
            action={{
              label: 'Try again',
              onAction: () => {
                headingRef.current?.focus()
                void query.refetch()
              },
            }}
          />
        ) : null}
      </main>
    </>
  )
}
