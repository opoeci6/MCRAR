import { useState } from 'react'
import { errorMessage } from '../../api/useAsync'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Select } from '../../ui/Select'
import { envVarName } from './env'
import type { SectionProps } from './types'
import { settingsStrings as t } from './strings'
import { useSettingsSave } from './useSettingsSave'
import styles from './Section.module.css'

export function ModelSection({ view, onUpdated }: SectionProps) {
  const [draft, setDraft] = useState<string | null>(null)
  const { pending, error, save } = useSettingsSave(onUpdated)
  const pinned = view.overridden_by_env.includes('default_embedder')
  const current = view.editable.default_embedder
  const selected = draft ?? current

  return (
    <section className={styles.section} aria-labelledby="settings-model-heading">
      <h2 id="settings-model-heading">{t.model.heading}</h2>
      <Select
        label={t.model.label}
        hint={t.model.hint}
        value={selected}
        disabled={pinned || pending}
        onChange={(event) => setDraft(event.target.value)}
      >
        {view.embedders.map((embedder) => (
          <option key={embedder.key} value={embedder.key}>
            {`${embedder.key} (${embedder.model_id}): ${
              embedder.commercial_ok ? t.model.commercial : t.model.research
            }`}
          </option>
        ))}
      </Select>
      {pinned ? <p className={styles.note}>{t.envPinned(envVarName('default_embedder'))}</p> : null}
      {error ? (
        <Notice kind="error" title={t.saveFailed}>
          {errorMessage(error)}
        </Notice>
      ) : null}
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={pinned || pending || selected === current}
          onClick={() => void save({ default_embedder: selected }).then((ok) => ok && setDraft(null))}
        >
          {t.model.save}
        </Button>
      </div>
    </section>
  )
}
