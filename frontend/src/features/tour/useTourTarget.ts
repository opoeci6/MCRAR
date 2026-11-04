import { useEffect, useState } from 'react'
import { navigate, parseHash } from '../../app/route'
import type { Box } from './placement'
import type { TourStep } from './steps'

/** How long to wait for a target to appear (a page may still be loading) before giving up. */
export const TARGET_TIMEOUT_MS = 3000

export interface TourTarget {
  /** The target's place in the window. Null: no spotlight (no target, not found, or no size). */
  rect: Box | null
  /** False while the page is switching and the target is being looked for. */
  settled: boolean
}

const NONE: TourTarget = { rect: null, settled: true }
const SEARCHING: TourTarget = { rect: null, settled: false }

/** A target taller than this share of the window below the header is shown by its top part only. */
const TALL_SHARE = 0.45
/** When to scroll to the target a second time, after the page has loaded its lists. */
const REVEAL_AGAIN_MS = 500
/** Room left between the sticky header and a tall target scrolled up under it. */
const TALL_MARGIN = 24

/** The height of the sticky page header (`--header-h`), which covers the top of the window. */
export function headerHeight(): number {
  const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h'))
  return Number.isFinite(value) ? value : 0
}

function tallLimit(): number {
  return (window.innerHeight - headerHeight()) * TALL_SHARE
}

/** The spotlight's box: the target, cut to its top part when it is tall (a whole section). */
function toBox(rect: DOMRect): Box | null {
  if (!(rect.width > 0) || !(rect.height > 0)) return null
  const height = Math.min(rect.height, tallLimit())
  return { top: rect.top, left: rect.left, width: rect.width, height }
}

/** Brings the target into view: centred, or a tall one with its top just under the header. */
function reveal(element: Element) {
  const rect = element.getBoundingClientRect()
  if (rect.height > tallLimit()) {
    if (typeof window.scrollBy === 'function' && !navigator.userAgent.includes('jsdom')) {
      window.scrollBy({ top: rect.top - headerHeight() - TALL_MARGIN })
    }
  } else if (typeof element.scrollIntoView === 'function') {
    // jsdom has no scrollIntoView; a real browser does.
    element.scrollIntoView({ block: 'center' })
  }
}

/**
 * Takes the tour to `step`: opens its tab, waits for the element marked `data-tour="<target>"`,
 * scrolls it into view and keeps its window position up to date. A step with no target, or a
 * target that does not show up in time, settles with a null `rect`, so the tour never gets stuck.
 */
export function useTourTarget(step: TourStep, timeoutMs = TARGET_TIMEOUT_MS): TourTarget {
  const { id, page, target } = step
  const [found, setFound] = useState<{ id: string; rect: Box | null } | null>(null)

  useEffect(() => {
    if (page && parseHash(window.location.hash).page !== page) navigate(page)
    if (!target) return

    const selector = `[data-tour="${target}"]`
    let settled = false
    let frame = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let observer: MutationObserver | undefined
    let resizeObserver: ResizeObserver | undefined
    let detach: (() => void) | undefined

    const stopWaiting = () => {
      observer?.disconnect()
      cancelAnimationFrame(frame)
      clearTimeout(timer)
    }

    const follow = (element: Element) => {
      reveal(element)
      // The page may still be growing (lists load after it opens), which can stop the first
      // scroll short: scroll once more when it has settled.
      const again = setTimeout(() => reveal(element), REVEAL_AGAIN_MS)
      const measure = () => setFound({ id, rect: toBox(element.getBoundingClientRect()) })
      measure()
      window.addEventListener('resize', measure)
      window.addEventListener('scroll', measure, true)
      if (typeof ResizeObserver !== 'undefined') {
        resizeObserver = new ResizeObserver(measure)
        resizeObserver.observe(element)
      }
      detach = () => {
        window.removeEventListener('resize', measure)
        window.removeEventListener('scroll', measure, true)
        resizeObserver?.disconnect()
        clearTimeout(again)
      }
    }

    const look = () => {
      if (settled) return
      const element = document.querySelector(selector)
      if (element) {
        settled = true
        stopWaiting()
        follow(element)
      } else {
        frame = requestAnimationFrame(look)
      }
    }

    observer = new MutationObserver(look)
    observer.observe(document.body, { childList: true, subtree: true })
    timer = setTimeout(() => {
      if (settled) return
      settled = true
      stopWaiting()
      setFound({ id, rect: null })
    }, timeoutMs)
    look()

    return () => {
      settled = true
      stopWaiting()
      detach?.()
    }
  }, [id, page, target, timeoutMs])

  if (!target) return NONE
  return found?.id === id ? { rect: found.rect, settled: true } : SEARCHING
}
