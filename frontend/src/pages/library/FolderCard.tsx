import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { ingestLocal } from '../../api'
import { useBackendStatus } from '../../app/backendStatus'
import { StartError } from '../../features/jobs/StartError'
import { useStartJob } from '../../features/jobs/useStartJob'
import { Button } from '../../ui/Button'
import { TextInput } from '../../ui/TextInput'
import { LicenseEmbedFields } from './LicenseEmbedFields'
import type { StartProps } from './startJob'
import { libraryStrings as t } from './strings'
import { useFolderPicker } from './useFolderPicker'
import formStyles from './Forms.module.css'
import styles from './LocalForm.module.css'

const f = t.local.folder

/** "Use a folder where it is": the backend scans a folder path, and nothing is copied. */
export function FolderCard({ busy, onStarted, onShowRunning }: StartProps) {
  const [path, setPath] = useState('')
  const [license, setLicense] = useState('')
  const [embed, setEmbed] = useState(true)
  const headingId = useId()
  const { pending, error, start } = useStartJob(onStarted)
  const picker = useFolderPicker()
  // Browsing the folders of the computer is only offered when the backend runs on it.
  const canBrowse = useBackendStatus().health?.local_files === true

  const browse = async () => {
    const chosen = await picker.pick(path.trim() || undefined)
    if (chosen) setPath(chosen)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void start(() =>
      ingestLocal({ path: path.trim(), license: license.trim() || undefined, embed }),
    )
  }

  return (
    <section className={styles.card} aria-labelledby={headingId}>
      <h3 id={headingId}>{f.title}</h3>
      <p className={styles.muted}>{f.body}</p>
      <form className={formStyles.form} onSubmit={submit}>
        <div className={styles.pathRow}>
          <TextInput
            className={styles.pathField}
            label={f.path}
            hint={f.pathHint}
            placeholder={f.pathPlaceholder}
            required
            value={path}
            onChange={(event) => setPath(event.target.value)}
          />
          {canBrowse ? (
            <Button className={styles.browse} onClick={() => void browse()}>
              {f.browse}
            </Button>
          ) : null}
        </div>
        <LicenseEmbedFields
          license={license}
          onLicense={setLicense}
          embed={embed}
          onEmbed={setEmbed}
          licenseHint={f.licenseHint}
        />
        <StartError error={error} onShowRunning={onShowRunning} />
        <div className={formStyles.submit}>
          <Button type="submit" variant="primary" disabled={busy || pending || path.trim() === ''}>
            {f.submit}
          </Button>
        </div>
      </form>
      {picker.element}
    </section>
  )
}
