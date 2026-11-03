import { useState } from 'react'
import { removeTrack, trackRemoval } from '../../api/endpoints'
import type { TrackDetail, TrackRemovalImpact } from '../../api/types'
import { errorMessage } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { Button } from '../../ui/Button'
import { TrashIcon } from '../../ui/icons'
import { Notice } from '../../ui/Notice'
import { trackFeatureStrings as t } from './strings'
import styles from './TrackDrawer.module.css'

const r = t.remove

/** The question to ask, with what goes with the track (zero parts are left out). */
function confirmText(track: TrackDetail, impact: TrackRemovalImpact): string {
  const parts = [
    impact.ratings > 0 ? r.ratings(impact.ratings) : null,
    impact.scene_labels > 0 ? r.sceneLabels(impact.scene_labels) : null,
    impact.projects > 0 ? r.projects(impact.projects) : null,
  ].filter((part): part is string => part !== null)
  const sentences = [r.question(track.title || t.untitled)]
  if (parts.length > 0) sentences.push(r.alsoDeletes(r.list(parts)))
  if (impact.copied_file) sentences.push(r.copiedFile)
  else if (track.source === 'local') sentences.push(r.fileKept)
  return sentences.join(' ')
}

export interface RemoveTrackProps {
  track: TrackDetail
  onRemoved: (trackId: number) => void
}

/**
 * "Remove from library" for the actions row of the track drawer. It first asks the backend what
 * the removal takes with it, then asks for a confirmation that says so.
 */
export function RemoveTrack({ track, onRemoved }: RemoveTrackProps) {
  const toast = useToast()
  const [impact, setImpact] = useState<TrackRemovalImpact | null>(null)
  const [working, setWorking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const ask = async () => {
    setWorking(true)
    setProblem(null)
    try {
      setImpact(await trackRemoval(track.id))
    } catch (caught) {
      setProblem(errorMessage(caught))
    } finally {
      setWorking(false)
    }
  }

  const confirm = async () => {
    setWorking(true)
    setProblem(null)
    try {
      await removeTrack(track.id)
    } catch (caught) {
      setProblem(errorMessage(caught))
      setWorking(false)
      return
    }
    toast.info(r.removed(track.title || t.untitled))
    onRemoved(track.id)
  }

  return (
    <>
      {impact ? (
        <div className={styles.confirm} role="group" aria-label={r.group}>
          <span className={styles.confirmText}>{confirmText(track, impact)}</span>
          <Button size="sm" variant="danger" disabled={working} onClick={() => void confirm()}>
            {r.confirm}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={working}
            autoFocus
            onClick={() => {
              setImpact(null)
              setProblem(null)
            }}
          >
            {r.cancel}
          </Button>
        </div>
      ) : (
        <Button
          size="sm"
          variant="danger"
          icon={<TrashIcon />}
          disabled={working}
          onClick={() => void ask()}
        >
          {r.action}
        </Button>
      )}
      {problem ? (
        <div className={styles.confirm}>
          <Notice kind="error" title={r.failed}>
            {problem}
          </Notice>
        </div>
      ) : null}
    </>
  )
}
