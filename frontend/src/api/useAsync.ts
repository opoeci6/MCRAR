import { useCallback, useEffect, useRef, useState } from 'react'
import { isAbort } from './client'

export interface AsyncState<T> {
  /** The last result for the current deps; kept while a reload runs; `undefined` after a dep change. */
  data: T | undefined
  /** An `ApiError` for a failed call. */
  error: Error | undefined
  /** True while a request is in flight (also on a reload). */
  loading: boolean
  /** Runs the request again. */
  reload: () => void
}

interface Settled<T> {
  deps: readonly unknown[]
  tick: number
  data: T | undefined
  error: Error | undefined
}

function sameDeps(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((value, i) => Object.is(value, b[i]))
}

/**
 * Runs `load` on mount and whenever `deps` change, and aborts the request on unmount or when the
 * deps change. `load` gets the `AbortSignal` to pass on to the endpoint function:
 *
 *   const projects = useAsync((signal) => listProjects({ signal }), [])
 *
 * `deps` must have the same length on every render (like any hook's dependency list).
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): AsyncState<T> {
  const [settled, setSettled] = useState<Settled<T> | undefined>(undefined)
  const [tick, setTick] = useState(0)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })

  // The `tick` makes `reload()` run the effect again; the caller owns the deps.
  /* oxlint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    const controller = new AbortController()
    loadRef
      .current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setSettled({ deps, tick, data, error: undefined })
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted || isAbort(caught)) return
        const error = caught instanceof Error ? caught : new Error(String(caught))
        // Keep the earlier data of the same deps so a failed reload does not blank the screen.
        setSettled((previous) => ({
          deps,
          tick,
          data: previous && sameDeps(previous.deps, deps) ? previous.data : undefined,
          error,
        }))
      })
    return () => controller.abort()
  }, [...deps, tick])
  /* oxlint-enable react-hooks/exhaustive-deps */

  const reload = useCallback(() => setTick((n) => n + 1), [])
  const current = settled && sameDeps(settled.deps, deps) ? settled : undefined
  return {
    data: current?.data,
    error: current?.tick === tick ? current.error : undefined,
    loading: !current || current.tick !== tick,
    reload,
  }
}

/** The message to show for a failed call (the backend's `detail` for an `ApiError`). */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
