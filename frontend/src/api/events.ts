import type { JobEventData } from './types'

export interface JobEventHandlers {
  onStarted?: (data: JobEventData['started']) => void
  onProgress?: (data: JobEventData['progress']) => void
  onWarning?: (data: JobEventData['warning']) => void
  onDone?: (data: JobEventData['done']) => void
  onFailed?: (data: JobEventData['failed']) => void
  onCancelled?: (data: JobEventData['cancelled']) => void
  /**
   * The stream broke and will not come back (the browser retries by itself, and the server
   * replays from the last event, so a brief drop never reaches this).
   */
  onError?: () => void
}

const FINAL = new Set(['done', 'failed', 'cancelled'])

/**
 * Follows a job's Server-Sent events. Returns a function that closes the stream; call it when
 * the component unmounts. The stream closes itself after `done`, `failed` or `cancelled`.
 */
export function openJobEvents(jobId: string, handlers: JobEventHandlers): () => void {
  const source = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`)
  let closed = false

  const close = () => {
    if (closed) return
    closed = true
    source.close()
  }

  const listen = <K extends keyof JobEventData>(
    type: K,
    call: ((data: JobEventData[K]) => void) | undefined,
  ) => {
    source.addEventListener(type, (event) => {
      if (closed) return
      let data: JobEventData[K]
      try {
        data = JSON.parse((event as MessageEvent<string>).data) as JobEventData[K]
      } catch {
        return // a malformed event is skipped; the stream goes on
      }
      if (FINAL.has(type)) close()
      call?.(data)
    })
  }

  listen('started', handlers.onStarted)
  listen('progress', handlers.onProgress)
  listen('warning', handlers.onWarning)
  listen('done', handlers.onDone)
  listen('failed', handlers.onFailed)
  listen('cancelled', handlers.onCancelled)

  source.addEventListener('error', () => {
    if (closed) return
    if (source.readyState === EventSource.CLOSED) {
      close()
      handlers.onError?.()
    }
  })

  return close
}
