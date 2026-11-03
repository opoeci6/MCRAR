import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { FolderBrowser } from './FolderBrowser'

export interface FolderPicker {
  /**
   * Asks the user for a folder: the path chosen, or null when they cancel. `initialPath` is
   * where to start (an absolute path), when there is one.
   */
  pick: (initialPath?: string) => Promise<string | null>
  /** What the caller renders so the picker can show itself (nothing while it is closed). */
  element: ReactNode
}

interface Request {
  initialPath: string | undefined
  resolve: (path: string | null) => void
}

/**
 * The one way the Library asks for a folder. Today it opens the folder browser in a side panel,
 * which walks the folders through the backend. A desktop window can replace this hook with one
 * that calls the native folder dialog and renders no `element`; the callers do not change.
 */
export function useFolderPicker(): FolderPicker {
  const [request, setRequest] = useState<Request | null>(null)
  const latest = useRef<Request | null>(null)

  const settle = useCallback((path: string | null) => {
    const open = latest.current
    latest.current = null
    setRequest(null)
    open?.resolve(path)
  }, [])

  const pick = useCallback(
    (initialPath?: string) =>
      new Promise<string | null>((resolve) => {
        latest.current?.resolve(null) // a second request cancels the first
        const next = { initialPath, resolve }
        latest.current = next
        setRequest(next)
      }),
    [],
  )

  // A caller that is gone must not leave its promise hanging.
  useEffect(() => () => latest.current?.resolve(null), [])

  const element = request ? (
    <FolderBrowser
      initialPath={request.initialPath}
      onChoose={(path) => settle(path)}
      onCancel={() => settle(null)}
    />
  ) : null
  return { pick, element }
}
