export interface ErrorStateProps {
  title: string
  message: string
  headingLevel?: 1 | 2 | 3 | 4 | 5 | 6
  action?: { label: string; onAction: () => void }
}

export function ErrorState(props: ErrorStateProps): React.JSX.Element | null {
  void props
  return null
}
