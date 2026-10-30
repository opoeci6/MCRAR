/** "3:07" for 187 seconds; "1:02:03" past an hour; "–:––" for a missing or invalid value. */
export function formatTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '–:––'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const ss = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

/**
 * A download's progress as text: whole MB, or GB with one decimal once the larger of the two
 * reaches 1 GB, so both numbers share a unit. `total` is null while the size is unknown.
 */
export function formatDownload(doneBytes: number, totalBytes: number | null): { done: string; total: string | null } {
  const known = totalBytes != null && totalBytes > 0 ? totalBytes : null
  const gigabytes = Math.max(doneBytes, known ?? 0) >= 1e9
  const text = (bytes: number) => (gigabytes ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`)
  return { done: text(doneBytes), total: known === null ? null : text(known) }
}

/** The name of an embedder as the Settings select shows it, `key (model id)`. */
export function embedderName(embedder: { key: string; model_id: string }): string {
  return `${embedder.key} (${embedder.model_id})`
}

/** A number with a fixed number of decimals, or "–" when it is missing. */
export function formatNumber(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '–' : value.toFixed(digits)
}
