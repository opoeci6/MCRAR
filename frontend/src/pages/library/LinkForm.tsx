import { useState } from 'react'
import type { FormEvent } from 'react'
import { ingestLinks } from '../../api'
import { Button } from '../../ui/Button'
import { Checkbox } from '../../ui/Toggle'
import { TextArea } from '../../ui/TextArea'
import { libraryStrings as t } from './strings'
import { StartError } from '../../features/jobs/StartError'
import type { StartProps } from './startJob'
import { useStartJob } from '../../features/jobs/useStartJob'
import styles from './Forms.module.css'

/** The longest text the backend takes. */
const TEXT_MAX = 10000

/** Adds the tracks that pasted Jamendo and Freesound links point to. The backend reads the links. */
export function LinkForm({ busy, onStarted, onShowRunning }: StartProps) {
  const [text, setText] = useState('')
  const [embed, setEmbed] = useState(true)
  const { pending, error, start } = useStartJob(onStarted)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (text.trim() === '') return
    void start(() => ingestLinks({ text, embed }))
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      <p className={styles.intro}>{t.links.intro}</p>
      <TextArea
        label={t.links.label}
        hint={t.links.hint}
        placeholder={t.links.placeholder}
        value={text}
        rows={5}
        maxLength={TEXT_MAX}
        spellCheck={false}
        onChange={(event) => setText(event.target.value)}
      />
      <div className={styles.checks}>
        <Checkbox label={t.links.embed} hint={t.links.embedHint} checked={embed} onChange={setEmbed} />
      </div>
      <StartError error={error} onShowRunning={onShowRunning} />
      <div className={styles.submit}>
        <Button type="submit" variant="primary" disabled={busy || pending || text.trim() === ''}>
          {pending ? t.links.starting : t.links.submit}
        </Button>
      </div>
    </form>
  )
}
