import { useEffect, useReducer, useRef } from 'react'
import { cancelJob, getJob, openJobEvents } from '../../api'
import type { Job } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { Button } from '../../ui/Button'
import { initialJobView, isFinal, jobReducer } from './jobState'
import type { JobView } from './jobState'
import { jobStrings as t } from './strings'
import styles from './InlineJobProgress.module.css'

export interface InlineJobProgressProps {
  job: Job
  /** What the job is doing, shown above the bar. */
  title: string
  /** Called once, with the final state of the job (done, failed or cancelled). */
  onSettled: (view: JobView) => void
}

/** A compact view of one running job: a progress bar, the current track and a Cancel button. */
export function InlineJobProgress({ job, title, onSettled }: InlineJobProgressProps) {
  const toast = useToast()
  const [view, dispatch] = useReducer(jobReducer, job, initialJobView)
  const settledRef = useRef(onSettled)
  useEffect(() => {
    settledRef.current = onSettled
  })

  useEffect(() => {
    dispatch({ type: 'reset', job })
    const controller = new AbortController()
    const close = openJobEvents(job.id, {
      onProgress: (data) => dispatch({ type: 'progress', data }),
      onWarning: (data) => dispatch({ type: 'warning', data }),
      onDone: (data) => dispatch({ type: 'done', data }),
      onFailed: (data) => dispatch({ type: 'failed', data }),
      onCancelled: (data) => dispatch({ type: 'cancelled', data }),
      onError: () => {
        dispatch({ type: 'lost' })
        // The stream is gone: ask for the last known state instead.
        getJob(job.id, { signal: controller.signal })
          .then((response) => dispatch({ type: 'settled', job: response.job }))
          .catch(() => {})
      },
    })
    return () => {
      controller.abort()
      close()
    }
    // The component is keyed by job id: a new job means a new component.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id])

  const finished = isFinal(view.status)
  const notified = useRef(false)
  useEffect(() => {
    if (finished && !notified.current) {
      notified.current = true
      settledRef.current(view)
    }
  }, [finished, view])

  const cancel = async () => {
    dispatch({ type: 'cancelRequested' })
    try {
      await cancelJob(view.id)
    } catch (caught) {
      toast.error(`${t.progress.cancelFailed}: ${errorMessage(caught)}`)
    }
  }

  const determinate = view.total != null && view.total > 0
  return (
    <section className={styles.box} aria-label={t.progress.panel}>
      <div className={styles.head}>
        <p className={styles.title}>{title}</p>
        <Button size="sm" variant="danger" disabled={view.cancelRequested || finished} onClick={cancel}>
          {view.cancelRequested ? t.progress.cancelling : t.progress.cancel}
        </Button>
      </div>
      <div className={styles.progressRow}>
        <progress
          className={styles.bar}
          aria-label={t.progress.label}
          max={determinate ? view.total! : undefined}
          value={determinate ? Math.min(view.index, view.total!) : undefined}
        />
        <span className={styles.progressText}>{t.progress.text(view.index, view.total)}</span>
      </div>
      {view.title ? (
        <p className={styles.current}>
          <span className={styles.muted}>{t.progress.currentTrack}:</span> {view.title}
        </p>
      ) : null}
      {view.streamLost && !finished ? <p className={styles.lost}>{t.progress.streamLost}</p> : null}
    </section>
  )
}
