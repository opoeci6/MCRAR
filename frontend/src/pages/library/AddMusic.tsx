import { useId } from 'react'
import { usePersistentState } from '../../app/usePersistentState'
import { cx } from '../../lib/cx'
import { Notice } from '../../ui/Notice'
import { FreesoundForm } from './FreesoundForm'
import { JamendoForm } from './JamendoForm'
import { LocalForm } from './LocalForm'
import { MaintenancePanel } from './MaintenancePanel'
import { libraryStrings as t } from './strings'
import type { StartProps } from './startJob'
import styles from './AddMusic.module.css'

const TABS = [
  { id: 'jamendo', label: t.add.jamendo },
  { id: 'freesound', label: t.add.freesound },
  { id: 'local', label: t.add.local },
  { id: 'maintenance', label: t.add.maintenance },
] as const
type TabId = (typeof TABS)[number]['id']

/** The ways to start a job. All panels stay mounted so a half-filled form survives a tab switch. */
export function AddMusic(props: StartProps) {
  const [tab, setTab] = usePersistentState<TabId>('library.addTab', 'jamendo')
  const base = useId()
  return (
    <section className={styles.section} aria-labelledby={`${base}-heading`}>
      <h2 id={`${base}-heading`}>{t.add.heading}</h2>
      <div role="tablist" aria-label={t.add.tabs} className={styles.tabs}>
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`${base}-tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`${base}-panel-${item.id}`}
            tabIndex={tab === item.id ? 0 : -1}
            className={cx(styles.tab, tab === item.id && styles.active)}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {props.busy ? (
        <Notice kind="info" title={t.start.busyTitle}>
          {t.start.busyBody}
        </Notice>
      ) : null}
      {TABS.map((item) => (
        <div
          key={item.id}
          role="tabpanel"
          id={`${base}-panel-${item.id}`}
          aria-labelledby={`${base}-tab-${item.id}`}
          hidden={tab !== item.id}
        >
          {item.id === 'jamendo' ? <JamendoForm {...props} /> : null}
          {item.id === 'freesound' ? <FreesoundForm {...props} /> : null}
          {item.id === 'local' ?<LocalForm {...props} /> : null}
          {item.id === 'maintenance' ? <MaintenancePanel {...props} /> : null}
        </div>
      ))}
    </section>
  )
}
