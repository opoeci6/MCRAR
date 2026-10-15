import { useCallback, useEffect, useRef, useState } from 'react'
import { importForSearch, listJobs } from '../../api/endpoints'
import type { Job, SearchFilters } from '../../api/types'
import type { JobView } from '../../features/jobs/jobState'
import { useStartJob } from '../../features/jobs/useStartJob'
import { searchStrings as s } from './strings'

/** How many Jamendo candidates one import asks for. */
export const IMPORT_LIMIT = 50

export const IMPORT_KIND = 'ingest-query'

/** An import that is running: its job and the search text it is for. */
export interface ActiveImport {
  job: Job
  text: string
}

export interface ImportOutcome {
  text: string
  newTrackIds: number[]
}

export interface UseJamendoImportOptions {
  /** The text and filters of the search on screen, which an import is for. */
  text: string | undefined
  filters: SearchFilters | undefined
  /** The import finished (or was cancelled with some tracks added). */
  onFinished: (outcome: ImportOutcome) => void
}

/**
 * Runs the "search Jamendo for more" job of the Search page: starts it, finds one that is
 * already running when the page opens, and reports how it ended.
 */
export function useJamendoImport({ text, filters, onFinished }: UseJamendoImportOptions) {
  const [active, setActive] = useState<ActiveImport | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const finishedRef = useRef(onFinished)
  useEffect(() => {
    finishedRef.current = onFinished
  })

  const starter = useStartJob((job) => setActive({ job, text: String(job.params.text ?? text ?? '') }))
  const { start: startRequest, reset: resetStart } = starter

  // Reattach: an import for the search on screen that was started earlier and is still running.
  const initialText = useRef(text)
  useEffect(() => {
    const wanted = initialText.current
    if (!wanted) return
    const controller = new AbortController()
    listJobs({ signal: controller.signal })
      .then((response) => {
        const running = response.jobs.find(
          (job) => job.kind === IMPORT_KIND && job.status === 'running' && job.params.text === wanted,
        )
        if (running) setActive((current) => current ?? { job: running, text: wanted })
      })
      .catch(() => {}) // no job list: the button still works
    return () => controller.abort()
  }, [])

  const start = useCallback(() => {
    if (!text) return
    setFailure(null)
    void startRequest(() => importForSearch({ text, filters: filters ?? {}, limit: IMPORT_LIMIT }))
  }, [text, filters, startRequest])

  const onSettled = useCallback((view: JobView) => {
    setActive(null)
    if (view.status === 'failed') {
      setFailure(view.error ?? s.jamendo.failedFallback)
      return
    }
    const newTrackIds = view.report?.new_track_ids ?? []
    // A job the user cancelled before it added anything has nothing to show.
    if (view.status === 'done' || newTrackIds.length > 0) {
      finishedRef.current({ text: String(view.params.text ?? ''), newTrackIds })
    }
  }, [])

  /** Hides the error and failure of an earlier attempt (a new search starts). */
  const reset = useCallback(() => {
    setFailure(null)
    resetStart()
  }, [resetStart])

  return { active, pending: starter.pending, error: starter.error, failure, start, onSettled, reset }
}
