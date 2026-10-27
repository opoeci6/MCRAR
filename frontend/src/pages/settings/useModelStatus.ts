import { useEffect, useState } from 'react'
import { getHealth } from '../../api/endpoints'
import type { Health, HealthModel } from '../../api/types'
import { useBackendStatus } from '../../app/backendStatus'

const FAST_POLL_MS = 1_000
/** How long after a save the new model is waited for before the fast poll gives up. */
const EXPECT_LIMIT_MS = 30_000

export interface ModelStatus {
  /** False until a health answer is known: then there is nothing to say about the model. */
  known: boolean
  /** The model's entry in the health answer; null when it is not loaded, loading or failed. */
  model: HealthModel | null
  /** A save just changed the default and its entry has not shown up in health yet. */
  waiting: boolean
  gpu: Health['gpu']
  /** Call after a saved model change: the backend loads the new default in the background. */
  expectLoad: () => void
}

/**
 * What `/api/health` says about one model. It follows the shell's slow backend poll, and polls
 * every second itself only while the model is loading or a just-saved model has not appeared,
 * so the status line settles without a permanent fast poll. A failed fetch is ignored: the
 * backend indicator already says when the backend is offline.
 */
export function useModelStatus(key: string): ModelStatus {
  const shared = useBackendStatus().health
  const [health, setHealth] = useState<Health | null>(shared)
  const [seenShared, setSeenShared] = useState<Health | null>(shared)
  const [expecting, setExpecting] = useState(false)
  // A newer answer from the shell's poll replaces the one this hook fetched itself.
  if (shared !== seenShared) {
    setSeenShared(shared)
    setHealth(shared)
  }

  const model = health?.models.find((entry) => entry.key === key) ?? null
  // Once the entry appears the expectation is met, whatever happens to it later.
  if (expecting && model) setExpecting(false)
  const waiting = expecting && !model
  const polling = waiting || model?.state === 'loading'

  useEffect(() => {
    if (!polling) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    const tick = async () => {
      try {
        const next = await getHealth({ signal: controller.signal })
        if (!stopped) setHealth(next)
      } catch {
        // Ignored: the next tick tries again.
      }
      if (!stopped) timer = setTimeout(() => void tick(), FAST_POLL_MS)
    }
    void tick()
    return () => {
      stopped = true
      controller.abort()
      clearTimeout(timer)
    }
  }, [polling])

  useEffect(() => {
    if (!expecting) return
    const timer = setTimeout(() => setExpecting(false), EXPECT_LIMIT_MS)
    return () => clearTimeout(timer)
  }, [expecting])

  return {
    known: health !== null,
    model,
    waiting,
    gpu: health?.gpu ?? null,
    expectLoad: () => setExpecting(true),
  }
}
