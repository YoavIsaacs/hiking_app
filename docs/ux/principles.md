# UX principles

Short and stable. Updated only when a step establishes a new pattern; the step that set it is in brackets.

1. **Fewest steps to a trustworthy checklist.** Defaults over settings; show why an item is on the list.
2. **Mobile-first, one-handed, outdoor-legible.** Design at 360 px first; tap targets ≥ 44 × 44 px.
3. **Offline is a normal state, not an error.** (Applies from Phase 1.)
4. **Errors say what happened and what to do.** One reusable error-state: plain-words title, a message with the
   cause (if known) and the next step, and at most one verb-phrase action ("Try again", "Reload page").
   Root `role="alert"`; no stack traces or technical detail shown to users. [0.3]
5. **Async results are announced.** A `role="status"` region exists from first render and carries the loading
   and success summary; errors go through the error-state's alert, never both. Automatic retries stay in the
   loading state; the error appears only after the last attempt. [0.3]
6. **Focus follows the user's action, not the network.** Don't move focus on initial load results; when an
   action unmounts the focused control, move focus to the section heading (`tabindex="-1"`). [0.3]
7. **Unexpected crashes** show a full-page fallback with a single h1 and "Reload page", focused on render. [0.3]
8. **No motion without a reduced-motion path.** Prefer text over spinners.
