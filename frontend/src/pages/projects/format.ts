import type { Risk, ShortlistEntry } from '../../api/types'

/** "Oct 15, 2026" in the user's language; the text unchanged when it is not a date. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { dateStyle: 'medium' })
}

export const RISK_ORDER: Risk[] = ['green', 'amber', 'red', 'unknown']

/** How many shortlist entries fall in each licence risk class. */
export function riskCounts(items: ShortlistEntry[]): Record<Risk, number> {
  const counts: Record<Risk, number> = { green: 0, amber: 0, red: 0, unknown: 0 }
  for (const { track } of items) {
    counts[track.risk in counts ? track.risk : 'unknown'] += 1
  }
  return counts
}
