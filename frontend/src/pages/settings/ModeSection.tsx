import { useState } from 'react'
import type { SettingsView } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { hrefFor } from '../../app/route'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Toggle } from '../../ui/Toggle'
import { envVarName } from './env'
import { settingsStrings as t } from './strings'
import { useSettingsSave } from './useSettingsSave'
import styles from './Section.module.css'

export interface SectionProps {
  view: SettingsView
  onUpdated: (view: SettingsView) => void
}

export function ModeSection({ view, onUpdated }: SectionProps) {
  const [confirmOff, setConfirmOff] = useState(false)
  const [changed, setChanged] = useState(false)
  const { pending, error, save } = useSettingsSave(onUpdated)
  const pinned = view.overridden_by_env.includes('commercial_mode')
  const on = view.editable.commercial_mode

  const apply = async (next: boolean) => {
    setConfirmOff(false)
    if (await save({ commercial_mode: next })) setChanged(true)
  }

  return (
    <section className={styles.section} aria-labelledby="settings-mode-heading">
      <h2 id="settings-mode-heading">{t.mode.heading}</h2>
      <Toggle
        label={t.mode.toggle}
        hint={t.mode.explain}
        checked={on}
        disabled={pinned || pending}
        onChange={(next) => (next ? void apply(true) : setConfirmOff(true))}
      />
      {pinned ? <p className={styles.note}>{t.envPinned(envVarName('commercial_mode'))}</p> : null}
      {confirmOff ? (
        <Notice
          kind="warning"
          title={t.mode.confirmTitle}
          action={
            <div className={styles.actions}>
              <Button size="sm" variant="danger" onClick={() => void apply(false)}>
                {t.mode.confirmAction}
              </Button>
              <Button size="sm" onClick={() => setConfirmOff(false)}>
                {t.mode.keepOn}
              </Button>
            </div>
          }
        >
          {t.mode.confirmBody}
        </Notice>
      ) : null}
      {error ? (
        <Notice kind="error" title={t.saveFailed}>
          {errorMessage(error)}
        </Notice>
      ) : null}
      {changed && !error ? (
        <Notice
          kind="info"
          title={t.mode.retagTitle}
          action={<a href={hrefFor('library')}>{t.mode.retagLink}</a>}
        >
          {t.mode.retagBody}
        </Notice>
      ) : null}
    </section>
  )
}
