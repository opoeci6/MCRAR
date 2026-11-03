import { useEffect, useRef, useState } from 'react'
import { fileRoots, isAbort, listFolder } from '../../api'
import type { FileRoots, FolderEntry, FolderListing } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { Button } from '../../ui/Button'
import { Drawer } from '../../ui/Drawer'
import { FolderIcon } from '../../ui/icons'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { libraryStrings } from './strings'
import styles from './FolderBrowser.module.css'

const t = libraryStrings.folderBrowser

/** "C:\", "D:/x", "/home/x" or a network path: where the browser can open a typed path. */
function isAbsolutePath(path: string): boolean {
  return /^([A-Za-z]:[\\/]|\/|\\\\)/.test(path)
}

export interface FolderBrowserProps {
  /** The path typed so far: opened first when it is an absolute path that exists. */
  initialPath?: string
  onChoose: (path: string) => void
  onCancel: () => void
}

/**
 * A side panel that walks the folders of the computer the backend runs on, and hands back the
 * one chosen. It is only useful when the backend is local (the routes answer 403 otherwise).
 */
export function FolderBrowser({ initialPath, onChoose, onCancel }: FolderBrowserProps) {
  const [roots, setRoots] = useState<FileRoots | null>(null)
  const [rootsError, setRootsError] = useState<string | null>(null)
  const [listing, setListing] = useState<FolderListing | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const current = useRef<AbortController | null>(null)
  /** The reason the last folder could not be opened. */
  const failure = useRef<string | null>(null)

  /** Opens a folder. On a failure the last good folder stays and the reason is shown. */
  const open = async (path: string): Promise<boolean> => {
    current.current?.abort()
    const own = new AbortController()
    current.current = own
    setLoading(true)
    try {
      const next = await listFolder(path, { signal: own.signal })
      setListing(next)
      setError(null)
      return true
    } catch (caught) {
      if (!isAbort(caught)) {
        failure.current = errorMessage(caught)
        setError(failure.current)
      }
      return false
    } finally {
      if (current.current === own) setLoading(false)
    }
  }

  // The first folder: the typed path, else home (the first place), else the first drive.
  useEffect(() => {
    const own = new AbortController()
    void (async () => {
      let found: FileRoots | null = null
      try {
        found = await fileRoots({ signal: own.signal })
        setRoots(found)
      } catch (caught) {
        if (isAbort(caught)) return
        setRootsError(errorMessage(caught))
      }
      const typed = initialPath?.trim() ?? ''
      const fallback = found?.places[0]?.path ?? found?.roots[0]?.path
      if (typed && isAbsolutePath(typed) && (await open(typed))) return
      if (own.signal.aborted) return
      const why = failure.current
      if (!fallback) setLoading(false)
      // Home is shown instead, and the reason the typed path was not opened stays on screen.
      else if ((await open(fallback)) && why) setError(why)
    })()
    return () => {
      own.abort()
      current.current?.abort()
    }
    // Runs once, when the panel opens.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const shortcuts = (title: string, entries: FolderEntry[]) =>
    entries.length === 0 ? null : (
      <div className={styles.shortcuts} role="group" aria-label={title}>
        <span className={styles.groupTitle}>{title}</span>
        {entries.map((entry) => (
          <Button key={entry.path} size="sm" onClick={() => void open(entry.path)}>
            {entry.name}
          </Button>
        ))}
      </div>
    )

  return (
    <Drawer
      open
      onClose={onCancel}
      title={t.title}
      width="520px"
      footer={
        <div className={styles.footer}>
          <Button
            variant="primary"
            disabled={listing === null || loading}
            onClick={() => listing && onChoose(listing.path)}
          >
            {t.use}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            {t.cancel}
          </Button>
        </div>
      }
    >
      <div className={styles.body}>
        {rootsError ? (
          <Notice kind="error" title={t.rootsFailed}>
            {rootsError}
          </Notice>
        ) : null}
        {shortcuts(t.places, roots?.places ?? [])}
        {shortcuts(t.drives, roots?.roots ?? [])}
        {error ? (
          <Notice kind="error" title={t.loadFailed}>
            {error}
          </Notice>
        ) : null}
        {listing ? (
          <section className={styles.listing} aria-label={t.current}>
            <div className={styles.pathRow}>
              <Button size="sm" disabled={listing.parent === null || loading} onClick={() => listing.parent && void open(listing.parent)}>
                {t.up}
              </Button>
              <code className={styles.path} title={t.current}>
                {listing.path}
              </code>
            </div>
            {listing.folders.length === 0 ? (
              <p className={styles.muted}>{t.noFolders}</p>
            ) : (
              <ul className={styles.folders} aria-label={t.folders}>
                {listing.folders.map((folder) => (
                  <li key={folder.path}>
                    <button type="button" className={styles.folder} onClick={() => void open(folder.path)}>
                      <FolderIcon aria-hidden="true" />
                      <span>{folder.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {listing.truncated ? <p className={styles.muted}>{t.truncated}</p> : null}
            <p className={styles.muted}>{t.audioFiles(listing.audio_files)}</p>
          </section>
        ) : null}
        {loading ? <Spinner label={t.loading} /> : null}
      </div>
    </Drawer>
  )
}
