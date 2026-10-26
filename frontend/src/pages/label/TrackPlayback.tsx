import { useEffect, useRef } from 'react'
import { formatTime } from '../../lib/format'
import { usePlayer, usePlayerTime } from '../../player/playerContext'
import type { PlayableTrack } from '../../player/playerContext'
import { Button, IconButton } from '../../ui/Button'
import { PauseIcon, PlayIcon } from '../../ui/icons'
import { labelStrings as t } from './strings'
import styles from './LabelCard.module.css'

/** Where "Jump to" buttons seek to, as a share of the track. */
const JUMPS = [30, 60]

/** The track's title, the play button and the jumps into the track (to hear more than the intro). */
export function TrackPlayback({ track }: { track: PlayableTrack }) {
  const player = usePlayer()
  const time = usePlayerTime()
  const title = track.title || t.card.untitled
  const isCurrent = player.current?.id === track.id
  const playing = isCurrent && player.isPlaying
  const duration = (isCurrent && time.duration > 0 ? time.duration : track.duration_s) ?? 0
  // A jump (in percent) asked for before the audio could take it: done once it plays and its
  // length is known.
  const pending = useRef<number | null>(null)

  useEffect(() => {
    const percent = pending.current
    if (percent === null || !isCurrent || !player.isPlaying || player.isLoading || duration <= 0) return
    pending.current = null
    player.seek((duration * percent) / 100)
  }, [isCurrent, player, duration])

  const jump = (percent: number) => {
    if (isCurrent && player.isPlaying && !player.isLoading && duration > 0) {
      player.seek((duration * percent) / 100)
      return
    }
    pending.current = percent
    if (!isCurrent) player.play(track)
    else if (!player.isPlaying) player.toggle()
  }

  return (
    <div className={styles.playback}>
      <IconButton
        variant="primary"
        size="lg"
        label={playing ? t.card.pause(title) : t.card.play(title)}
        onClick={() => {
          pending.current = null
          player.play(track)
        }}
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </IconButton>
      <div className={styles.trackText}>
        <h2 className={styles.title}>{title}</h2>
        <p className={styles.meta}>
          {track.artist ? t.card.byArtist(track.artist) : t.card.unknownArtist}
          {' · '}
          {formatTime(track.duration_s)}
        </p>
      </div>
      <div className={styles.jumps}>
        {JUMPS.map((percent) => (
          <Button key={percent} size="sm" onClick={() => jump(percent)}>
            {t.card.jump(percent)}
          </Button>
        ))}
      </div>
    </div>
  )
}
