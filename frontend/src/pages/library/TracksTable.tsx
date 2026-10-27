import { useEffect, useRef, useState } from 'react'
import { listTracks } from '../../api/endpoints'
import { errorMessage, useAsync } from '../../api/useAsync'
import type { Risk, Source, TrackSummary } from '../../api/types'
import { usePersistentState } from '../../app/usePersistentState'
import { AddToProjectMenu } from '../../features/projects/AddToProjectMenu'
import { sourceLabel } from '../../features/track/sourceLabel'
import { TrackDrawer } from '../../features/track/TrackDrawer'
import { formatTime } from '../../lib/format'
import { usePlayer } from '../../player/playerContext'
import { strings } from '../../strings'
import { Button, IconButton } from '../../ui/Button'
import { EmptyState } from '../../ui/EmptyState'
import { PauseIcon, PlayIcon } from '../../ui/icons'
import { LicenseBadge } from '../../ui/LicenseBadge'
import { Notice } from '../../ui/Notice'
import { Select } from '../../ui/Select'
import { Spinner } from '../../ui/Spinner'
import { libraryStrings as t } from './strings'
import styles from './TracksTable.module.css'

export const PAGE_SIZE = 50

export interface TracksTableProps {
  /** Changes when the catalog changed (a job finished): the page is loaded again. */
  refreshKey: number
  /** Changes when the user asks to see the new tracks: goes back to the first page. */
  focusSignal: number
}

export function TracksTable({ refreshKey, focusSignal }: TracksTableProps) {
  const [source, setSource] = usePersistentState<Source | ''>('library.source', '')
  const [risk, setRisk] = usePersistentState<Risk | ''>('library.risk', '')
  const [offset, setOffset] = usePersistentState('library.offset', 0)
  const [openId, setOpenId] = useState<number | null>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (focusSignal === 0) return
    setOffset(0)
    headingRef.current?.focus()
  }, [focusSignal, setOffset])

  const tracks = useAsync(
    (signal) =>
      listTracks(
        { source: source || undefined, risk: risk || undefined, limit: PAGE_SIZE, offset },
        { signal },
      ),
    [source, risk, offset, refreshKey],
  )

  const filtered = source !== '' || risk !== ''
  return (
    <section className={styles.section} aria-labelledby="library-tracks-heading">
      <h2 id="library-tracks-heading" tabIndex={-1} ref={headingRef}>
        {t.tracks.heading}
      </h2>
      <div className={styles.filters}>
        <Select
          label={t.tracks.filterSource}
          value={source}
          onChange={(event) => {
            setSource(event.target.value as Source | '')
            setOffset(0)
          }}
        >
          <option value="">{t.tracks.any}</option>
          {t.tracks.sourceOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        <Select
          label={t.tracks.filterRisk}
          value={risk}
          onChange={(event) => {
            setRisk(event.target.value as Risk | '')
            setOffset(0)
          }}
        >
          <option value="">{t.tracks.any}</option>
          {t.tracks.riskOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>

      {tracks.error && !tracks.data ? (
        <Notice
          kind="error"
          action={
            <Button size="sm" onClick={tracks.reload}>
              {strings.common.retry}
            </Button>
          }
        >
          {t.tracks.loadFailed}: {errorMessage(tracks.error)}
        </Notice>
      ) : !tracks.data ? (
        <Spinner />
      ) : tracks.data.items.length === 0 ? (
        <EmptyState
          title={t.tracks.emptyTitle}
          description={filtered ? t.tracks.emptyFiltered : t.tracks.emptyCatalog}
        />
      ) : (
        <>
          <div className={styles.scroll}>
            <table className={styles.table} aria-label={t.tracks.tableLabel}>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="sr-only">{t.tracks.columns.play}</span>
                  </th>
                  <th scope="col">{t.tracks.columns.title}</th>
                  <th scope="col">{t.tracks.columns.artist}</th>
                  <th scope="col">{t.tracks.columns.source}</th>
                  <th scope="col">{t.tracks.columns.duration}</th>
                  <th scope="col">{t.tracks.columns.license}</th>
                  <th scope="col">
                    <span className="sr-only">{t.tracks.columns.actions}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {tracks.data.items.map((track) => (
                  <TrackRow key={track.id} track={track} onOpen={setOpenId} />
                ))}
              </tbody>
            </table>
          </div>
          <Pager
            offset={tracks.data.offset}
            count={tracks.data.items.length}
            total={tracks.data.total}
            onChange={setOffset}
          />
        </>
      )}
      <TrackDrawer trackId={openId} onClose={() => setOpenId(null)} />
    </section>
  )
}

function TrackRow({ track, onOpen }: { track: TrackSummary; onOpen: (id: number) => void }) {
  const player = usePlayer()
  const title = track.title || t.tracks.untitled
  const active = player.current?.id === track.id && player.isPlaying
  return (
    <tr>
      <td>
        <IconButton
          label={active ? t.tracks.pause(title) : t.tracks.play(title)}
          variant="secondary"
          size="sm"
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
          {active ? <PauseIcon width={14} height={14} /> : <PlayIcon width={14} height={14} />}
        </IconButton>
      </td>
      <td>
        <button
          type="button"
          className={styles.titleButton}
          aria-label={t.tracks.openDetails(title)}
          onClick={() => onOpen(track.id)}
        >
          {title}
        </button>
      </td>
      <td>{track.artist || t.tracks.unknownArtist}</td>
      <td>{sourceLabel(track.source)}</td>
      <td className={styles.number}>{formatTime(track.duration_s)}</td>
      <td>
        <LicenseBadge risk={track.risk} code={track.license_code} />
      </td>
      <td>
        <AddToProjectMenu trackId={track.id} trackTitle={title} />
      </td>
    </tr>
  )
}

interface PagerProps {
  offset: number
  count: number
  total: number
  onChange: (offset: number) => void
}

function Pager({ offset, count, total, onChange }: PagerProps) {
  return (
    <nav className={styles.pager} aria-label={t.tracks.pagination}>
      <span className={styles.range}>{t.tracks.range(offset + 1, offset + count, total)}</span>
      <Button size="sm" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>
        {t.tracks.previous}
      </Button>
      <Button size="sm" disabled={offset + count >= total} onClick={() => onChange(offset + PAGE_SIZE)}>
        {t.tracks.next}
      </Button>
    </nav>
  )
}
