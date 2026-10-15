import { useEffect, useReducer, useRef } from 'react'
import { cancelJob, getJob, openJobEvents } from '../../api'
import type { Job, JobReport } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { initialJobView, isFinal, jobReducer } from '../../features/jobs/jobState'
import { libraryStrings as t } from './strings'
import styles from './JobPanel.module.css'

export interface JobPanelProps {
  job: Job
  /** Called once the job has reached its final state. */
  onSettled: () => void
  /** The user wants to look at the tracks the job added. */
  onViewNew: () => void
  onDismiss: () => void
}

/** Follows one job live through its event stream and shows its progress and final report. */
export function JobPanel({ job, onSettled, onViewNew, onDismiss }: JobPanelProps) {
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
    // The panel is keyed by job id: a new job means a new panel.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id])

  const finished = isFinal(view.status)
  const notified = useRef(false)
  useEffect(() => {
    if (finished && !notified.current) {
      notified.current = true
      settledRef.current()
    }
  }, [finished])

  const cancel = async () => {
    dispatch({ type: 'cancelRequested' })
    try {
      await cancelJob(view.id)
    } catch (caught) {
      toast.error(`${t.jobs.cancelFailed}: ${errorMessage(caught)}`)
    }
  }

  const kindName = t.jobs.kindNames[view.kind] ?? view.kind
  const determinate = view.total != null && view.total > 0
  return (
    <section className={styles.panel} aria-label={t.jobs.panel}>
      <div className={styles.head}>
        <h3 className={styles.kind}>{kindName}</h3>
        <span className={styles.status} data-status={view.status}>
          {t.jobs.statusNames[view.status] ?? view.status}
        </span>
        <div className={styles.actions}>
          {finished ? (
            <>
              <Button variant="primary" size="sm" onClick={onViewNew}>
                {t.jobs.viewNew}
              </Button>
              <Button size="sm" onClick={onDismiss}>
                {t.jobs.dismiss}
              </Button>
            </>
          ) : (
            <Button size="sm" variant="danger" disabled={view.cancelRequested} onClick={cancel}>
              {view.cancelRequested ? t.jobs.cancelling : t.jobs.cancel}
            </Button>
          )}
        </div>
      </div>

      {!finished ? (
        <div className={styles.progressRow}>
          <progress
            className={styles.bar}
            aria-label={t.jobs.progressLabel}
            max={determinate ? view.total! : undefined}
            value={determinate ? Math.min(view.index, view.total!) : undefined}
          />
          <span className={styles.progressText}>{t.jobs.progressText(view.index, view.total)}</span>
        </div>
      ) : null}

      {!finished && view.cancelRequested ? <Notice kind="info">{t.jobs.cancelRequested}</Notice> : null}
      {!finished && view.title ? (
        <p className={styles.current}>
          <span className={styles.muted}>{t.jobs.currentTrack}:</span> {view.title}
        </p>
      ) : null}

      <ul className={styles.counters}>
        <li>
          {t.jobs.counters.done}: <strong>{view.done}</strong>
        </li>
        <li>
          {t.jobs.counters.skipped}: <strong>{view.skipped}</strong>
        </li>
        <li>
          {t.jobs.counters.failed}: <strong>{view.failed}</strong>
        </li>
      </ul>

      {view.warnings.length > 0 ? (
        <div className={styles.warnings}>
          <strong>{t.jobs.warnings}</strong>
          <ul>
            {view.warnings.map((warning, index) => (
              <li key={index}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {view.streamLost && !finished ? <Notice kind="warning">{t.jobs.streamLost}</Notice> : null}
      {view.status === 'failed' && view.error ? (
        <Notice kind="error" title={t.jobs.errorTitle}>
          {view.error}
        </Notice>
      ) : null}
      {view.report ? <Report report={view.report} /> : null}
    </section>
  )
}

function Report({ report }: { report: JobReport }) {
  const rows: [string, string | number][] = [
    [t.jobs.report.seen, report.seen],
    [t.jobs.report.new, report.new],
    [t.jobs.report.updated, report.updated],
    [t.jobs.report.processed, report.processed],
    [t.jobs.report.skipped, report.skipped],
    [t.jobs.report.failed, report.failed],
    [t.jobs.report.elapsed, t.jobs.report.seconds(report.elapsed_s)],
  ]
  return (
    <div className={styles.report}>
      <h4>{t.jobs.report.heading}</h4>
      <dl className={styles.reportGrid}>
        {rows.map(([label, value]) => (
          <div key={label} className={styles.reportItem}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {report.aborted ? <Notice kind="warning">{t.jobs.report.aborted(report.aborted)}</Notice> : null}
      {report.failures.length > 0 ? (
        <details className={styles.failures}>
          <summary>{t.jobs.report.failures(report.failures.length, report.failures_total)}</summary>
          <ul>
            {report.failures.map((failure, index) => (
              <li key={`${failure.source_id}-${index}`}>
                {t.jobs.report.failure(failure.title, failure.stage, failure.message)}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  )
}
