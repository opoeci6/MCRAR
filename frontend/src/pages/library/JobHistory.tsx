import type { Job } from '../../api/types'
import { Button } from '../../ui/Button'
import { libraryStrings as t } from './strings'
import styles from './JobHistory.module.css'

export interface JobHistoryProps {
  jobs: Job[]
  onShow: (job: Job) => void
}

/** The recent jobs the backend remembers, newest first. */
export function JobHistory({ jobs, onShow }: JobHistoryProps) {
  return (
    <section className={styles.section} aria-labelledby="library-history-heading">
      <h2 id="library-history-heading">{t.history.heading}</h2>
      {jobs.length === 0 ? (
        <p className={styles.empty}>{t.history.empty}</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table} aria-label={t.history.table}>
            <thead>
              <tr>
                <th scope="col">{t.history.started}</th>
                <th scope="col">{t.history.kind}</th>
                <th scope="col">{t.history.parameters}</th>
                <th scope="col">{t.history.status}</th>
                <th scope="col">
                  <span className="sr-only">{t.history.show}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const kind = t.jobs.kindNames[job.kind] ?? job.kind
                return (
                  <tr key={job.id}>
                    <td className={styles.nowrap}>{t.history.time(job.created_at)}</td>
                    <td>{kind}</td>
                    <td className={styles.params}>{t.history.paramsSummary(job.params)}</td>
                    <td>{t.jobs.statusNames[job.status] ?? job.status}</td>
                    <td>
                      <Button size="sm" aria-label={t.history.showJob(kind)} onClick={() => onShow(job)}>
                        {t.history.show}
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
