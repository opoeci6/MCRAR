import { useState } from 'react'
import { projectCreditsUrl } from '../../api/endpoints'
import type { CreditsFormat } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Select } from '../../ui/Select'
import { Spinner } from '../../ui/Spinner'
import { fetchCreditsText } from './creditsText'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

type PreviewFormat = 'md' | 'txt'
const EXPORTS: CreditsFormat[] = ['txt', 'md', 'json']

/** Download links for the credits of a project, and a text preview that can be copied. */
export function CreditsPanel({ projectId }: { projectId: number }) {
  const [previewing, setPreviewing] = useState(false)
  const [format, setFormat] = useState<PreviewFormat>('md')

  return (
    <section className={styles.credits} aria-labelledby="credits-heading">
      <h3 id="credits-heading">{t.creditsTitle}</h3>
      <p className={styles.muted}>{t.creditsDisclaimer}</p>
      <div className={styles.creditsActions}>
        <div className={styles.exports} role="group" aria-label={t.exportCredits}>
          <span className={styles.exportLabel}>{t.exportCredits}</span>
          {EXPORTS.map((fmt) => (
            <a
              key={fmt}
              className={styles.linkButton}
              href={projectCreditsUrl(projectId, fmt)}
              download
            >
              {t.exportAs[fmt]}
            </a>
          ))}
        </div>
        <Button
          aria-expanded={previewing}
          onClick={() => setPreviewing((open) => !open)}
        >
          {previewing ? t.hidePreview : t.preview}
        </Button>
      </div>
      {previewing ? (
        <>
          <Select
            label={t.previewFormat}
            value={format}
            onChange={(event) => setFormat(event.target.value as PreviewFormat)}
            className={styles.previewFormat}
          >
            <option value="md">{t.previewFormats.md}</option>
            <option value="txt">{t.previewFormats.txt}</option>
          </Select>
          <CreditsPreview key={format} projectId={projectId} format={format} />
        </>
      ) : null}
    </section>
  )
}

function CreditsPreview({ projectId, format }: { projectId: number; format: PreviewFormat }) {
  const text = useAsync((signal) => fetchCreditsText(projectId, format, signal), [projectId, format])
  const [copy, setCopy] = useState<'idle' | 'copied' | 'failed'>('idle')

  const copyText = async (value: string) => {
    try {
      if (!navigator.clipboard) throw new Error('no clipboard')
      await navigator.clipboard.writeText(value)
      setCopy('copied')
    } catch {
      setCopy('failed')
    }
  }

  if (text.error) {
    return (
      <Notice
        kind="error"
        title={t.previewFailed}
        action={
          <Button size="sm" onClick={text.reload}>
            {strings.common.retry}
          </Button>
        }
      >
        {errorMessage(text.error)}
      </Notice>
    )
  }
  if (text.data === undefined) {
    return (
      <div className={styles.center}>
        <Spinner />
      </div>
    )
  }
  return (
    <div className={styles.preview}>
      <pre className={styles.previewText} tabIndex={0} aria-label={t.previewLabel}>
        {text.data}
      </pre>
      <div className={styles.previewActions}>
        <Button size="sm" onClick={() => void copyText(text.data ?? '')}>
          {t.copy}
        </Button>
        <span role="status" className={copy === 'failed' ? styles.copyFailed : styles.muted}>
          {copy === 'copied' ? t.copied : copy === 'failed' ? t.copyFailed : ''}
        </span>
      </div>
    </div>
  )
}
