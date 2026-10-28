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

const REMOTE_SOURCES: readonly string[] = ['jamendo', 'freesound']

/**
 * The sources an import for these filters uses. With no Source filter that is every usable source
 * and nothing is sent (`request` is undefined: the backend picks the same). With one, it is the
 * filter's remote sources that are usable; `request` then names them. Usable sources that are
 * unknown or none do not narrow the filter: the backend then says what is missing.
 */
export function importSourcesFor(
  filters: SearchFilters | undefined,
  usable: readonly ImportSource[],
): { sources: ImportSource[]; request?: ImportSource[] } {
  const wanted = filters?.sources
  const known = usable.length > 0 ? usable : undefined
  if (!wanted || wanted.length === 0) return { sources: [...(known ?? DEFAULT_SOURCES)] }
  const remote = wanted.filter((source): source is ImportSource => REMOTE_SOURCES.includes(source))
  const sources = known ? remote.filter((source) => known.includes(source)) : remote
  return { sources, request: sources }
}

/**
 * Runs the "search for more" job of the Search page (Jamendo and/or Freesound, whichever have
 * their key and the Source filter allows): starts it, finds one that is already running when the
 * page opens, and reports how it ended. `wording` names the sources it uses. The request names
 * them only when the search has a Source filter; left out, the backend uses every source that has
 * its key, which is what `wording` describes. `available` is false when the filter leaves none.
 */
export function useSearchImport({ text, filters, onFinished }: UseSearchImportOptions) {
  const usable = useAsync((signal) => getImportSources({ signal }), [])
  const usableSources = usable.data?.sources
  const { sources, request: requestSources } = useMemo(
    () => importSourcesFor(filters, usableSources ?? []),
    [filters, usableSources],
  )
  const available = sources.length > 0
  const wording = useMemo(() => importWording(sources), [sources])
  const wordingRef = useRef(wording)
  useEffect(() => {
    wordingRef.current = wording
  })
  const [active, setActive] = useState<ActiveImport | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  /** What went wrong in an import that still added tracks, or in one source of it. */
  const [warnings, setWarnings] = useState<string[]>([])
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
    setWarnings([])
    void startRequest(() =>
      importForSearch({
        text,
        filters: filters ?? {},
        limit: IMPORT_LIMIT,
        ...(requestSources ? { sources: requestSources } : {}),
      }),
    )
  }, [text, filters, requestSources, startRequest])

  const onSettled = useCallback((view: JobView) => {
    setActive(null)
    const newTrackIds = view.report?.new_track_ids ?? []
    if (view.status === 'failed') {
      const message = view.error ?? s.importing.failedFallback
      if (newTrackIds.length === 0) {
        setFailure(message)
        return
      }
      // One source failed but the other's tracks are in: show them, with the error as a warning.
      setWarnings([...view.warnings.filter((warning) => warning !== message), message])
    } else {
      setWarnings(view.warnings)
    }
    // A job the user cancelled before it added anything has nothing to show.
    if (view.status !== 'cancelled' || newTrackIds.length > 0) {
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
    setWarnings([])
    resetStart()
  }, [resetStart])

  return {
    active,
    pending: starter.pending,
    error: starter.error,
    failure,
    warnings,
    available,
    sources,
    wording,
    start,
    onSettled,
    reset,
  }
}
