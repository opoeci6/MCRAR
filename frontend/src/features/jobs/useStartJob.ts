import { useCallback, useState } from 'react'
import type { Job } from '../../api'

/** Runs a request that starts a job, and keeps its pending state and error. */
export function useStartJob(onStarted: (job: Job) => void) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const start = async (request: () => Promise<{ job: Job }>) => {
    setPending(true)
    setError(null)
    try {
      const { job } = await request()
      onStarted(job)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error(String(caught)))
    } finally {
      setPending(false)
    }
  }
  const reset = useCallback(() => setError(null), [])
  return { pending, error, start, reset }
}
