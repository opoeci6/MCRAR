import { getStats } from '../../api/endpoints'
import { errorMessage, useAsync } from '../../api/useAsync'
import type { Risk, Stats } from '../../api/types'
import { cx } from '../../lib/cx'
import { strings } from '../../strings'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { libraryStrings as t } from './strings'
import styles from './LibraryStats.module.css'

const RISKS: Risk[] = ['green', 'amber', 'red', 'unknown']

export interface LibraryStatsProps {
  /** Changes when the catalog changed (a job finished): the numbers are loaded again. */
  refreshKey: number
}

export function LibraryStats({ refreshKey }: LibraryStatsProps) {
  const stats = useAsync((signal) => getStats({ signal }), [refreshKey])
  return (
    <section className={styles.section} aria-labelledby="library-stats-heading">
      <h2 id="library-stats-heading">{t.stats.heading}</h2>
      {stats.error && !stats.data ? (
        <Notice kind="error">
          {t.stats.loadFailed}: {errorMessage(stats.error)}
        </Notice>
      ) : !stats.data ? (
        <Spinner />
      ) : (
        <StatsCards stats={stats.data} />
      )}
    </section>
  )
}

function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

function StatsCards({ stats }: { stats: Stats }) {
  const sources = Object.entries(stats.tracks_by_source)
  const embeddings = Object.entries(stats.embeddings_by_model)
  return (
    <div className={styles.cards}>
      <div className={styles.card}>
        <div className={styles.label}>{t.stats.tracks}</div>
        <div className={styles.big} data-testid="stat-tracks">
          {stats.tracks}
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.label}>{t.stats.bySource}</div>
        {sources.length === 0 ? (
          <div className={styles.muted}>{t.stats.none}</div>
        ) : (
          <ul className={styles.list}>
            {sources.map(([source, count]) => (
              <li key={source}>
                <span>{t.stats.sourceNames[source] ?? source}</span>
                <strong>{count}</strong>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.card}>
        <div className={styles.label}>{t.stats.byRisk}</div>
        <ul className={styles.list}>
          {RISKS.map((risk) => (
            <li key={risk}>
              <span className={cx(styles.risk, styles[risk])}>{strings.license.risk[risk]}</span>
              <strong>{stats.tracks_by_risk[risk] ?? 0}</strong>
            </li>
          ))}
        </ul>
      </div>

      <div className={styles.card}>
        <div className={styles.label}>{t.stats.coverage}</div>
        <ul className={styles.list}>
          <li>
            {t.stats.analysed(stats.features.tracks_with_features, percent(stats.features.coverage))}
          </li>
          {embeddings.length === 0 ? (
            <li className={styles.muted}>{t.stats.noEmbeddings}</li>
          ) : (
            embeddings.map(([model, count]) => <li key={model}>{t.stats.embedded(model, count)}</li>)
          )}
        </ul>
      </div>
    </div>
  )
}
