import { useState, type ReactNode } from 'react'
import { getTrack, trackCreditsUrl } from '../../api/endpoints'
import type { TrackDetail, TrackFeatures, TrackTag } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { formatNumber, formatTime } from '../../lib/format'
import { linkify } from '../../lib/linkify'
import { usePlayer } from '../../player/playerContext'
import { strings } from '../../strings'
import { Button, IconButton } from '../../ui/Button'
import { Drawer } from '../../ui/Drawer'
import { PauseIcon, PlayIcon } from '../../ui/icons'
import { LicenseBadge } from '../../ui/LicenseBadge'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { AddToProjectMenu } from '../projects/AddToProjectMenu'
import { trackFeatureStrings as t } from './strings'
import { TempoValue } from './TempoValue'
import styles from './TrackDrawer.module.css'

export interface TrackDrawerProps {
  /** The track to show, or `null` to keep the drawer closed. */
  trackId: number | null
  onClose: () => void
  /** Offers "Find similar" (search by this track as the reference song) when given. */
  onFindSimilar?: (track: TrackDetail) => void
}

/** How many tags of a label set are shown before "Show all". */
const TAGS_SHOWN = 8

/** The one label of a regression set (valence, arousal): a value in 0 to 1, not a tag name. */
const REGRESSION_LABEL = 'value'

/**
 * The side panel with everything about one track: licence and credit line, audio features, and
 * its tags grouped by label set. Loads `GET /api/tracks/{id}` when opened.
 */
export function TrackDrawer({ trackId, onClose, onFindSimilar }: TrackDrawerProps) {
  const track = useAsync(
    (signal) => (trackId === null ? Promise.resolve(null) : getTrack(trackId, { signal })),
    [trackId],
  )
  const title = track.data ? track.data.title || t.untitled : t.drawerFallbackTitle
  return (
    <Drawer open={trackId !== null} onClose={onClose} title={title} width="520px">
      {track.error ? (
        <Notice kind="error">
          {t.loadFailed}: {errorMessage(track.error)}
        </Notice>
      ) : track.data ? (
        <TrackDetails key={track.data.id} track={track.data} onFindSimilar={onFindSimilar} />
      ) : (
        <Spinner />
      )}
    </Drawer>
  )
}

function TrackDetails({
  track,
  onFindSimilar,
}: {
  track: TrackDetail
  onFindSimilar?: (track: TrackDetail) => void
}) {
  return (
    <div className={styles.body}>
      <Intro track={track} onFindSimilar={onFindSimilar} />
      <LicenseSection track={track} />
      <FeaturesSection features={track.features} track={track} />
      <TagsSection tags={track.tags} />
    </div>
  )
}

function Intro({
  track,
  onFindSimilar,
}: {
  track: TrackDetail
  onFindSimilar?: (track: TrackDetail) => void
}) {
  const player = usePlayer()
  const title = track.title || t.untitled
  const playing = player.current?.id === track.id && player.isPlaying
  const { license } = track
  return (
    <div className={styles.intro}>
      <IconButton
        variant="primary"
        label={playing ? t.pauseLabel(title) : t.playLabel(title)}
        onClick={() =>
          player.play({
            id: track.id,
            title: track.title,
            artist: track.artist,
            risk: license.risk,
            license_code: license.code,
            attribution: license.attribution_text,
            license_url: license.url,
            commercial_license_url: license.commercial_license_url,
            duration_s: track.duration_s,
          })
        }
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </IconButton>
      <div className={styles.introText}>
        <p className={styles.artist}>
          {track.artist ? t.byArtist(track.artist) : t.unknownArtist}
          {track.album ? ` · ${t.album(track.album)}` : ''}
        </p>
        {track.source_url ? (
          <a className={styles.source} href={track.source_url} target="_blank" rel="noreferrer noopener">
            {track.source === 'jamendo' ? t.openOnJamendo : t.openSource}
            <span className="sr-only"> {strings.common.opensInNewTab}</span>
          </a>
        ) : null}
        {track.source === 'local' && track.local_path ? (
          <p className={styles.local} title={t.localFile}>
            {track.local_path}
          </p>
        ) : null}
        <div className={styles.actions}>
          <AddToProjectMenu trackId={track.id} trackTitle={track.title ?? ''} />
          {onFindSimilar ? (
            <Button size="sm" onClick={() => onFindSimilar(track)}>
              {t.findSimilar}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function LicenseSection({ track }: { track: TrackDetail }) {
  const { license } = track
  return (
    <section className={styles.section} aria-labelledby="track-licence-heading">
      <h3 id="track-licence-heading">{t.licence.heading}</h3>
      <LicenseBadge
        risk={license.risk}
        code={license.code}
        attribution={license.attribution_text}
        licenseUrl={license.url}
        commercialLicenseUrl={license.commercial_license_url}
      />
      {license.attribution_text ? (
        <div>
          <div className={styles.hint}>{t.licence.credit}</div>
          <p className={styles.credit}>{linkify(license.attribution_text)}</p>
        </div>
      ) : null}
      <ul className={styles.links}>
        {license.url ? (
          <li>
            <a href={license.url} target="_blank" rel="noreferrer noopener">
              {t.licence.licenceLink}
              <span className="sr-only"> {strings.common.opensInNewTab}</span>
            </a>
          </li>
        ) : null}
        {license.commercial_license_url ? (
          <li>
            <a href={license.commercial_license_url} target="_blank" rel="noreferrer noopener">
              {t.licence.commercialLink}
              <span className="sr-only"> {strings.common.opensInNewTab}</span>
            </a>
          </li>
        ) : null}
        <li>
          <a href={trackCreditsUrl(track.id, 'txt')} download>
            {t.licence.downloadTxt}
          </a>
        </li>
        <li>
          <a href={trackCreditsUrl(track.id, 'md')} download>
            {t.licence.downloadMd}
          </a>
        </li>
      </ul>
      <p className={styles.hint}>{t.licence.disclaimer}</p>
    </section>
  )
}

function FeaturesSection({ features, track }: { features: TrackFeatures | null; track: TrackDetail }) {
  const f = t.features
  const percent = (value: number | null) => (value == null ? null : Math.round(value * 100))
  const bpmConfidence = percent(features?.bpm_confidence ?? null)
  const keyText = features?.key ? [features.key, features.mode].filter(Boolean).join(' ') : null
  const energy = percent(features?.energy ?? null)
  const vocals =
    track.vocal_instrumental === 'vocal'
      ? f.vocal
      : track.vocal_instrumental === 'instrumental'
        ? f.instrumental
        : null
  const tempo =
    features?.bpm == null ? null : (
      <TempoValue
        bpm={features.bpm}
        confidence={features.bpm_confidence}
        suffix={bpmConfidence == null ? null : ` (${f.confidence(bpmConfidence)})`}
      />
    )
  const rows: [string, ReactNode][] = [
    [f.bpm, tempo],
    [f.key, keyText],
    [
      f.loudness,
      features?.loudness_lufs == null ? null : f.loudnessValue(formatNumber(features.loudness_lufs, 1)),
    ],
    [f.energy, energy == null ? null : `${energy}%`],
    [f.duration, track.duration_s == null ? null : formatTime(track.duration_s)],
    [f.vocals, vocals],
  ]
  return (
    <section className={styles.section} aria-labelledby="track-features-heading">
      <h3 id="track-features-heading">{f.heading}</h3>
      {features === null ? <p className={styles.muted}>{f.none}</p> : null}
      <dl className={styles.facts}>
        {rows.map(([label, value]) => (
          <div key={label} className={styles.fact}>
            <dt>{label}</dt>
            <dd>{value ?? <span className={styles.muted}>{f.missing}</span>}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** "dark-ambient" to "Dark Ambient" (the stored label is an id). */
function labelText(label: string): string {
  return label.replace(/[-_]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function groupTags(tags: TrackTag[]): [string, TrackTag[]][] {
  const groups = new Map<string, TrackTag[]>()
  for (const tag of tags) {
    const group = groups.get(tag.label_set) ?? []
    group.push(tag)
    groups.set(tag.label_set, group)
  }
  return Array.from(groups, ([set, items]) => [set, [...items].sort((a, b) => b.prob - a.prob)])
}

function TagsSection({ tags }: { tags: TrackTag[] }) {
  return (
    <section className={styles.section} aria-labelledby="track-tags-heading">
      <h3 id="track-tags-heading">{t.tags.heading}</h3>
      {tags.length === 0 ? null : <p className={styles.hint}>{t.tags.probabilityCaption}</p>}
      {tags.length === 0 ? <p className={styles.muted}>{t.tags.none}</p> : null}
      {groupTags(tags).map(([set, items]) => (
        <TagGroup key={set} set={set} items={items} />
      ))}
    </section>
  )
}

function TagGroup({ set, items }: { set: string; items: TrackTag[] }) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, TAGS_SHOWN)
  return (
    <div className={styles.tagSet}>
      <h4>{t.tags.sets[set] ?? labelText(set)}</h4>
      <ul className={styles.tagList}>
        {shown.map((tag) => (
          <li key={tag.label} className={styles.tag}>
            {tag.label === REGRESSION_LABEL
              ? t.tags.valueChip(Math.round(tag.prob * 100))
              : t.tags.chipLabel(labelText(tag.label), Math.round(tag.prob * 100))}
          </li>
        ))}
      </ul>
      {items.length > TAGS_SHOWN ? (
        <div>
          <Button size="sm" variant="ghost" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? t.tags.showFewer : t.tags.showAll(items.length)}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
