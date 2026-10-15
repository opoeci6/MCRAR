import type { ShortlistEntry } from '../../api/types'
import { usePlayer } from '../../player/playerContext'
import { IconButton } from '../../ui/Button'
import { CloseIcon, PauseIcon, PlayIcon } from '../../ui/icons'
import { LicenseBadge } from '../../ui/LicenseBadge'
import { formatTime } from '../../lib/format'
import { formatDate } from './format'
import { NoteEditor } from './NoteEditor'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

export interface ShortlistProps {
  items: ShortlistEntry[]
  onSaveNote: (trackId: number, note: string) => Promise<void>
  onRemove: (entry: ShortlistEntry) => void
}

/** The tracks of a project, each with its licence, a note and a remove button. */
export function Shortlist({ items, onSaveNote, onRemove }: ShortlistProps) {
  const player = usePlayer()

  return (
    <ul className={styles.shortlist}>
      {items.map((entry) => {
        const { track } = entry
        const title = track.title || t.untitled
        const active = player.current?.id === track.id && player.isPlaying
        return (
          <li key={track.id} className={styles.row}>
            <IconButton
              label={active ? t.pause(title) : t.play(title)}
              variant="secondary"
              onClick={() =>
                player.play({
                  id: track.id,
                  title: track.title,
                  artist: track.artist,
                  risk: track.risk,
                  license_code: track.license_code,
                  duration_s: track.duration_s,
                })
              }
            >
              {active ? <PauseIcon /> : <PlayIcon />}
            </IconButton>
            <div className={styles.trackText}>
              <div className={styles.trackTitle}>{title}</div>
              <div className={styles.trackArtist}>{track.artist || t.unknownArtist}</div>
            </div>
            <LicenseBadge risk={track.risk} code={track.license_code} />
            <span className={styles.trackMeta} title={t.duration}>
              {formatTime(track.duration_s)}
            </span>
            <span className={styles.trackMeta}>{t.added(formatDate(entry.added_at))}</span>
            <IconButton label={t.remove(title)} size="sm" onClick={() => onRemove(entry)}>
              <CloseIcon width={14} height={14} />
            </IconButton>
            <NoteEditor
              trackTitle={title}
              note={entry.note}
              onSave={(note) => onSaveNote(track.id, note)}
            />
          </li>
        )
      })}
    </ul>
  )
}
