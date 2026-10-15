import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { ingestLocal } from '../../api'
import { Button } from '../../ui/Button'
import { Checkbox } from '../../ui/Toggle'
import { TextInput } from '../../ui/TextInput'
import { libraryStrings as t } from './strings'
import { StartError } from './startJob'
import type { StartProps } from './startJob'
import { useStartJob } from './useStartJob'
import styles from './Forms.module.css'

export function LocalForm({ busy, onStarted, onShowRunning }: StartProps) {
  const [path, setPath] = useState('')
  const [license, setLicense] = useState('')
  const [embed, setEmbed] = useState(true)
  const suggestionsId = useId()
  const { pending, error, start } = useStartJob(onStarted)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void start(() =>
      ingestLocal({ path: path.trim(), license: license.trim() || undefined, embed }),
    )
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <p className={styles.intro}>{t.local.intro}</p>
      <TextInput
        label={t.local.path}
        hint={t.local.pathHint}
        placeholder={t.local.pathPlaceholder}
        required
        value={path}
        onChange={(event) => setPath(event.target.value)}
      />
      <TextInput
        label={t.local.license}
        hint={t.local.licenseHint}
        list={suggestionsId}
        value={license}
        onChange={(event) => setLicense(event.target.value)}
      />
      <datalist id={suggestionsId}>
        {t.local.licenseSuggestions.map((code) => (
          <option key={code} value={code} />
        ))}
      </datalist>
      <Checkbox label={t.local.embed} hint={t.local.embedHint} checked={embed} onChange={setEmbed} />
      <StartError error={error} onShowRunning={onShowRunning} />
      <div className={styles.submit}>
        <Button type="submit" variant="primary" disabled={busy || pending || path.trim() === ''}>
          {t.local.submit}
        </Button>
      </div>
    </form>
  )
}
