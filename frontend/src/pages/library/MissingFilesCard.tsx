import { useState } from 'react'
import { missingTracks, removeMissingTracks } from '../../api'
import type { MissingTracks } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { libraryStrings as t } from './strings'
import styles from './Forms.module.css'

const m = t.maintenance

/** How many of the tracks without a file are listed before "and N more". */
const SHOWN = 10

export interface MissingFilesCardProps {
  /** A job is running: removing tracks would be refused. */
  busy: boolean
  /** Tracks were removed, so the track list is out of date. */
  onChanged?: () => void
}

/** Finds the tracks of your own files whose file is gone, and removes them on request. */
export function MissingFilesCard({ busy, onChanged }: MissingFilesCardProps) {
  const [found, setFound] = useState<MissingTracks | null>(null)
  const [removed, setRemoved] = useState<number | null>(null)
  const [working, setWorking] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const check = async () => {
    setWorking(true)
    setProblem(null)
    setRemoved(null)
    setConfirming(false)
    try {
      setFound(await missingTracks())
    } catch (caught) {
      setFound(null)
      setProblem(errorMessage(caught))
    } finally {
      setWorking(false)
    }
  }

  const remove = async () => {
    setWorking(true)
    setProblem(null)
    try {
      const result = await removeMissingTracks()
      setRemoved(result.removed)
      setFound(null)
      setConfirming(false)
      onChanged?.()
    } catch (caught) {
      setProblem(errorMessage(caught))
    } finally {
      setWorking(false)
    }
  }

  return (
    <section className={styles.card} aria-labelledby="library-missing-heading">
      <h3 id="library-missing-heading">{m.missingTitle}</h3>
      <p>{m.missingBody}</p>
      <Button disabled={working} onClick={() => void check()}>
        {m.missingCheck}
      </Button>
      {problem ? (
        <Notice kind="error" title={m.missingFailed}>
          {problem}
        </Notice>
      ) : null}
      {removed !== null ? <Notice kind="info">{m.missingRemoved(removed)}</Notice> : null}
      {found && found.count === 0 ? <p className={styles.plain}>{m.missingNone}</p> : null}
      {found && found.count > 0 ? (
        <>
          <p className={styles.plain}>{m.missingFound(found.count)}</p>
          <ul className={styles.missingList}>
            {found.tracks.slice(0, SHOWN).map((track) => (
              <li key={track.id}>{m.missingItem(track.title, track.local_path)}</li>
            ))}
            {found.count > Math.min(SHOWN, found.tracks.length) ? (
              <li>{m.missingMore(found.count - Math.min(SHOWN, found.tracks.length))}</li>
            ) : null}
          </ul>
          {confirming ? (
            <div className={styles.confirm} role="group" aria-label={m.missingConfirmGroup}>
              <span>{m.missingConfirm(found.count)}</span>
              <Button variant="danger" size="sm" disabled={working || busy} onClick={() => void remove()}>
                {m.confirm}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={working}
                autoFocus
                onClick={() => setConfirming(false)}
              >
                {m.cancel}
              </Button>
            </div>
          ) : (
            <Button variant="danger" disabled={working || busy} onClick={() => setConfirming(true)}>
              {m.missingRemove(found.count)}
            </Button>
          )}
        </>
      ) : null}
    </section>
  )
}
