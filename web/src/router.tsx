import type { RouteObject } from 'react-router'
import { RouteErrorRethrow } from './components/RouteErrorRethrow'
import { HomePage } from './pages/HomePage'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <HomePage />,
    errorElement: <RouteErrorRethrow />,
  },
]
