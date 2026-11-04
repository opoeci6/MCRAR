import { useEffect, useState } from 'react'

/**
 * What the desktop window (`mcrar desktop`, pywebview) offers the page through
 * `window.pywebview.api`. In a browser there is none of it.
 */
export interface DesktopApi {
  /** The native folder dialog: the folder chosen, or null when the user cancels. */
  pick_folder: (initial: string | null) => Promise<string | null>
}

declare global {
  interface Window {
    pywebview?: { api?: Partial<DesktopApi> }
  }
}

/** The desktop window's API, or null in a browser (or before pywebview has injected it). */
export function desktopApi(): DesktopApi | null {
  const api = typeof window === 'undefined' ? undefined : window.pywebview?.api
  return typeof api?.pick_folder === 'function' ? (api as DesktopApi) : null
}

/**
 * The desktop window's API once it is there. pywebview injects it after the page has loaded and
 * then fires `pywebviewready` on the window, so a component that renders first learns of it then.
 */
export function useDesktopApi(): DesktopApi | null {
  const [api, setApi] = useState<DesktopApi | null>(desktopApi)
  useEffect(() => {
    if (api) return
    const ready = () => setApi(desktopApi())
    window.addEventListener('pywebviewready', ready)
    ready() // it may have arrived between the first render and this effect
    return () => window.removeEventListener('pywebviewready', ready)
  }, [api])
  return api
}
