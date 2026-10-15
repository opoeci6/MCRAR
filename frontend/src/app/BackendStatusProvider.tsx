import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { getHealth } from '../api/endpoints'
import { BackendStatusContext } from './backendStatus'
import type { BackendStatus } from './backendStatus'

const ONLINE_POLL_MS = 15_000
const OFFLINE_POLL_MS = 3_000
const REQUEST_TIMEOUT_MS = 5_000

/** Polls `/api/health`: slowly while the backend is up, quickly while it is down. */
export function BackendStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackendStatus>({ state: 'checking', health: null })

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    let controller: AbortController | undefined
    let stopped = false

    // Keep the old object when nothing changed, so a quiet poll re-renders nobody.
    const update = (next: BackendStatus) =>
      setStatus((previous) =>
        previous.state === next.state && JSON.stringify(previous.health) === JSON.stringify(next.health)
          ? previous
          : next,
      )

    const check = async () => {
      const own = new AbortController()
      controller = own
      const giveUp = setTimeout(() => own.abort(), REQUEST_TIMEOUT_MS)
      let online = false
      try {
        const health = await getHealth({ signal: own.signal })
        if (stopped) return
        online = health?.status === 'ok'
        update(online ? { state: 'online', health } : { state: 'offline', health: null })
      } catch {
        if (stopped) return
        update({ state: 'offline', health: null })
      } finally {
        clearTimeout(giveUp)
      }
      timer = setTimeout(() => void check(), online ? ONLINE_POLL_MS : OFFLINE_POLL_MS)
    }

    void check()
    return () => {
      stopped = true
      controller?.abort()
      clearTimeout(timer)
    }
  }, [])

  return <BackendStatusContext.Provider value={status}>{children}</BackendStatusContext.Provider>
}
