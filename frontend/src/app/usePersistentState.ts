import { useCallback, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

const store = new Map<string, unknown>()

/**
 * `useState` whose value survives the page being unmounted when the user switches tabs (the
 * shell shows one page at a time). Kept in memory only: a reload starts fresh.
 * Use it for the search box, filters and results, so coming back to Search finds them as left.
 * Keys are global: prefix them with the page (`search.query`).
 */
export function usePersistentState<T>(key: string, initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() =>
    store.has(key) ? (store.get(key) as T) : initial instanceof Function ? initial() : initial,
  )
  const set = useCallback<Dispatch<SetStateAction<T>>>(
    (next) => {
      setValue((previous) => {
        const resolved = next instanceof Function ? next(previous) : next
        store.set(key, resolved)
        return resolved
      })
    },
    [key],
  )
  return [value, set]
}

/** Forgets every stored value (for tests). */
export function clearPersistentState(): void {
  store.clear()
}
