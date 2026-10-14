import type { ReactNode, Ref } from 'react'

export interface ErrorStateProps {
  title: string
  message: string
  headingLevel?: 1 | 2 | 3 | 4 | 5 | 6
  action?: { label: string; onAction: () => void }
  headingRef?: Ref<HTMLHeadingElement>
}

export function ErrorState({
  title,
  message,
  headingLevel = 3,
  action,
  headingRef,
}: ErrorStateProps): ReactNode {
  const Heading = `h${headingLevel}` as const
  return (
    <div role="alert">
      <Heading ref={headingRef} tabIndex={headingRef ? -1 : undefined}>
        {title}
      </Heading>
      <p>{message}</p>
      {action ? (
        <button type="button" onClick={action.onAction}>
          {action.label}
        </button>
      ) : null}
    </div>
  )
}
