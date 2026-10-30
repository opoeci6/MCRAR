import type { HealthModel } from '../../api/types'
import { formatDownload } from '../../lib/format'
import { Notice } from '../../ui/Notice'
import { searchStrings as s } from './strings'
import styles from './ModelNotice.module.css'

/**
 * What the search is waiting for when its model is not ready: the first-run download (with a
 * bar once the size is known), the load into memory, or the error that stopped it. Nothing when
 * the model is ready or not known.
 */
export function ModelNotice({ model, name }: { model: HealthModel | null; name: string }) {
  if (!model || model.state === 'ready') return null
  if (model.state === 'error') {
    return (
      <Notice kind="warning" title={s.model.errorTitle}>
        <p>{model.error}</p>
        <p>{s.model.errorHint}</p>
      </Notice>
    )
  }
  if (model.phase === 'downloading' && model.download) {
    const { done_bytes: doneBytes, total_bytes: totalBytes } = model.download
    const { done, total } = formatDownload(doneBytes, totalBytes)
    return (
      <Notice>
        <p>{s.model.downloading(name, done, total)}</p>
        {total && totalBytes ? (
          <progress
            className={styles.bar}
            aria-label={s.model.progressLabel}
            max={totalBytes}
            value={Math.min(doneBytes, totalBytes)}
          />
        ) : null}
      </Notice>
    )
  }
  return <Notice>{s.model.loading(name)}</Notice>
}
