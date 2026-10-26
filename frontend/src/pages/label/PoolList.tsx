import { useState } from 'react'
import type { PoolEntry } from '../../api/types'
import { Button } from '../../ui/Button'
import { releaseFocus } from './shortcuts'
import { labelStrings as t } from './strings'
import styles from './PoolList.module.css'

export interface PoolListProps {
  entries: PoolEntry[]
  /** The track on screen, marked in the list. */
  currentTrackId: number | null
  disabled: boolean
  onOpen: (entry: PoolEntry) => void
}

/** The tracks of the part in order, to revisit one. Closed until asked for. */
export function PoolList({ entries, currentTrackId, disabled, onOpen }: PoolListProps) {
  const [open, setOpen] = useState(false)
  return (
    // The click handler only lets go of the focus (see releaseFocus); the buttons do the rest.
    <section className={styles.section} onClick={releaseFocus}>
      <div>
        <Button size="sm" variant="ghost" aria-expanded={open} aria-controls="label-pool" onClick={() => setOpen(!open)}>
          {t.pool.toggle(entries.length)}
        </Button>
      </div>
      {open ? (
        <ul id="label-pool" className={styles.list} aria-label={t.pool.list}>
          {entries.map((entry, index) => (
            <li key={entry.track_id}>
              <button
                type="button"
                className={styles.row}
                aria-current={entry.track_id === currentTrackId ? 'true' : undefined}
                disabled={disabled}
                onClick={() => onOpen(entry)}
              >
                <span className={styles.number}>{index + 1}</span>
                <span className={styles.title}>{entry.title || t.card.untitled}</span>
                <span className={styles.artist}>{entry.artist || t.card.unknownArtist}</span>
                <span className={styles[entry.status ?? 'todo']}>{t.pool.statusLabels[entry.status ?? 'todo']}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
