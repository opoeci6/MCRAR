import { formatTime } from '../lib/format'
import { strings } from '../strings'
import { IconButton } from '../ui/Button'
import { PauseIcon, PlayIcon, RepeatIcon, VolumeIcon } from '../ui/icons'
import { LicenseBadge } from '../ui/LicenseBadge'
import { Spinner } from '../ui/Spinner'
import { usePlayer, usePlayerTime } from './playerContext'
import styles from './PlayerBar.module.css'

/** The fixed bar at the bottom. Shows nothing until a track has been played. */
export function PlayerBar() {
  const { current, isPlaying, isLoading, volume, loop, toggle, seek, setVolume, setLoop } = usePlayer()
  const { currentTime, duration } = usePlayerTime()
  if (!current) return null

  const title = current.title || strings.player.unknownTitle
  const artist = current.artist || strings.player.unknownArtist
  const seekable = duration > 0
  const position = Math.min(currentTime, seekable ? duration : currentTime)

  return (
    <section className={styles.bar} aria-label={strings.player.bar}>
      <IconButton
        label={isPlaying ? strings.player.pause : strings.player.play}
        variant="primary"
        size="lg"
        className={styles.playButton}
        onClick={toggle}
      >
        {isPlaying ? <PauseIcon width={18} height={18} /> : <PlayIcon width={18} height={18} />}
      </IconButton>

      <div className={styles.info}>
        <div className={styles.title} title={title}>
          {title}
        </div>
        <div className={styles.artist}>{artist}</div>
      </div>

      <LicenseBadge
        risk={current.risk}
        code={current.license_code}
        attribution={current.attribution}
        licenseUrl={current.license_url}
        commercialLicenseUrl={current.commercial_license_url}
        placement="top-start"
        className={styles.badge}
      />

      <div className={styles.seek}>
        <span className={styles.time}>{formatTime(position)}</span>
        <input
          type="range"
          className={styles.range}
          aria-label={strings.player.seek}
          aria-valuetext={strings.player.seekValue(formatTime(position), formatTime(duration))}
          min={0}
          max={seekable ? duration : 0}
          step={0.5}
          value={seekable ? position : 0}
          disabled={!seekable}
          onChange={(event) => seek(Number(event.target.value))}
        />
        <span className={styles.time}>{formatTime(seekable ? duration : null)}</span>
        {isLoading ? <Spinner size={14} label={strings.player.loading} /> : null}
        <IconButton
          label={strings.player.repeat}
          size="sm"
          className={styles.repeat}
          aria-pressed={loop}
          onClick={() => setLoop(!loop)}
        >
          <RepeatIcon />
        </IconButton>
      </div>

      <div className={styles.volume}>
        <VolumeIcon aria-hidden="true" />
        <input
          type="range"
          className={styles.range}
          aria-label={strings.player.volume}
          min={0}
          max={1}
          step={0.05}
          value={volume}
          onChange={(event) => setVolume(Number(event.target.value))}
        />
      </div>
    </section>
  )
}
