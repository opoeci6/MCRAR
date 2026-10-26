import type { Breakdown } from '../api/types'
import { cx } from '../lib/cx'
import { formatNumber } from '../lib/format'
import { strings } from '../strings'
import styles from './ScoreBreakdown.module.css'

export interface ScoreBreakdownProps {
  /** Terms by name: `{ semantic: { raw, weight, contribution }, ... }`. */
  breakdown: Breakdown
  className?: string
}

const ORDER = ['semantic', 'reference', 'tags', 'bpm', 'energy']

/**
 * Why a track got its score, one row per term: a bar for how well it matched (raw, 0 to 1), and
 * the points it added. A term that was not used in this search (weight 0, no raw value) is dimmed
 * and says so.
 */
export function ScoreBreakdown({ breakdown, className }: ScoreBreakdownProps) {
  const names = Object.keys(breakdown).sort((a, b) => {
    const ia = ORDER.indexOf(a)
    const ib = ORDER.indexOf(b)
    return (ia < 0 ? ORDER.length : ia) - (ib < 0 ? ORDER.length : ib)
  })

  return (
    <ul className={cx(styles.list, className)}>
      {names.map((name) => {
        const term = breakdown[name]
        if (!term) return null
        const label = strings.breakdown.terms[name] ?? name
        const inactive = term.raw == null || term.weight === 0
        const percent = Math.round(Math.min(1, Math.max(0, term.raw ?? 0)) * 100)
        const description = inactive
          ? strings.breakdown.describeInactive(label)
          : strings.breakdown.describe(
              label,
              formatNumber(term.raw),
              formatNumber(term.weight),
              formatNumber(term.contribution),
            )
        return (
          <li key={name} className={cx(styles.row, inactive && styles.inactive)}>
            <span className={styles.label} aria-hidden="true">
              {label}
            </span>
            <span className={styles.track} aria-hidden="true">
              {inactive ? null : <span className={styles.fill} style={{ width: `${percent}%` }} />}
            </span>
            <span className={styles.value} aria-hidden="true">
              {inactive ? strings.breakdown.inactive : `+${formatNumber(term.contribution)}`}
            </span>
            <span className="sr-only">{description}</span>
          </li>
        )
      })}
    </ul>
  )
}
