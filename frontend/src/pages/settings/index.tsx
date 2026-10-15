import { useState } from 'react'
import { getSettings } from '../../api/endpoints'
import type { SettingsView } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { PageHeader } from '../../ui/PageHeader'
import { Spinner } from '../../ui/Spinner'
import { AboutSection } from './AboutSection'
import { ModelSection } from './ModelSection'
import { SecretsSection } from './SecretsSection'
import { settingsStrings as t } from './strings'
import { TuningSection } from './TuningSection'
import styles from './Section.module.css'

export default function SettingsPage() {
  const loaded = useAsync((signal) => getSettings({ signal }), [])
  // The newest view the backend sent after a save: it replaces the first load.
  const [saved, setSaved] = useState<SettingsView | null>(null)
  const view = saved ?? loaded.data

  return (
    <>
      <PageHeader title={t.title} description={t.description} />
      <div className={styles.page}>
        {loaded.error && !view ? (
          <Notice
            kind="error"
            action={
              <Button size="sm" onClick={loaded.reload}>
                {strings.common.retry}
              </Button>
            }
          >
            {t.loadFailed}: {errorMessage(loaded.error)}
          </Notice>
        ) : !view ? (
          <Spinner />
        ) : (
          <>
            <ModelSection view={view} onUpdated={setSaved} />
            <TuningSection view={view} onUpdated={setSaved} />
          </>
        )}
        <SecretsSection />
        {view ? <AboutSection view={view} /> : null}
      </div>
    </>
  )
}
