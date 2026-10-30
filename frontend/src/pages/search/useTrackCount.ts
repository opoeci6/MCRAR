import { useEffect, useState } from 'react'
import { getHealth } from '../../api/endpoints'
import { useBackendStatus } from '../../app/backendStatus'

/**
 * How many tracks the catalog has, or null while that is unknown (nothing is said then). It is
 * fetched when the page opens and again whenever `recheck` changes, because the shell's own poll
 * is slow; a newer answer from the shell's poll replaces it. A failed fetch keeps the last count.
 */
export function useTrackCount(recheck: number): number | null {
  const shared = useBackendStatus().health
  const [count, setCount] = useState<number | null>(shared?.catalog.tracks ?? null)
  const [seenShared, setSeenShared] = useState(shared)
  if (shared !== seenShared) {
    setSeenShared(shared)
    if (shared) setCount(shared.catalog.tracks)
  }

  useEffect(() => {
    const controller = new AbortController()
    getHealth({ signal: controller.signal }).then(
      (health) => {
        if (typeof health?.catalog?.tracks === 'number') setCount(health.catalog.tracks)
      },
      () => {
        // Ignored: the backend indicator already says when the backend is offline.
      },
    )
    return () => controller.abort()
  }, [recheck])

  return count
}
