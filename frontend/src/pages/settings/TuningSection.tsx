import { useState } from 'react'
import type { SearchWeights, SettingsUpdate } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { TextInput } from '../../ui/TextInput'
import { envVarName } from './env'
import type { SectionProps } from './types'
import { settingsStrings as t } from './strings'
import { useSettingsSave } from './useSettingsSave'
import styles from './Section.module.css'

const DEFAULT_TUNING = {
  pool_size: 200,
  max_per_artist: 2,
  min_results: 1,
  weights: { semantic: 0.6, tags: 0.2, bpm: 0.1, energy: 0.1 } satisfies SearchWeights,
}

type IntField = 'pool_size' | 'max_per_artist' | 'min_results'
const INT_FIELDS: { name: IntField; label: string; hint: string; min: number }[] = [
  { name: 'pool_size', label: t.tuning.poolSize, hint: t.tuning.poolSizeHint, min: 1 },
  { name: 'max_per_artist', label: t.tuning.maxPerArtist, hint: t.tuning.maxPerArtistHint, min: 1 },
  { name: 'min_results', label: t.tuning.minResults, hint: t.tuning.minResultsHint, min: 0 },
]
const WEIGHT_FIELDS = ['semantic', 'tags', 'bpm', 'energy'] as const

/** The values as text, so a half-typed number is not rejected while typing. */
type Draft = Record<string, string>

function toDraft(search: SectionProps['view']['editable']['search']): Draft {
  return {
    pool_size: String(search.pool_size),
    max_per_artist: String(search.max_per_artist),
    min_results: String(search.min_results),
    semantic: String(search.weights.semantic),
    tags: String(search.weights.tags),
    bpm: String(search.weights.bpm),
    energy: String(search.weights.energy),
  }
}

export function TuningSection({ view, onUpdated }: SectionProps) {
  const toast = useToast()
  const [edits, setEdits] = useState<Draft>({})
  const [errors, setErrors] = useState<Draft>({})
  const { pending, error, save } = useSettingsSave(onUpdated)
  const stored = toDraft(view.editable.search)
  const value = (name: string) => edits[name] ?? stored[name]!
  const isPinned = (dotted: string) => view.overridden_by_env.includes(dotted)

  /** The update for the fields that can be changed here (an env-pinned field would be refused). */
  const build = (source: Draft): { update: SettingsUpdate; errors: Draft } => {
    const found: Draft = {}
    const search: NonNullable<SettingsUpdate['search']> = {}
    const weights: Partial<SearchWeights> = {}
    for (const field of INT_FIELDS) {
      if (isPinned(`search.${field.name}`)) continue
      const number = Number(source[field.name])
      if (source[field.name]!.trim() === '' || !Number.isInteger(number) || number < field.min) {
        found[field.name] = t.tuning.invalidInt(field.min)
      } else {
        search[field.name] = number
      }
    }
    for (const name of WEIGHT_FIELDS) {
      if (isPinned(`search.weights.${name}`)) continue
      const number = Number(source[name])
      if (source[name]!.trim() === '' || !Number.isFinite(number) || number < 0) {
        found[name] = t.tuning.invalidWeight
      } else {
        weights[name] = number
      }
    }
    if (Object.keys(weights).length > 0) search.weights = weights
    if (!WEIGHT_FIELDS.some((name) => found[name])) {
      const total = WEIGHT_FIELDS.reduce(
        (sum, name) => sum + Number(isPinned(`search.weights.${name}`) ? stored[name] : source[name]),
        0,
      )
      if (total <= 0) found.semantic = t.tuning.weightsZero
    }
    return { update: { search }, errors: found }
  }

  const submit = async (source: Draft) => {
    const built = build(source)
    setErrors(built.errors)
    if (Object.keys(built.errors).length > 0) return
    if (await save(built.update)) {
      setEdits({})
      toast.info(t.saved)
    }
  }

  const reset = () => {
    const defaults: Draft = {
      pool_size: String(DEFAULT_TUNING.pool_size),
      max_per_artist: String(DEFAULT_TUNING.max_per_artist),
      min_results: String(DEFAULT_TUNING.min_results),
      semantic: String(DEFAULT_TUNING.weights.semantic),
      tags: String(DEFAULT_TUNING.weights.tags),
      bpm: String(DEFAULT_TUNING.weights.bpm),
      energy: String(DEFAULT_TUNING.weights.energy),
    }
    setEdits(defaults)
    void submit(defaults)
  }

  const field = (name: string, dotted: string, label: string, hint?: string) => (
    <TextInput
      key={name}
      label={label}
      hint={isPinned(dotted) ? t.envPinned(envVarName(dotted)) : hint}
      type="number"
      step={INT_FIELDS.some((f) => f.name === name) ? 1 : 0.05}
      min={0}
      value={value(name)}
      readOnly={isPinned(dotted)}
      disabled={isPinned(dotted)}
      error={errors[name]}
      onChange={(event) => setEdits((previous) => ({ ...previous, [name]: event.target.value }))}
    />
  )

  return (
    <section className={styles.section} aria-labelledby="settings-tuning-heading">
      <details className={styles.details}>
        <summary>
          <h2 id="settings-tuning-heading" className={styles.inline}>
            {t.tuning.heading}
          </h2>{' '}
          <span className={styles.note}>({t.tuning.summary})</span>
        </summary>
        <div className={styles.inner}>
          <p className={styles.explain}>{t.tuning.intro}</p>
          <div className={styles.grid}>
            {INT_FIELDS.map((f) => field(f.name, `search.${f.name}`, f.label, f.hint))}
          </div>
          <fieldset className={styles.fieldset}>
            <legend className={styles.legend}>{t.tuning.weights}</legend>
            <p className={styles.note}>{t.tuning.weightsHint}</p>
            <div className={styles.grid}>
              {WEIGHT_FIELDS.map((name) =>
                field(name, `search.weights.${name}`, t.tuning.weightNames[name]),
              )}
            </div>
          </fieldset>
          {error ? (
            <Notice kind="error" title={t.saveFailed}>
              {errorMessage(error)}
            </Notice>
          ) : null}
          <div className={styles.actions}>
            <Button variant="primary" disabled={pending} onClick={() => void submit({ ...stored, ...edits })}>
              {t.tuning.save}
            </Button>
            <Button disabled={pending} onClick={reset}>
              {t.tuning.reset}
            </Button>
          </div>
        </div>
      </details>
    </section>
  )
}
