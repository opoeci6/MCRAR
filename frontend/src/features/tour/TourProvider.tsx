import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { getSettings, updateSettings } from '../../api/endpoints'
import { useBackendStatus } from '../../app/backendStatus'
import { TourContext } from './tourContext'
import { TourOverlay } from './TourOverlay'

export interface TourProviderProps {
  children: ReactNode
  /** How long a step waits for its target before it shows without a spotlight. Default 3 s. */
  targetTimeoutMs?: number
}

/** Where the user was when the tour started, so closing the tour can put them back. */
interface Origin {
  hash: string
  focused: HTMLElement | null
  focusedId: string
}

/** How many animation frames (about half a second) closing the tour waits for the opener. */
const FOCUS_RETRY_FRAMES = 30

function restoreFocus(origin: Origin) {
  const find = () => {
    if (origin.focused && document.contains(origin.focused)) return origin.focused
    // The page was unmounted and mounted again during the tour: look the control up by its id.
    return origin.focusedId ? document.getElementById(origin.focusedId) : null
  }
  const element = find()
  if (element) {
    element.focus()
  } else if (origin.focused && origin.focused !== document.body) {
    // The page may still be rendering after the hash was restored: keep looking for a moment.
    let frames = FOCUS_RETRY_FRAMES
    const retry = () => {
      const later = find()
      if (later) later.focus()
      else if (--frames > 0) requestAnimationFrame(retry)
    }
    requestAnimationFrame(retry)
  }
}

/**
 * Owns the first-run tour. It starts by itself once the backend is online and the settings say the
 * tour was never seen, and from `useTour().start()` (Settings). Closing it for any reason goes back
 * to where the user was and records that the tour was seen.
 */
export function TourProvider({ children, targetTimeoutMs }: TourProviderProps) {
  const { state } = useBackendStatus()
  const [index, setIndex] = useState<number | null>(null)
  // True while the tour is open; read synchronously so a double close sends one request.
  const openRef = useRef(false)
  const originRef = useRef<Origin | null>(null)

  const start = useCallback(() => {
    if (openRef.current) return
    openRef.current = true
    const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    originRef.current = { hash: window.location.hash, focused, focusedId: focused?.id ?? '' }
    setIndex(0)
  }, [])

  const close = useCallback(() => {
    if (!openRef.current) return
    openRef.current = false
    setIndex(null)
    const origin = originRef.current
    originRef.current = null
    if (origin) {
      if (window.location.hash !== origin.hash) window.location.hash = origin.hash
      restoreFocus(origin)
    }
    // A failure is ignored: the tour then shows again on the next start.
    updateSettings({ ui: { tutorial_seen: true } }).catch(() => {})
  }, [])

  // The first-run check: one successful look at the settings per page load.
  const checkedRef = useRef(false)
  const checkingRef = useRef(false)
  const aliveRef = useRef(true)
  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])
  useEffect(() => {
    if (state !== 'online' || checkedRef.current || checkingRef.current) return
    checkingRef.current = true
    getSettings()
      .then((view) => {
        checkedRef.current = true
        if (aliveRef.current && view?.editable?.ui?.tutorial_seen === false) start()
      })
      .catch(() => {})
      .finally(() => {
        checkingRef.current = false
      })
  }, [state, start])

  const value = useMemo(() => ({ active: index !== null, start }), [index, start])

  return (
    <TourContext.Provider value={value}>
      {children}
      {index !== null ? (
        <TourOverlay
          index={index}
          onIndexChange={setIndex}
          onClose={close}
          targetTimeoutMs={targetTimeoutMs}
        />
      ) : null}
    </TourContext.Provider>
  )
}
