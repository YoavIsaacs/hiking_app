import { Component, createRef, type ReactNode } from 'react'
import { ErrorState } from './ErrorState'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  error: Error | null
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  override state: AppErrorBoundaryState = { error: null }
  private readonly headingRef = createRef<HTMLHeadingElement>()

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error }
  }

  override componentDidCatch(error: Error): void {
    console.error(error)
  }

  // A crash during the very first render mounts the boundary already in the
  // error state, so focus on mount as well as on update.
  override componentDidMount(): void {
    this.focusHeading()
  }

  override componentDidUpdate(): void {
    this.focusHeading()
  }

  private focusHeading(): void {
    if (this.state.error) this.headingRef.current?.focus()
  }

  override render(): ReactNode {
    if (!this.state.error) return this.props.children
    return (
      <main>
        <ErrorState
          title="Something went wrong"
          message="Hike Prep hit an unexpected problem. Reload the page to continue."
          headingLevel={1}
          headingRef={this.headingRef}
          action={{
            label: 'Reload page',
            onAction: () => {
              window.location.reload()
            },
          }}
        />
      </main>
    )
  }
}
