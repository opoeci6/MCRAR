import { useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

export interface NoteEditorProps {
  trackTitle: string
  /** The note as stored. */
  note: string | null
  /** Stores the note (an empty string clears it). Rejects when it could not be saved. */
  onSave: (note: string) => Promise<void>
}

export const NOTE_MAX = 2000

/** A note field that saves when it loses focus or on Ctrl+Enter, and says "Saved". */
export function NoteEditor({ trackTitle, note, onSave }: NoteEditorProps) {
  const [draft, setDraft] = useState(note ?? '')
  const [saved, setSaved] = useState(false)
  // What the backend holds (or is about to): stops a blur right after Ctrl+Enter saving twice.
  const stored = useRef(note ?? '')

  const save = async () => {
    if (draft === stored.current) return
    const previous = stored.current
    stored.current = draft
    try {
      await onSave(draft)
      setSaved(true)
    } catch {
      // The caller shows the error; the draft stays, so the next blur retries.
      stored.current = previous
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      void save()
    }
  }

  return (
    <div className={styles.note}>
      <textarea
        className={styles.noteInput}
        aria-label={t.noteLabel(trackTitle)}
        placeholder={t.notePlaceholder}
        title={t.noteHint}
        value={draft}
        maxLength={NOTE_MAX}
        rows={2}
        onChange={(event) => {
          setDraft(event.target.value)
          setSaved(false)
        }}
        onBlur={() => void save()}
        onKeyDown={onKeyDown}
      />
      <span className={styles.noteStatus} role="status">
        {saved ? t.noteSaved : ''}
      </span>
    </div>
  )
}
