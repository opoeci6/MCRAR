import { useState } from 'react'
import type { FormEvent } from 'react'
import { ingestJamendo } from '../../api'
import type { JamendoIngestRequest, Vocal } from '../../api'
import { Button } from '../../ui/Button'
import { Checkbox } from '../../ui/Toggle'
import { Select } from '../../ui/Select'
import { TextInput } from '../../ui/TextInput'
import { libraryStrings as t } from './strings'
import { StartError } from '../../features/jobs/StartError'
import type { StartProps } from './startJob'
import { useStartJob } from '../../features/jobs/useStartJob'
import styles from './Forms.module.css'

const LIMIT_MIN = 1
const LIMIT_MAX = 1000

/** Splits "ambient, calm" into the tags to send. */
function splitTags(text: string): string[] {
  return text
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
}

export function JamendoForm({ busy, onStarted, onShowRunning }: StartProps) {
  const [tags, setTags] = useState('')
  const [search, setSearch] = useState('')
  const [vocals, setVocals] = useState<Vocal | ''>('')
  const [commercialOnly, setCommercialOnly] = useState(false)
  const [limit, setLimit] = useState('50')
  const [embed, setEmbed] = useState(true)
  const [limitError, setLimitError] = useState<string | undefined>()
  const { pending, error, start } = useStartJob(onStarted)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const count = Number(limit)
    if (!Number.isInteger(count) || count < LIMIT_MIN || count > LIMIT_MAX) {
      setLimitError(t.jamendo.limitInvalid)
      return
    }
    setLimitError(undefined)
    const body: JamendoIngestRequest = {
      tags: splitTags(tags).length > 0 ? splitTags(tags) : undefined,
      search: search.trim() || undefined,
      vocalinstrumental: vocals || undefined,
      commercial_only: commercialOnly,
      limit: count,
      embed,
    }
    void start(() => ingestJamendo(body))
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <p className={styles.intro}>{t.jamendo.intro}</p>
      <TextInput
        label={t.jamendo.tags}
        hint={t.jamendo.tagsHint}
        value={tags}
        onChange={(event) => setTags(event.target.value)}
      />
      <TextInput
        label={t.jamendo.search}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <div className={styles.row}>
        <Select
          label={t.jamendo.vocals}
          value={vocals}
          onChange={(event) => setVocals(event.target.value as Vocal | '')}
        >
          <option value="">{t.jamendo.vocalsAny}</option>
          <option value="instrumental">{t.jamendo.vocalsInstrumental}</option>
          <option value="vocal">{t.jamendo.vocalsVocal}</option>
        </Select>
        <TextInput
          label={t.jamendo.limit}
          hint={t.jamendo.limitHint}
          type="number"
          min={LIMIT_MIN}
          max={LIMIT_MAX}
          inputMode="numeric"
          value={limit}
          error={limitError}
          onChange={(event) => setLimit(event.target.value)}
        />
      </div>
      <div className={styles.checks}>
        <Checkbox
          label={t.jamendo.commercialOnly}
          hint={t.jamendo.commercialOnlyHint}
          checked={commercialOnly}
          onChange={setCommercialOnly}
        />
        <Checkbox
          label={t.jamendo.embed}
          hint={t.jamendo.embedHint}
          checked={embed}
          onChange={setEmbed}
        />
      </div>
      <StartError error={error} onShowRunning={onShowRunning} />
      <div className={styles.submit}>
        <Button type="submit" variant="primary" disabled={busy || pending}>
          {pending ? t.jamendo.starting : t.jamendo.submit}
        </Button>
      </div>
    </form>
  )
}
