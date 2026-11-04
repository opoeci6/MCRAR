const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** The tabbable controls inside `container`, in document order. */
export function focusableIn(container: HTMLElement | null | undefined): HTMLElement[] {
  return Array.from(container?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
}

/** The part of a keyboard event that the Tab trap needs (React's and the DOM's both fit). */
export interface TabKeyEvent {
  key: string
  shiftKey: boolean
  preventDefault: () => void
}

/**
 * Keeps Tab and Shift+Tab inside `container`: wraps from the last control to the first and back.
 * Call it from a keydown handler on the container (or the document).
 */
export function trapTabKey(event: TabKeyEvent, container: HTMLElement | null | undefined) {
  if (event.key !== 'Tab') return
  const items = focusableIn(container)
  if (items.length === 0) {
    event.preventDefault()
    return
  }
  const first = items[0]
  const last = items[items.length - 1]
  const active = document.activeElement
  if (event.shiftKey && (active === first || active === container)) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first?.focus()
  }
}
