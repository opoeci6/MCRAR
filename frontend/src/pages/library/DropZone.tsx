import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { AUDIO_ACCEPT } from '../../lib/audio'
import { cx } from '../../lib/cx'
import { Button } from '../../ui/Button'
import { FolderIcon } from '../../ui/icons'
import { readDropped } from './readDropped'
import { libraryStrings as t } from './strings'
import styles from './DropZone.module.css'

const c = t.local.copy

/** Whether a drag carries files (and not, say, selected text or a link). */
function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

export interface DropZoneProps {
  /** Nothing is taken while it is set (a copy is running). */
  disabled: boolean
  /** The files chosen or dropped, folders already opened. Any type: the caller picks the audio. */
  onFiles: (files: File[]) => void
}

/**
 * A box that takes dropped files and folders, with a "Choose files" button for the same. Only
 * this box takes a drop (not the whole page), and it lights up while a drag is over it.
 */
export function DropZone({ disabled, onFiles }: DropZoneProps) {
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  // Entering a child fires `dragenter` for it before `dragleave` for the parent, so the box
  // stays lit while the count is above zero.
  const depth = useRef(0)

  const enter = (event: DragEvent) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    if (disabled) return
    depth.current += 1
    setDragging(true)
  }
  const over = (event: DragEvent) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = disabled ? 'none' : 'copy'
  }
  const leave = (event: DragEvent) => {
    if (!hasFiles(event) || depth.current === 0) return
    depth.current -= 1
    if (depth.current === 0) setDragging(false)
  }
  const drop = (event: DragEvent) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    depth.current = 0
    setDragging(false)
    if (disabled) return
    void readDropped(event.dataTransfer).then((files) => {
      if (files.length > 0) onFiles(files)
    })
  }

  const chosen = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? [])
    // So that choosing the same files again still counts as a change.
    event.target.value = ''
    if (files.length > 0) onFiles(files)
  }

  return (
    <div
      className={cx(styles.zone, dragging && styles.dragging, disabled && styles.disabled)}
      onDragEnter={enter}
      onDragOver={over}
      onDragLeave={leave}
      onDrop={drop}
    >
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={AUDIO_ACCEPT}
        aria-label={c.inputLabel}
        onChange={chosen}
      />
      <FolderIcon width={24} height={24} className={styles.icon} />
      <p className={styles.title}>{dragging ? c.dropActive : c.dropTitle}</p>
      <p className={styles.or}>{c.dropOr}</p>
      <Button size="sm" disabled={disabled} onClick={() => input.current?.click()}>
        {c.choose}
      </Button>
    </div>
  )
}
