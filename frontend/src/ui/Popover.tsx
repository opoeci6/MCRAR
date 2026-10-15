import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { cx } from '../lib/cx'
import styles from './Popover.module.css'

export interface PopoverTriggerProps {
  ref: (element: HTMLButtonElement | null) => void
  onClick: () => void
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void
  'aria-haspopup': 'menu' | 'dialog'
  'aria-expanded': boolean
  'aria-controls': string | undefined
}

export type PopoverPlacement = 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end'

export interface PopoverProps {
  /** Renders the trigger button; spread `props` onto a `<button>` (or `Button`). */
  trigger: (props: PopoverTriggerProps) => ReactNode
  /** The panel content, or a function that gets `close`. */
  children: ReactNode | ((api: { close: () => void }) => ReactNode)
  /** Accessible name of the panel. */
  label: string
  /** `menu` adds arrow-key navigation among `[role="menuitem"]` children. */
  role?: 'dialog' | 'menu'
  placement?: PopoverPlacement
  className?: string
  onOpenChange?: (open: boolean) => void
}

const FOCUSABLE =
  '[role="menuitem"]:not(:disabled), input:not(:disabled), select:not(:disabled), button:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])'

/**
 * A small non-modal panel anchored to a trigger. Closes on Escape (focus returns to the trigger),
 * on a click outside, and when focus leaves it. Focus moves into the panel when it opens.
 * It is positioned in place (no portal), so do not put it inside an `overflow: hidden` parent.
 */
export function Popover({
  trigger,
  children,
  label,
  role = 'dialog',
  placement = 'bottom-start',
  className,
  onOpenChange,
}: PopoverProps) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [triggerEl, setTriggerEl] = useState<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const panelId = useId()
  const [focusEnd, setFocusEnd] = useState<'first' | 'last'>('first')

  const change = useCallback(
    (next: boolean) => {
      setOpen(next)
      onOpenChange?.(next)
    },
    [onOpenChange],
  )
  const close = useCallback(() => change(false), [change])

  useEffect(() => {
    if (!open) return
    const panel = panelRef.current
    if (panel) {
      const items = panel.querySelectorAll<HTMLElement>(FOCUSABLE)
      const target = focusEnd === 'last' ? items[items.length - 1] : items[0]
      ;(target ?? panel).focus()
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) change(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open, change, focusEnd])

  const closeAndRefocus = useCallback(() => {
    close()
    triggerEl?.focus()
  }, [close, triggerEl])

  const onWrapKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!open) return
    if (event.key === 'Escape') {
      event.stopPropagation()
      event.preventDefault()
      closeAndRefocus()
    }
  }

  const onPanelKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (role !== 'menu') return
    const items = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not(:disabled)') ?? [],
    )
    if (items.length === 0) return
    const index = items.indexOf(document.activeElement as HTMLElement)
    let next = -1
    if (event.key === 'ArrowDown') next = (index + 1) % items.length
    else if (event.key === 'ArrowUp') next = (index - 1 + items.length) % items.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = items.length - 1
    else if (event.key === 'Tab') close()
    if (next >= 0) {
      event.preventDefault()
      items[next]?.focus()
    }
  }

  const onTriggerClick = () => {
    setFocusEnd('first')
    change(!open)
  }

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (role !== 'menu' || open) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setFocusEnd(event.key === 'ArrowUp' ? 'last' : 'first')
      change(true)
    }
  }

  return (
    <div
      ref={wrapRef}
      className={styles.wrap}
      onKeyDown={onWrapKeyDown}
      onBlur={(event) => {
        // Focus left the whole popover (Tab past the end, or a click elsewhere that took focus).
        const next = event.relatedTarget as Node | null
        if (open && next && !wrapRef.current?.contains(next)) close()
      }}
    >
      {trigger({
        ref: setTriggerEl,
        onClick: onTriggerClick,
        onKeyDown: onTriggerKeyDown,
        'aria-haspopup': role,
        'aria-expanded': open,
        'aria-controls': open ? panelId : undefined,
      })}
      {open ? (
        <div
          ref={panelRef}
          id={panelId}
          role={role}
          aria-label={label}
          tabIndex={-1}
          className={cx(styles.panel, styles[placement], className)}
          onKeyDown={onPanelKeyDown}
        >
          {typeof children === 'function' ? children({ close: closeAndRefocus }) : children}
        </div>
      ) : null}
    </div>
  )
}
