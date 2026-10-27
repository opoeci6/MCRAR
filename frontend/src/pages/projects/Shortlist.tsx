import type { ShortlistEntry } from '../../api/types'
import { TrackActions } from '../../features/track/TrackActions'
import { usePlayer } from '../../player/playerContext'
import type { PlayableTrack } from '../../player/playerContext'
import { Button, IconButton } from '../../ui/Button'
import { PauseIcon, PlayIcon, TrashIcon } from '../../ui/icons'
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
  /** Opens the details of a track (the track drawer). */
  onOpen: (trackId: number) => void
  onFindSimilar: (trackId: number) => void
}

function playable(track: ShortlistEntry['track']): PlayableTrack {
  return {
    id: track.id,
    title: track.title,
    artist: track.artist,
    risk: track.risk,
    license_code: track.license_code,
    attribution: track.attribution_text,
    license_url: track.license_url,
    commercial_license_url: track.commercial_license_url,
    duration_s: track.duration_s,
  }
}

/** The tracks of a project, each with its licence, actions and a note. */
export function Shortlist({ items, onSaveNote, onRemove, onOpen, onFindSimilar }: ShortlistProps) {
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
              onClick={() => player.play(playable(track))}
            >
              {active ? <PauseIcon /> : <PlayIcon />}
            </IconButton>
            <div className={styles.trackText}>
              <button
                type="button"
                className={styles.trackTitle}
                title={t.openDetails(title)}
                onClick={() => onOpen(track.id)}
              >
                {title}
              </button>
              <div className={styles.trackArtist}>{track.artist || t.unknownArtist}</div>
            </div>
            <LicenseBadge
              risk={track.risk}
              code={track.license_code}
              attribution={track.attribution_text}
              licenseUrl={track.license_url}
              commercialLicenseUrl={track.commercial_license_url}
              placement="bottom-end"
            />
            <span className={styles.trackMeta} title={t.duration}>
              {formatTime(track.duration_s)}
            </span>
            <span className={styles.trackMeta}>{t.added(formatDate(entry.added_at))}</span>
            <div className={styles.actions}>
              <TrackActions
                trackId={track.id}
                title={title}
                downloadUrl={track.download_url}
                onFindSimilar={() => onFindSimilar(track.id)}
              />
              <Button
                size="sm"
                icon={<TrashIcon />}
                aria-label={t.remove(title)}
                onClick={() => onRemove(entry)}
              >
                {t.removeLabel}
              </Button>
            </div>
            <NoteEditor
              track={playable(track)}
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
