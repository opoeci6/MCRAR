import { useState } from 'react'
import type { EmbedderInfo } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Select } from '../../ui/Select'
import { envVarName } from './env'
import type { SectionProps } from './types'
import { settingsStrings as t } from './strings'
import { useModelStatus } from './useModelStatus'
import { useSettingsSave } from './useSettingsSave'
import styles from './Section.module.css'

/** The name of a model as the select shows it. */
const embedderName = (embedder: EmbedderInfo) => `${embedder.key} (${embedder.model_id})`

export function ModelSection({ view, onUpdated }: SectionProps) {
  const [draft, setDraft] = useState<string | null>(null)
  const { pending, error, save } = useSettingsSave(onUpdated)
  const toast = useToast()
  const pinned = view.overridden_by_env.includes('default_embedder')
  const current = view.editable.default_embedder
  const selected = draft ?? current
  const status = useModelStatus(current)
  const { model } = status
  const currentEmbedder = view.embedders.find((embedder) => embedder.key === current)
  const s = t.model.status

  let statusText: string | null = null
  if (status.known) {
    if (model?.state === 'ready') {
      const vram = status.gpu ? s.vram(Math.round(status.gpu.vram_allocated_mb)) : null
      statusText = [s.ready(model.device, model.dtype), vram].filter(Boolean).join(' · ')
    } else if (model?.state === 'loading' || status.waiting) {
      statusText = s.loading(currentEmbedder ? embedderName(currentEmbedder) : current)
    } else if (!model) {
      statusText = s.absent
    }
  }

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
            {`${embedderName(embedder)}: ${embedder.commercial_ok ? t.model.commercial : t.model.research}`}
          </option>
        ))}
      </Select>
      {pinned ? <p className={styles.note}>{t.envPinned(envVarName('default_embedder'))}</p> : null}
      {model?.state === 'error' ? (
        <Notice kind="error" title={s.errorTitle}>
          {model.error}
        </Notice>
      ) : statusText ? (
        <p className={styles.note} role="status" aria-live="polite">
          {statusText}
        </p>
      ) : null}
      {error ? (
        <Notice kind="error" title={t.saveFailed}>
          {errorMessage(error)}
        </Notice>
      ) : null}
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={pinned || pending || selected === current}
          onClick={() =>
            void save({ default_embedder: selected }).then((ok) => {
              if (!ok) return
              setDraft(null)
              status.expectLoad()
              toast.info(t.model.saved)
            })
          }
        >
          {t.model.save}
        </Button>
      </div>
    </section>
  )
}
