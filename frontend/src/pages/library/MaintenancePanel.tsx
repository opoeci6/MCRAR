import { reprocess } from '../../api'
import { Button } from '../../ui/Button'
import { MissingFilesCard } from './MissingFilesCard'
import { libraryStrings as t } from './strings'
import { StartError } from '../../features/jobs/StartError'
import type { StartProps } from './startJob'
import { useStartJob } from '../../features/jobs/useStartJob'
import styles from './Forms.module.css'

export interface MaintenancePanelProps extends StartProps {
  /** Tracks were removed, so the track list is out of date. */
  onCatalogChanged?: () => void
}

export function MaintenancePanel({ busy, onStarted, onShowRunning, onCatalogChanged }: MaintenancePanelProps) {
  const { pending, error, start } = useStartJob(onStarted)
  return (
    <div className={styles.form}>
      <p className={styles.intro}>{t.maintenance.intro}</p>
      <div className={styles.cards}>
        <div className={styles.card}>
          <h3>{t.maintenance.embedTitle}</h3>
          <p>{t.maintenance.embedBody}</p>
          <Button disabled={busy || pending} onClick={() => void start(() => reprocess({ what: 'embed' }))}>
            {t.maintenance.embedAction}
          </Button>
        </div>
        <div className={styles.card}>
          <h3>{t.maintenance.tagTitle}</h3>
          <p>{t.maintenance.tagBody}</p>
          <Button disabled={busy || pending} onClick={() => void start(() => reprocess({ what: 'tag' }))}>
            {t.maintenance.tagAction}
          </Button>
        </div>
        <MissingFilesCard busy={busy} onChanged={onCatalogChanged} />
      </div>
      <StartError error={error} onShowRunning={onShowRunning} />
    </div>
  )
}
