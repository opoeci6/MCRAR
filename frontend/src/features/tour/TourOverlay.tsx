import { useEffect, useId, useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { cx } from '../../lib/cx'
import { Button } from '../../ui/Button'
import { trapTabKey } from '../../ui/focusTrap'
import { centerCard, placeCard } from './placement'
import { TOUR_STEPS } from './steps'
import { tourStrings as t } from './strings'
import { headerHeight, useTourTarget } from './useTourTarget'
import styles from './TourOverlay.module.css'

/** Room between the target and the edge of its spotlight. */
export const SPOTLIGHT_PADDING = 8

export interface TourOverlayProps {
  /** Index into `TOUR_STEPS`. */
  index: number
  onIndexChange: (index: number) => void
  /** The tour ended: Skip, Escape, or Done. */
  onClose: () => void
  /** How long to wait for a step's target before showing the card without a spotlight. */
  targetTimeoutMs?: number
}

/** True for a key press that belongs to a text control, where the arrow keys must keep working. */
function isEditable(element: EventTarget | null): boolean {
  if (!(element instanceof HTMLElement)) return false
  return (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement ||
    element.isContentEditable ||
    element.contentEditable === 'true' ||
    element.contentEditable === 'plaintext-only'
  )
}

/**
 * The tour on screen: a layer that dims the page and swallows clicks, a spotlight box around the
 * step's target, and a card with the text and the Skip / Back / Next buttons.
 */
export function TourOverlay({ index, onIndexChange, onClose, targetTimeoutMs }: TourOverlayProps) {
  const step = TOUR_STEPS[index] ?? TOUR_STEPS[0]!
  const { rect, settled } = useTourTarget(step, targetTimeoutMs)
  const cardRef = useRef<HTMLDivElement>(null)
  const primaryRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const bodyId = useId()

  const isWelcome = index === 0
  const isLast = index === TOUR_STEPS.length - 1
  const spot = settled ? rect : null
  // The spotlight box: the target plus padding. The card keeps clear of it.
  const spotBox = spot
    ? {
        top: spot.top - SPOTLIGHT_PADDING,
        left: spot.left - SPOTLIGHT_PADDING,
        width: spot.width + 2 * SPOTLIGHT_PADDING,
        height: spot.height + 2 * SPOTLIGHT_PADDING,
      }
    : null

  const goNext = () => (isLast ? onClose() : onIndexChange(index + 1))
  const goBack = () => {
    if (index > 1) onIndexChange(index - 1)
  }

  // The key handler is kept in a ref so the document listener is added only once.
  const keyRef = useRef<(event: KeyboardEvent) => void>(() => {})
  useEffect(() => {
    keyRef.current = (event) => {
      if (event.defaultPrevented) return
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      } else if (event.key === 'Tab') {
        const card = cardRef.current
        if (card && !card.contains(document.activeElement)) {
          // Focus got out (a click on the dimmed page): bring it back instead of tabbing into the page.
          event.preventDefault()
          primaryRef.current?.focus()
        } else {
          trapTabKey(event, card)
        }
      } else if (
        (event.key === 'ArrowRight' || event.key === 'ArrowLeft') &&
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !isEditable(event.target)
      ) {
        event.preventDefault()
        if (event.key === 'ArrowRight') goNext()
        else goBack()
      }
    }
  })
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => keyRef.current(event)
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  // Focus the primary button on every step (before paint, so a test or a screen reader never sees it elsewhere).
  useLayoutEffect(() => {
    primaryRef.current?.focus()
  }, [index])

  // Place the card: next to the spotlight, or in the middle without one. The position is written
  // straight to the element so a resize does not need a render.
  const spotTop = spotBox?.top
  const spotLeft = spotBox?.left
  const spotWidth = spotBox?.width
  const spotHeight = spotBox?.height
  useLayoutEffect(() => {
    const card = cardRef.current
    if (!card) return
    const place = () => {
      const size = { width: card.offsetWidth, height: card.offsetHeight }
      const viewport = { width: window.innerWidth, height: window.innerHeight }
      const { top, left } =
        spotTop === undefined || spotLeft === undefined || spotWidth === undefined || spotHeight === undefined
          ? centerCard(size, viewport)
          : placeCard(
              { top: spotTop, left: spotLeft, width: spotWidth, height: spotHeight },
              size,
              viewport,
              headerHeight(),
            )
      card.style.top = `${top}px`
      card.style.left = `${left}px`
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [spotTop, spotLeft, spotWidth, spotHeight, index])

  return createPortal(
    <div
      className={cx(styles.layer, !spotBox && styles.dim)}
      data-testid="tour-layer"
      // Keep focus where it is when the dimmed page is clicked.
      onMouseDown={(event) => {
        if (!cardRef.current?.contains(event.target as Node)) event.preventDefault()
      }}
    >
      {spotBox ? (
        <div
          className={styles.spotlight}
          data-testid="tour-spotlight"
          data-target={step.target}
          style={{ top: spotBox.top, left: spotBox.left, width: spotBox.width, height: spotBox.height }}
        />
      ) : null}
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        className={styles.card}
      >
        {isWelcome ? null : (
          <p className={styles.progress}>{t.progress(index, TOUR_STEPS.length - 1)}</p>
        )}
        <h2 id={titleId} className={styles.title}>
          {step.title}
        </h2>
        <p id={bodyId} className={styles.body}>
          {step.body}
        </p>
        <div className={styles.actions}>
          {isLast ? null : (
            <Button variant="ghost" onClick={onClose}>
              {t.skip}
            </Button>
          )}
          <span className={styles.spacer} />
          {index > 1 ? <Button onClick={goBack}>{t.back}</Button> : null}
          <Button ref={primaryRef} variant="primary" onClick={goNext}>
            {isWelcome ? t.start : isLast ? t.done : t.next}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
