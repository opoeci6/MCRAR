import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { FocusEvent, KeyboardEvent } from 'react'
import { usePlayer, usePlayerTime } from '../../player/playerContext'
import type { PlayableTrack } from '../../player/playerContext'
import { Button } from '../../ui/Button'
import { formatTimestamp, splitTimestamps } from './timestamps'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

export interface NoteEditorProps {
  /** The track the note is about: its timestamps play it, and "Insert current time" follows it. */
  track: PlayableTrack
  trackTitle: string
  /** The note as stored. */
  note: string | null
  /** Stores the note (an empty string clears it). Rejects when it could not be saved. */
  onSave: (note: string) => Promise<void>
}

export const NOTE_MAX = 2000

/** How long after the last keystroke the note is saved. */
export const AUTOSAVE_MS = 800

/** The tallest the field grows before it scrolls. */
const MAX_HEIGHT_PX = 240

type Status = 'idle' | 'saving' | 'saved' | 'failed'

const STATUS_TEXT: Record<Status, string> = {
  idle: '',
  saving: t.noteSaving,
  saved: t.noteSaved,
  failed: t.noteSaveFailed,
}

/**
 * A note on a shortlist entry. Empty, it is an "Add note" button; with text it is read as text
 * whose timestamps (`1:23`) play the track from there; clicking it opens the field. The field
 * saves as you type (after a short pause), when it loses focus and on Ctrl+Enter, and shows
 * "Saving…", "Saved" or "Couldn't save". A failed save keeps what was typed in the field (the
 * caller shows the reason) and the next edit, blur or Ctrl+Enter tries again.
 */
export function NoteEditor({ track, trackTitle, note, onSave }: NoteEditorProps) {
  const player = usePlayer()
  const [draft, setDraft] = useState(note ?? '')
  const [editing, setEditing] = useState(false)
  const [status, setStatus] = useState<Status>('idle')
  const container = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  // The text as typed, kept apart from the state so a save in flight reads the newest value.
  const latest = useRef(draft)
  // What the backend holds (the last save that succeeded).
  const stored = useRef(draft)
  const saving = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const onSaveRef = useRef(onSave)
  // Set when the field must take the focus (and where the caret goes) once it is on screen.
  const focusRequest = useRef<{ caret: number | null } | null>(null)

  useEffect(() => {
    onSaveRef.current = onSave
  })

  /**
   * Saves the latest text. Only one save runs at a time: edits made meanwhile are picked up by
   * the same loop afterwards, so the backend sees the values in order and the last one wins.
   */
  const flush = useCallback(async () => {
    clearTimeout(timer.current)
    timer.current = undefined
    if (saving.current) return
    saving.current = true
    let failed = false
    try {
      while (latest.current !== stored.current) {
        const value = latest.current
        setStatus('saving')
        try {
          await onSaveRef.current(value)
          stored.current = value
        } catch {
          failed = true
          break
        }
      }
    } finally {
      saving.current = false
    }
    if (failed) setStatus('failed')
    else setStatus((current) => (current === 'saving' ? 'saved' : current))
  }, [])

  // Leaving the page (or removing the entry) must not lose what is still waiting for the pause.
  useEffect(
    () => () => {
      if (latest.current !== stored.current) void flush()
      else clearTimeout(timer.current)
    },
    [flush],
  )

  const change = (value: string) => {
    latest.current = value
    setDraft(value)
    if (!saving.current) setStatus('idle')
    clearTimeout(timer.current)
    timer.current = setTimeout(() => void flush(), AUTOSAVE_MS)
  }

  const open = (caret: number | null = null) => {
    focusRequest.current = { caret }
    setEditing(true)
  }

  useLayoutEffect(() => {
    const element = field.current
    if (!element) return
    // Grow with the text; the sizing needs a real layout, so it does nothing in jsdom.
    element.style.height = 'auto'
    if (element.scrollHeight > 0) {
      element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT_PX)}px`
    }
    const request = focusRequest.current
    if (request) {
      focusRequest.current = null
      element.focus()
      const caret = request.caret ?? element.value.length
      element.setSelectionRange(caret, caret)
    }
  }, [draft, editing])

  const insertTime = (seconds: number) => {
    const token = formatTimestamp(seconds)
    const element = editing ? field.current : null
    const value = latest.current
    // Into the field at the caret; from the read view or the button, at the end of the note.
    const start = element ? element.selectionStart : value.length
    const end = element ? element.selectionEnd : value.length
    const separator = !element && value !== '' && !/\s$/.test(value) ? ' ' : ''
    const text = `${separator}${token}`
    const next = value.slice(0, start) + text + value.slice(end)
    if (next.length > NOTE_MAX) return
    open(start + text.length)
    change(next)
  }

  const onBlur = (event: FocusEvent<HTMLTextAreaElement>) => {
    void flush()
    // Moving to a button of this note (Insert current time) keeps the field open.
    if (!container.current?.contains(event.relatedTarget)) setEditing(false)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      void flush()
    }
  }

  const playAt = (seconds: number) => player.play(track, { startAt: seconds })
  const hasText = draft !== ''

  return (
    <div ref={container} className={styles.note}>
      {editing ? (
        <textarea
          ref={field}
          className={styles.noteInput}
          aria-label={t.noteLabel(trackTitle)}
          placeholder={t.notePlaceholder}
          title={t.noteHint}
          value={draft}
          maxLength={NOTE_MAX}
          rows={2}
          onChange={(event) => change(event.target.value)}
          onBlur={onBlur}
          onKeyDown={onKeyDown}
        />
      ) : hasText ? (
        <div
          className={styles.noteRead}
          title={t.noteHint}
          onClick={() => {
            // Selecting text to copy it is not a request to edit.
            if (!window.getSelection()?.toString()) open()
          }}
        >
          {splitTimestamps(draft).map((part, index) =>
            part.seconds === undefined ? (
              part.text
            ) : (
              <button
                key={index}
                type="button"
                className={styles.timestamp}
                aria-label={t.playFrom(part.text)}
                onClick={(event) => {
                  event.stopPropagation()
                  playAt(part.seconds as number)
                }}
              >
                {part.text}
              </button>
            ),
          )}
        </div>
      ) : null}
      <div className={styles.noteBar}>
        {!editing && !hasText ? (
          <Button size="sm" variant="ghost" onClick={() => open()}>
            {t.addNote}
          </Button>
        ) : null}
        {!editing && hasText ? (
          <Button size="sm" variant="ghost" onClick={() => open()}>
            {t.editNote}
          </Button>
        ) : null}
        <InsertTimeButton
          active={player.current?.id === track.id}
          onInsert={insertTime}
        />
        <span className={styles.noteStatus} role="status" aria-live="polite" data-status={status}>
          {STATUS_TEXT[status]}
        </span>
      </div>
    </div>
  )
}

/**
 * "Insert current time", enabled while the entry's track is the one in the player. The position
 * is read here, not in the editor, so only this button follows the playback clock.
 */
function InsertTimeButton({
  active,
  onInsert,
}: {
  active: boolean
  onInsert: (seconds: number) => void
}) {
  if (!active) {
    return (
      <Button size="sm" variant="ghost" disabled title={t.insertTimeHint}>
        {t.insertTime}
      </Button>
    )
  }
  return <LiveInsertTimeButton onInsert={onInsert} />
}

function LiveInsertTimeButton({ onInsert }: { onInsert: (seconds: number) => void }) {
  const { currentTime } = usePlayerTime()
  return (
    <Button
      size="sm"
      variant="ghost"
      title={t.insertTimeHint}
      // Keep the focus (and the caret) in the field while the button is pressed.
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => onInsert(currentTime)}
    >
      {t.insertTime}
    </Button>
  )
}
