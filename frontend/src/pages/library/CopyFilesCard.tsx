import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ingestFiles, isAbort, uploadLibraryFile } from '../../api'
import type { IngestFileEntry } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { StartError } from '../../features/jobs/StartError'
import { useStartJob } from '../../features/jobs/useStartJob'
import { isAudioFile } from '../../lib/audio'
import { formatFileSize } from '../../lib/format'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { DropZone } from './DropZone'
import { LicenseEmbedFields } from './LicenseEmbedFields'
import type { StartProps } from './startJob'
import { libraryStrings as t } from './strings'
import formStyles from './Forms.module.css'
import styles from './LocalForm.module.css'

const c = t.local.copy

/** How many of the chosen file names are listed before "and N more". */
const NAMES_SHOWN = 5

const fileKey = (file: File) => `${file.name}|${file.size}|${file.lastModified}`

/** The title of a copied file: its name without the extension. */
function titleOf(name: string): string {
  return name.replace(/\.[^.]+$/, '') || name
}

interface Progress {
  index: number
  total: number
  name: string
}

/**
 * "Copy files into MCRAR": files are chosen or dropped, then sent to the backend one at a time
 * (so progress is real and Cancel stops quickly), and the copies are added to the catalog by one
 * job that the page then shows.
 */
export function CopyFilesCard({ busy, onStarted, onShowRunning }: StartProps) {
  const [files, setFiles] = useState<File[]>([])
  const [skipped, setSkipped] = useState(0)
  const [license, setLicense] = useState('')
  const [embed, setEmbed] = useState(true)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [cancelled, setCancelled] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const headingId = useId()
  const { pending, error, start, reset } = useStartJob(onStarted)
  const uploading = progress !== null

  // Leaving the page stops a copy that is still running.
  useEffect(() => () => controller.current?.abort(), [])

  const addFiles = (chosen: File[]) => {
    const audio = chosen.filter((file) => isAudioFile(file.name))
    setSkipped(chosen.length - audio.length)
    setFiles((current) => {
      const known = new Set(current.map(fileKey))
      return [...current, ...audio.filter((file) => !known.has(fileKey(file)))]
    })
    setProblem(null)
    setCancelled(false)
    reset()
  }

  const clear = () => {
    setFiles([])
    setSkipped(0)
    setProblem(null)
    setCancelled(false)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (files.length === 0) return
    const own = new AbortController()
    controller.current = own
    setProblem(null)
    setCancelled(false)
    reset()

    const entries: IngestFileEntry[] = []
    for (const [position, file] of files.entries()) {
      setProgress({ index: position + 1, total: files.length, name: file.name })
      try {
        const copy = await uploadLibraryFile(file, { signal: own.signal })
        entries.push({ file: copy.file, title: titleOf(file.name) })
      } catch (caught) {
        setProgress(null)
        if (isAbort(caught)) setCancelled(true)
        else setProblem(c.failed(file.name, errorMessage(caught)))
        return
      }
    }
    setProgress(null)

    await start(async () => {
      const started = await ingestFiles({
        files: entries,
        license: license.trim() || undefined,
        embed,
      })
      clear()
      return started
    })
  }

  const total = files.reduce((sum, file) => sum + file.size, 0)
  const shown = files.slice(0, NAMES_SHOWN)
  return (
    <section className={styles.card} aria-labelledby={headingId}>
      <h3 id={headingId}>{c.title}</h3>
      <p className={styles.muted}>{c.body}</p>
      <DropZone disabled={uploading || pending} onFiles={addFiles} />
      {skipped > 0 ? <Notice kind="info">{c.skipped(skipped)}</Notice> : null}
      {files.length > 0 ? (
        <div className={styles.selection}>
          <p className={styles.summary}>{c.selected(files.length, formatFileSize(total))}</p>
          <ul className={styles.names}>
            {shown.map((file) => (
              <li key={fileKey(file)}>{file.name}</li>
            ))}
            {files.length > shown.length ? <li>{c.more(files.length - shown.length)}</li> : null}
          </ul>
          <Button size="sm" variant="ghost" disabled={uploading || pending} onClick={clear}>
            {c.clear}
          </Button>
        </div>
      ) : null}
      <form className={formStyles.form} onSubmit={(event) => void submit(event)}>
        <LicenseEmbedFields
          license={license}
          onLicense={setLicense}
          embed={embed}
          onEmbed={setEmbed}
          licenseHint={c.licenseHint}
        />
        {progress ? (
          <div className={styles.progress} role="status">
            <progress
              aria-label={c.progress}
              max={progress.total}
              value={progress.index - 1}
              className={styles.bar}
            />
            <span>{c.copying(progress.index, progress.total, progress.name)}</span>
          </div>
        ) : null}
        {problem ? (
          <Notice kind="error" title={c.failedTitle}>
            {problem}
          </Notice>
        ) : null}
        {cancelled ? <Notice kind="info">{c.cancelled}</Notice> : null}
        <StartError error={error} onShowRunning={onShowRunning} />
        <div className={formStyles.submit}>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || pending || uploading || files.length === 0}
          >
            {c.submit(files.length)}
          </Button>
          {uploading ? (
            <Button onClick={() => controller.current?.abort()}>{c.cancel}</Button>
          ) : null}
        </div>
      </form>
    </section>
  )
}
