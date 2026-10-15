import { useId, useState } from 'react'
import type { RatingValue, SearchItem } from '../../api/types'
import { AddToProjectMenu } from '../../features/projects/AddToProjectMenu'
import { formatTime } from '../../lib/format'
import { usePlayer } from '../../player/playerContext'
import { Button, IconButton } from '../../ui/Button'
import { ChevronDownIcon, PauseIcon, PlayIcon } from '../../ui/icons'
import { LicenseBadge } from '../../ui/LicenseBadge'
import { RatingControl } from '../../ui/RatingControl'
import { ScoreBreakdown } from '../../ui/ScoreBreakdown'
import { strings } from '../../strings'
import { downloadTrack } from './download'
import { searchStrings } from './strings'
import styles from './ResultRow.module.css'

const r = searchStrings.row

const percent = (value: number) => Math.round(Math.min(1, Math.max(0, value)) * 100)

export interface ResultRowProps {
  item: SearchItem
  onOpen: (trackId: number) => void
  onRate: (item: SearchItem, rating: RatingValue | null) => void
}

/** One search result: play, title, licence, facts, tags, the reason, rating and actions. */
export function ResultRow({ item, onOpen, onRate }: ResultRowProps) {
  const player = usePlayer()
  const whyId = useId()
  const [whyOpen, setWhyOpen] = useState(false)
  const title = item.title || r.untitled
  const playing = player.current?.id === item.track_id && player.isPlaying
  const key = item.key ? [item.key, item.mode].filter(Boolean).join(' ') : null
  const energy = item.energy == null ? null : percent(item.energy)

  return (
    <article className={styles.row} aria-label={title}>
      <IconButton
        variant="primary"
        size="lg"
        label={playing ? r.pause(title) : r.play(title)}
        onClick={() =>
          player.play({
            id: item.track_id,
            title: item.title,
            artist: item.artist,
            risk: item.risk,
            license_code: item.license_code,
            attribution: item.attribution_text,
            license_url: item.license_url,
            commercial_license_url: item.commercial_license_url,
            duration_s: item.duration_s,
          })
        }
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </IconButton>

      <div className={styles.main}>
        <div className={styles.titleLine}>
          <button
            type="button"
            className={styles.title}
            title={r.openDetails(title)}
            onClick={() => onOpen(item.track_id)}
          >
            {title}
          </button>
          <span className={styles.artist}>
            {item.artist ? r.byArtist(item.artist) : r.unknownArtist}
          </span>
        </div>

        <div className={styles.facts}>
          <span>{formatTime(item.duration_s)}</span>
          {item.bpm == null ? null : <span>{r.bpm(item.bpm)}</span>}
          {key ? <span>{key}</span> : null}
          {energy == null ? null : (
            <span className={styles.energy} role="img" aria-label={r.energy(energy)}>
              <span className={styles.meter} aria-hidden="true">
                <span className={styles.meterFill} style={{ width: `${energy}%` }} />
              </span>
              <span aria-hidden="true">{energy}</span>
            </span>
          )}
        </div>

        {item.top_tags.length > 0 ? (
          <ul className={styles.tags} aria-label={r.topTags}>
            {item.top_tags.map((tag) => (
              <li key={`${tag.label_set}:${tag.label}`} className={styles.tag}>
                {r.tag(tag.display, percent(tag.score))}
              </li>
            ))}
          </ul>
        ) : null}

        {item.explanation ? <p className={styles.explanation}>{item.explanation}</p> : null}

        <div className={styles.actions}>
          <RatingControl value={item.rating} onChange={(value) => onRate(item, value)} />
          <AddToProjectMenu trackId={item.track_id} trackTitle={item.title ?? ''} />
          {item.download_url ? (
            <Button
              size="sm"
              title={r.downloadHint}
              onClick={() => downloadTrack(item.track_id, item.download_url as string)}
            >
              {r.download}
              <span className="sr-only"> {strings.common.opensInNewTab}</span>
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={whyOpen}
            aria-controls={whyId}
            icon={<ChevronDownIcon className={whyOpen ? styles.chevronOpen : undefined} />}
            onClick={() => setWhyOpen(!whyOpen)}
          >
            {r.why}
          </Button>
        </div>

        {whyOpen ? (
          <div id={whyId} className={styles.why}>
            <ScoreBreakdown breakdown={item.breakdown} />
          </div>
        ) : null}
      </div>

      <LicenseBadge
        risk={item.risk}
        code={item.license_code}
        attribution={item.attribution_text}
        licenseUrl={item.license_url}
        commercialLicenseUrl={item.commercial_license_url}
        placement="bottom-end"
        className={styles.badge}
      />
    </article>
  )
}
