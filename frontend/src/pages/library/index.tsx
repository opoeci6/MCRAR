import { useCallback, useState } from 'react'
import { listJobs } from '../../api/endpoints'
import type { Job } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { PageHeader } from '../../ui/PageHeader'
import { Notice } from '../../ui/Notice'
import { AddMusic } from './AddMusic'
import { JobHistory } from './JobHistory'
import { JobPanel } from './JobPanel'
import { LibraryStats } from './LibraryStats'
import { libraryStrings as t } from './strings'
import { TracksTable } from './TracksTable'
import styles from './index.module.css'

interface Active {
  job: Job
  settled: boolean
}

export default function LibraryPage() {
  const toast = useToast()
  const [refreshKey, setRefreshKey] = useState(0)
  const [focusSignal, setFocusSignal] = useState(0)
  const [active, setActive] = useState<Active | null>(null)
  const jobs = useAsync((signal) => listJobs({ signal }), [])
  const reloadJobs = jobs.reload

  // Reattach: a job that was started earlier (or from another tab) and is still running.
  const [attached, setAttached] = useState(false)
  if (!attached && jobs.data) {
    setAttached(true)
    const running = jobs.data.jobs.find((job) => job.status === 'running')
    if (running) setActive({ job: running, settled: false })
  }

  const show = useCallback((job: Job) => {
    setActive({ job, settled: job.status !== 'running' })
  }, [])

  const onStarted = useCallback(
    (job: Job) => {
      show(job)
      reloadJobs()
    },
    [show, reloadJobs],
  )

  const showRunning = useCallback(() => {
    listJobs()
      .then((response) => {
        const running = response.jobs.find((job) => job.status === 'running')
        if (running) show(running)
        reloadJobs()
      })
      .catch((caught: unknown) => toast.error(`${t.jobs.loadFailed}: ${errorMessage(caught)}`))
  }, [show, reloadJobs, toast])

  const onSettled = useCallback(() => {
    setActive((current) => (current ? { ...current, settled: true } : current))
    setRefreshKey((n) => n + 1) // the catalog changed
    reloadJobs()
  }, [reloadJobs])

  const busy = active !== null && !active.settled && active.job.status === 'running'

  return (
    <div className={styles.page}>
      <PageHeader title={t.title} description={t.description} />
      <LibraryStats refreshKey={refreshKey} />
      <AddMusic busy={busy} onStarted={onStarted} onShowRunning={showRunning} />
      {active ? (
        <section className={styles.job} aria-labelledby="library-job-heading">
          <h2 id="library-job-heading">{t.jobs.heading}</h2>
          <JobPanel
            key={active.job.id}
            job={active.job}
            onSettled={onSettled}
            onViewNew={() => {
              setRefreshKey((n) => n + 1)
              setFocusSignal((n) => n + 1)
            }}
            onDismiss={() => setActive(null)}
          />
        </section>
      ) : null}
      <TracksTable refreshKey={refreshKey} focusSignal={focusSignal} />
      {jobs.error && !jobs.data ? (
        <Notice kind="error">
          {t.jobs.loadFailed}: {errorMessage(jobs.error)}
        </Notice>
      ) : jobs.data ? (
        <JobHistory jobs={jobs.data.jobs} onShow={show} />
      ) : null}
    </div>
  )
}
