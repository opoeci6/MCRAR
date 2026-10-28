import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getImportSources, importForSearch, listJobs } from '../../api/endpoints'
import type { ImportSource, Job, SearchFilters } from '../../api/types'
import { useAsync } from '../../api/useAsync'
import type { JobView } from '../../features/jobs/jobState'
import { useStartJob } from '../../features/jobs/useStartJob'
import { importWording, searchStrings as s } from './strings'
import type { ImportWording } from './strings'

/** How many new tracks one import asks for, in all sources. */
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
  /** The wording in force when the import ended. */
  wording: ImportWording
}

export interface UseSearchImportOptions {
  /** The text and filters of the search on screen, which an import is for. */
  text: string | undefined
  filters: SearchFilters | undefined
  /** The import finished (or was cancelled with some tracks added). */
  onFinished: (outcome: ImportOutcome) => void
}

/** What the page says until the usable sources are known (or when they cannot be loaded). */
const DEFAULT_SOURCES: ImportSource[] = ['jamendo']

/**
 * Runs the "search for more" job of the Search page (Jamendo and/or Freesound, whichever have
 * their key): starts it, finds one that is already running when the page opens, and reports how
 * it ended. `wording` names the usable sources. The request never names them: left out, the
 * backend uses every source that has its key, which is what `wording` describes.
 */
export function useSearchImport({ text, filters, onFinished }: UseSearchImportOptions) {
  const usable = useAsync((signal) => getImportSources({ signal }), [])
  const sources = usable.data && usable.data.sources.length > 0 ? usable.data.sources : DEFAULT_SOURCES
  const wording = useMemo(() => importWording(sources), [sources])
  const wordingRef = useRef(wording)
  useEffect(() => {
    wordingRef.current = wording
  })
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
      setFailure(view.error ?? s.importing.failedFallback)
      return
    }
    const newTrackIds = view.report?.new_track_ids ?? []
    // A job the user cancelled before it added anything has nothing to show.
    if (view.status === 'done' || newTrackIds.length > 0) {
      finishedRef.current({
        text: String(view.params.text ?? ''),
        newTrackIds,
        wording: wordingRef.current,
      })
    }
  }, [])

  /** Hides the error and failure of an earlier attempt (a new search starts). */
  const reset = useCallback(() => {
    setFailure(null)
    resetStart()
  }, [resetStart])

  return {
    active,
    pending: starter.pending,
    error: starter.error,
    failure,
    sources,
    wording,
    start,
    onSettled,
    reset,
  }
}
