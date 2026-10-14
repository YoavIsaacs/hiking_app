import { useRouteError } from 'react-router'

// Hands any route error (render crash, unknown URL) to the single
// AppErrorBoundary instead of React Router's default error page.
export function RouteErrorRethrow(): never {
  throw useRouteError()
}
