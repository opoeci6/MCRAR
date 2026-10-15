/** "3:07" for 187 seconds; "1:02:03" past an hour; "–:––" for a missing or invalid value. */
export function formatTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '–:––'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const ss = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

/** A number with a fixed number of decimals, or "–" when it is missing. */
export function formatNumber(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '–' : value.toFixed(digits)
}
