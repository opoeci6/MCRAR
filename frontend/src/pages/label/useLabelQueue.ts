import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { deleteLabel, getLabel, getNextLabel, getTrack, putLabel } from '../../api/endpoints'
import type {
  Intensity,
  LabelPart,
  LabelStatus,
  PoolEntry,
  PoolPart,
  SceneLabel,
  TrackDetail,
} from '../../api/types'
import { errorMessage } from '../../api/useAsync'
import type { PlayableTrack } from '../../player/playerContext'
import { labelStrings as t } from './strings'

/** The track on screen: where it is in the pool and what the labeller already said about it. */
export interface Slot {
  track: PlayableTrack
  position: number
  part: PoolPart
  label: SceneLabel | null
}

export type QueueView =
  | { kind: 'loading' }
  | { kind: 'ready'; slot: Slot }
  /** Every track of the part is labelled or skipped. */
  | { kind: 'done' }
  | { kind: 'nopool' }
  | { kind: 'error'; message: string }

export interface LabelValues {
  scenes: string[]
  intensity: Intensity | null
}

const isStatus = (caught: unknown, status: number) => caught instanceof ApiError && caught.status === status

/**
 * The next track after `after` (the queue moves on even if someone skipped the tracks before it);
 * when nothing is left after it, the first track that is still open, so a track left behind by
 * "Back" or a jump is not forgotten.
 */
async function fetchNext(
  labeller: string,
  part: LabelPart,
  after: number | undefined,
  signal: AbortSignal,
): Promise<QueueView> {
  try {
    let next = await getNextLabel(labeller, part, after, { signal })
    if (next.track === null && after !== undefined) {
      next = await getNextLabel(labeller, part, undefined, { signal })
    }
    if (next.track === null) return { kind: 'done' }
    return {
      kind: 'ready',
      slot: { track: next.track, position: next.position, part: next.part, label: next.label },
    }
  } catch (caught) {
    if (isStatus(caught, 409)) return { kind: 'nopool' }
    throw caught
  }
}

function toPlayable(track: TrackDetail): PlayableTrack {
  return {
    id: track.id,
    title: track.title,
    artist: track.artist,
    risk: track.license.risk,
    license_code: track.license.code,
    attribution: track.license.attribution_text,
    license_url: track.license.url,
    commercial_license_url: track.license.commercial_license_url,
    duration_s: track.duration_s,
  }
}

/** A pool track picked from the list (or the one before the current): its details and its label. */
async function fetchEntry(entry: PoolEntry, labeller: string, signal: AbortSignal): Promise<QueueView> {
  const [track, label] = await Promise.all([
    getTrack(entry.track_id, { signal }),
    getLabel(entry.track_id, labeller, { signal }).catch((caught: unknown) => {
      if (isStatus(caught, 404)) return null // not labelled yet
      throw caught
    }),
  ])
  return { kind: 'ready', slot: { track: toPlayable(track), position: entry.position, part: entry.part, label } }
}

/**
 * The labelling queue of one labeller and part: the track on screen and the moves between tracks
 * (save, skip, delete, open another). One move runs at a time (`busy`); a newer one replaces an
 * older one that is still loading. A failed move leaves the track on screen with `error`.
 * It starts loading the first open track when it mounts: give it a `key` of the name and part.
 * `onChanged` runs after a label was stored or deleted (progress and pool list reload).
 */
export function useLabelQueue(labeller: string, part: LabelPart, onChanged: () => void) {
  const [view, setViewState] = useState<QueueView>({ kind: 'loading' })
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const viewRef = useRef(view)
  const controller = useRef<AbortController | null>(null)

  const setView = useCallback((next: QueueView) => {
    viewRef.current = next
    setViewState(next)
  }, [])

  const begin = useCallback(() => {
    controller.current?.abort()
    const own = new AbortController()
    controller.current = own
    setBusy(true)
    setError(null)
    return own
  }, [])

  /** What to show when a move failed: the old track with a message, or the error page. */
  const fail = useCallback(
    (caught: unknown, what: string) => {
      setBusy(false)
      if (viewRef.current.kind === 'ready') setError(`${what}: ${errorMessage(caught)}`)
      else setView({ kind: 'error', message: errorMessage(caught) })
    },
    [setView],
  )

  const finish = useCallback(
    (own: AbortController, task: Promise<QueueView>, what: string) => {
      task.then(
        (next) => {
          if (own.signal.aborted) return
          setView(next)
          setBusy(false)
        },
        (caught: unknown) => {
          if (!own.signal.aborted) fail(caught, what)
        },
      )
    },
    [fail, setView],
  )

  // The first open track, when the page opens (a new name or part mounts a new queue).
  useEffect(() => {
    const own = new AbortController()
    controller.current = own
    finish(own, fetchNext(labeller, part, undefined, own.signal), t.loadFailed)
    // The latest move, which may have replaced this one.
    return () => controller.current?.abort()
  }, [labeller, part, finish])

  const retry = useCallback(() => {
    setView({ kind: 'loading' })
    const own = begin()
    finish(own, fetchNext(labeller, part, undefined, own.signal), t.loadFailed)
  }, [begin, finish, labeller, part, setView])

  const store = useCallback(
    async (slot: Slot, status: LabelStatus, values: LabelValues) => {
      const own = begin()
      try {
        await putLabel(slot.track.id, { labeller, status, ...values })
      } catch (caught) {
        if (!own.signal.aborted) fail(caught, t.form.saveFailed)
        return
      }
      if (own.signal.aborted) return
      onChanged()
      finish(own, fetchNext(labeller, part, slot.position, own.signal), t.loadFailed)
    },
    [begin, fail, finish, labeller, onChanged, part],
  )

  const save = useCallback((slot: Slot, values: LabelValues) => store(slot, 'labelled', values), [store])
  const skip = useCallback(
    (slot: Slot) => store(slot, 'skipped', { scenes: [], intensity: null }),
    [store],
  )

  const remove = useCallback(
    async (slot: Slot) => {
      const own = begin()
      try {
        await deleteLabel(slot.track.id, labeller)
      } catch (caught) {
        if (!isStatus(caught, 404)) {
          if (!own.signal.aborted) fail(caught, t.form.deleteFailed)
          return
        }
      }
      if (own.signal.aborted) return
      onChanged()
      setView({ kind: 'ready', slot: { ...slot, label: null } })
      setBusy(false)
    },
    [begin, fail, labeller, onChanged, setView],
  )

  /** Shows a pool track and its label (for "Back" and the pool list). */
  const open = useCallback(
    (entry: PoolEntry) => {
      const own = begin()
      finish(own, fetchEntry(entry, labeller, own.signal), t.form.openFailed)
    },
    [begin, finish, labeller],
  )

  return { view, busy, error, retry, save, skip, remove, open }
}
