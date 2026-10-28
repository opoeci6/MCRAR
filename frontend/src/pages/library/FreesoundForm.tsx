import { useState } from 'react'
import type { FormEvent } from 'react'
import { ingestFreesound } from '../../api'
import type { FreesoundIngestRequest, FreesoundLicense, FreesoundSort } from '../../api'
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
const LIMIT_MAX = 500
const QUERY_MAX = 200
const TAGS_MAX = 10
const DURATION_CEILING_S = 3600
const TAG_PATTERN = /^[a-z0-9_-]+$/

/** In the order the request lists them. */
const LICENSES: FreesoundLicense[] = ['cc0', 'by', 'by-nc', 'sampling+']
const DEFAULT_LICENSES: FreesoundLicense[] = ['cc0', 'by']

/** Splits "Loop, Ambient" into the lowercase tags to send. */
function splitTags(text: string): string[] {
  return text
    .split(',')
    .map((tag) => tag.trim().toLowerCase())
    .filter(Boolean)
}

/** A number of seconds from the text of an input, or null when it is empty or not a number. */
function seconds(text: string): number | null {
  if (text.trim() === '') return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

interface FormErrors {
  search?: string
  tags?: string
  licenses?: string
  durationMin?: string
  durationMax?: string
  limit?: string
}

export function FreesoundForm({ busy, onStarted, onShowRunning }: StartProps) {
  const [search, setSearch] = useState('')
  const [tags, setTags] = useState('')
  const [licenses, setLicenses] = useState<FreesoundLicense[]>(DEFAULT_LICENSES)
  const [durationMin, setDurationMin] = useState('10')
  const [durationMax, setDurationMax] = useState('600')
  const [sort, setSort] = useState<FreesoundSort>('score')
  const [limit, setLimit] = useState('50')
  const [embed, setEmbed] = useState(true)
  const [errors, setErrors] = useState<FormErrors>({})
  const { pending, error, start } = useStartJob(onStarted)

  const toggleLicense = (license: FreesoundLicense, on: boolean) =>
    setLicenses((current) => (on ? [...current, license] : current.filter((item) => item !== license)))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const query = search.trim()
    const tagList = splitTags(tags)
    const minS = seconds(durationMin)
    const maxS = seconds(durationMax)
    const count = Number(limit)

    const found: FormErrors = {}
    if (query.length > QUERY_MAX) found.search = t.freesound.searchTooLong
    else if (query === '' && tagList.length === 0) found.search = t.freesound.needQueryOrTag
    if (!tagList.every((tag) => TAG_PATTERN.test(tag))) found.tags = t.freesound.tagInvalid
    else if (tagList.length > TAGS_MAX) found.tags = t.freesound.tagTooMany
    if (licenses.length === 0) found.licenses = t.freesound.licensesRequired
    if (minS === null || minS < 0) found.durationMin = t.freesound.durationInvalid
    if (maxS === null || maxS < 0) found.durationMax = t.freesound.durationInvalid
    else if (maxS > DURATION_CEILING_S) found.durationMax = t.freesound.durationMaxTooBig
    else if (minS !== null && minS >= 0 && maxS < minS) found.durationMax = t.freesound.durationOrder
    if (!Number.isInteger(count) || count < LIMIT_MIN || count > LIMIT_MAX) {
      found.limit = t.freesound.limitInvalid
    }
    setErrors(found)
    if (Object.keys(found).length > 0 || minS === null || maxS === null) return

    const body: FreesoundIngestRequest = {
      query,
      tags: tagList,
      licenses: LICENSES.filter((license) => licenses.includes(license)),
      duration_min_s: minS,
      duration_max_s: maxS,
      sort,
      limit: count,
      embed,
    }
    void start(() => ingestFreesound(body))
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <p className={styles.intro}>{t.freesound.intro}</p>
      <TextInput
        label={t.freesound.search}
        hint={t.freesound.searchHint}
        value={search}
        error={errors.search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <TextInput
        label={t.freesound.tags}
        hint={t.freesound.tagsHint}
        value={tags}
        error={errors.tags}
        onChange={(event) => setTags(event.target.value)}
      />
      <fieldset className={styles.group}>
        <legend className={styles.legend}>{t.freesound.licenses}</legend>
        <div className={styles.checks}>
          {LICENSES.map((license) => (
            <Checkbox
              key={license}
              label={t.freesound.licenseNames[license]}
              checked={licenses.includes(license)}
              onChange={(on) => toggleLicense(license, on)}
            />
          ))}
        </div>
        {errors.licenses ? <p className={styles.error}>{errors.licenses}</p> : null}
      </fieldset>
      <div className={styles.row}>
        <TextInput
          label={t.freesound.durationMin}
          type="number"
          min={0}
          max={DURATION_CEILING_S}
          inputMode="decimal"
          value={durationMin}
          error={errors.durationMin}
          onChange={(event) => setDurationMin(event.target.value)}
        />
        <TextInput
          label={t.freesound.durationMax}
          type="number"
          min={0}
          max={DURATION_CEILING_S}
          inputMode="decimal"
          value={durationMax}
          error={errors.durationMax}
          onChange={(event) => setDurationMax(event.target.value)}
        />
      </div>
      <div className={styles.row}>
        <Select
          label={t.freesound.sort}
          value={sort}
          onChange={(event) => setSort(event.target.value as FreesoundSort)}
        >
          {t.freesound.sortOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        <TextInput
          label={t.freesound.limit}
          hint={t.freesound.limitHint}
          type="number"
          min={LIMIT_MIN}
          max={LIMIT_MAX}
          inputMode="numeric"
          value={limit}
          error={errors.limit}
          onChange={(event) => setLimit(event.target.value)}
        />
      </div>
      <div className={styles.checks}>
        <Checkbox
          label={t.freesound.embed}
          hint={t.freesound.embedHint}
          checked={embed}
          onChange={setEmbed}
        />
      </div>
      <StartError error={error} onShowRunning={onShowRunning} />
      <div className={styles.submit}>
        <Button type="submit" variant="primary" disabled={busy || pending}>
          {pending ? t.freesound.starting : t.freesound.submit}
        </Button>
      </div>
    </form>
  )
}
