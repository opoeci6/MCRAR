import { useState } from 'react'
import { testLlm } from '../../api/endpoints'
import type { LlmSettings, LlmTestResult } from '../../api/types'
import { errorMessage } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Select } from '../../ui/Select'
import { Spinner } from '../../ui/Spinner'
import { TextInput } from '../../ui/TextInput'
import { Toggle } from '../../ui/Toggle'
import { envVarName } from './env'
import { SecretField } from './SecretField'
import type { SectionProps } from './types'
import { settingsStrings as t } from './strings'
import { useSettingsSave } from './useSettingsSave'
import styles from './Section.module.css'

const TOP_N_MIN = 5
const TOP_N_MAX = 50

/** The fields being edited; a field that is not here shows the saved value. */
interface Draft {
  enabled?: boolean
  preset?: string
  model?: string
  base_url?: string
  /** Text, so a half-typed number is not rejected while typing. */
  rerank_top_n?: string
}

type TestState =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'done'; result: LlmTestResult }
  | { kind: 'failed'; message: string }

function isHttpUrl(value: string): boolean {
  return /^https?:\/\/\S+$/i.test(value)
}

/**
 * The optional LLM: switch, provider, model, advanced settings and the provider's API key. The
 * form is a draft until Save, and "Test connection" tries the draft, so a setup can be checked
 * before it is saved.
 */
export function LlmSection({ view, onUpdated }: SectionProps) {
  const toast = useToast()
  const stored = view.editable.llm
  const presets = view.llm_presets
  const [edits, setEdits] = useState<Draft>({})
  const [topNError, setTopNError] = useState<string | undefined>()
  const [urlError, setUrlError] = useState<string | undefined>()
  const [test, setTest] = useState<TestState>({ kind: 'idle' })
  const { pending, error, save } = useSettingsSave(onUpdated)

  const isPinned = (field: keyof LlmSettings) => view.overridden_by_env.includes(`llm.${field}`)
  const pinnedNote = (field: keyof LlmSettings) => t.envPinned(envVarName(`llm.${field}`))

  const enabled = edits.enabled ?? stored.enabled
  const presetId = edits.preset ?? stored.preset
  const model = edits.model ?? stored.model
  const baseUrl = edits.base_url ?? stored.base_url
  const topN = edits.rerank_top_n ?? String(stored.rerank_top_n)
  const preset = presets.find((p) => p.id === presetId) ?? presets[0]
  if (!preset) return null

  const edit = (change: Draft) => setEdits((previous) => ({ ...previous, ...change }))

  // A model or address that was only the old provider's default (or empty) must not follow the
  // user to another provider; one the user typed themselves stays.
  const changePreset = (id: string) => {
    const next: Draft = { preset: id }
    if (model === '' || model === preset.default_model) next.model = ''
    if (baseUrl === '' || baseUrl === preset.base_url) next.base_url = ''
    edit(next)
    setTest({ kind: 'idle' })
  }

  const submit = async () => {
    const number = Number(topN)
    const badTopN =
      !isPinned('rerank_top_n') &&
      (topN.trim() === '' || !Number.isInteger(number) || number < TOP_N_MIN || number > TOP_N_MAX)
    const badUrl = !isPinned('base_url') && baseUrl.trim() !== '' && !isHttpUrl(baseUrl.trim())
    setTopNError(badTopN ? t.llm.invalidTopN : undefined)
    setUrlError(badUrl ? t.llm.invalidBaseUrl : undefined)
    if (badTopN || badUrl) return
    // A field set by an environment variable would be refused, so it is left out.
    const llm: Partial<LlmSettings> = {}
    if (!isPinned('enabled')) llm.enabled = enabled
    if (!isPinned('preset')) llm.preset = preset.id
    if (!isPinned('model')) llm.model = model.trim()
    if (!isPinned('base_url')) llm.base_url = baseUrl.trim()
    if (!isPinned('rerank_top_n')) llm.rerank_top_n = number
    if (await save({ llm })) {
      setEdits({})
      toast.info(t.saved)
    }
  }

  const runTest = async () => {
    setTest({ kind: 'running' })
    try {
      const result = await testLlm({ preset: preset.id, model: model.trim(), base_url: baseUrl.trim() })
      setTest({ kind: 'done', result })
    } catch (caught) {
      setTest({ kind: 'failed', message: errorMessage(caught) })
    }
  }

  return (
    <section className={styles.section} aria-labelledby="settings-llm-heading">
      <h2 id="settings-llm-heading">{t.llm.heading}</h2>
      <p className={styles.explain}>{t.llm.intro}</p>
      <p className={styles.explain}>{t.llm.privacy}</p>

      <Toggle
        label={t.llm.enable}
        hint={isPinned('enabled') ? pinnedNote('enabled') : t.llm.enableHint}
        checked={enabled}
        disabled={isPinned('enabled') || pending}
        onChange={(checked) => edit({ enabled: checked })}
      />
      <Select
        label={t.llm.provider}
        hint={isPinned('preset') ? pinnedNote('preset') : undefined}
        value={preset.id}
        disabled={isPinned('preset') || pending}
        onChange={(event) => changePreset(event.target.value)}
      >
        {presets.map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ))}
      </Select>
      <TextInput
        label={t.llm.model}
        hint={
          isPinned('model')
            ? pinnedNote('model')
            : preset.default_model
              ? t.llm.modelHint(preset.default_model)
              : t.llm.modelRequired
        }
        placeholder={preset.default_model}
        value={model}
        disabled={isPinned('model') || pending}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => edit({ model: event.target.value })}
      />

      <details className={styles.details}>
        <summary>{t.llm.advanced}</summary>
        <div className={styles.inner}>
          <TextInput
            label={t.llm.baseUrl}
            hint={isPinned('base_url') ? pinnedNote('base_url') : t.llm.baseUrlHint(preset.base_url)}
            placeholder={preset.base_url}
            value={baseUrl}
            disabled={isPinned('base_url') || pending}
            error={urlError}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => edit({ base_url: event.target.value })}
          />
          <TextInput
            label={t.llm.rerankTopN}
            hint={isPinned('rerank_top_n') ? pinnedNote('rerank_top_n') : t.llm.rerankTopNHint}
            type="number"
            step={1}
            min={TOP_N_MIN}
            max={TOP_N_MAX}
            value={topN}
            disabled={isPinned('rerank_top_n') || pending}
            error={topNError}
            onChange={(event) => edit({ rerank_top_n: event.target.value })}
          />
        </div>
      </details>

      {error ? (
        <Notice kind="error" title={t.saveFailed}>
          {errorMessage(error)}
        </Notice>
      ) : null}
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={pending || Object.keys(edits).length === 0}
          onClick={() => void submit()}
        >
          {t.llm.save}
        </Button>
        <Button disabled={test.kind === 'running'} onClick={() => void runTest()}>
          {t.llm.test}
        </Button>
      </div>
      {test.kind === 'running' ? <Spinner label={t.llm.testing} /> : null}
      {test.kind === 'done' && test.result.ok ? (
        <Notice>{t.llm.testOk(test.result.model, (test.result.elapsed_ms / 1000).toFixed(1))}</Notice>
      ) : null}
      {test.kind === 'done' && !test.result.ok ? (
        <Notice kind="error" title={t.llm.testFailedTitle}>
          {test.result.error}
        </Notice>
      ) : null}
      {test.kind === 'failed' ? (
        <Notice kind="error" title={t.llm.testRequestFailed}>
          {test.message}
        </Notice>
      ) : null}

      <SecretField
        key={preset.key_secret}
        name={preset.key_secret}
        title={t.llm.keyTitle(preset.label)}
        body={[t.llm.keyBody(preset.label), preset.key_required ? '' : t.llm.keyOptional]
          .filter(Boolean)
          .join(' ')}
        link={preset.docs_url ? { href: preset.docs_url, label: t.llm.keyLink } : undefined}
        inputLabel={t.llm.keyInput}
        removeWarning={t.llm.keyRemoveWarning}
      />
    </section>
  )
}
