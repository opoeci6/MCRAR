import { useEffect, useRef, useState } from 'react'
import { listTracks } from '../../api/endpoints'
import { errorMessage, useAsync } from '../../api/useAsync'
import type { Risk, Source, TrackSummary } from '../../api/types'
import { usePersistentState } from '../../app/usePersistentState'
import { AddToProjectMenu } from '../../features/projects/AddToProjectMenu'
import { sourceLabel } from '../../features/track/sourceLabel'
import { TrackDrawer } from '../../features/track/TrackDrawer'
import { cx } from '../../lib/cx'
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
import { TextInput } from '../../ui/TextInput'
import { libraryStrings as t } from './strings'
import styles from './TracksTable.module.css'

export const PAGE_SIZE = 50

/** How long the search box rests before the list is loaded again, so typing is not a request per key. */
export const SEARCH_DELAY_MS = 300

/** The longest search the backend takes. */
const SEARCH_MAX = 200

export interface TracksTableProps {
  /** Changes when the catalog changed (a job finished): the page is loaded again. */
  refreshKey: number
  /** Changes when the user asks to see the new tracks: goes back to the first page. */
  focusSignal: number
  /** A track was removed or its licence changed in the drawer: the page loads the catalog numbers and the list again. */
  onCatalogChanged: () => void
}

export function TracksTable({ refreshKey, focusSignal, onCatalogChanged }: TracksTableProps) {
  const [source, setSource] = usePersistentState<Source | ''>('library.source', '')
  const [risk, setRisk] = usePersistentState<Risk | ''>('library.risk', '')
  const [query, setQuery] = usePersistentState('library.q', '')
  // The search the list is loaded for: `query` once it has rested.
  const [search, setSearch] = useState(() => query.trim())
  const [offset, setOffset] = usePersistentState('library.offset', 0)
  const [openId, setOpenId] = useState<number | null>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (focusSignal === 0) return
    setOffset(0)
    headingRef.current?.focus()
  }, [focusSignal, setOffset])

  useEffect(() => {
    const wanted = query.trim()
    if (wanted === search) return
    const timer = setTimeout(() => {
      setSearch(wanted)
      setOffset(0)
    }, SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [query, search, setOffset])

  const tracks = useAsync(
    (signal) =>
      listTracks(
        {
          source: source || undefined,
          risk: risk || undefined,
          q: search || undefined,
          limit: PAGE_SIZE,
          offset,
        },
        { signal },
      ),
    [source, risk, search, offset, refreshKey],
  )

  const filtered = source !== '' || risk !== '' || search !== ''
  return (
    <section className={styles.section} aria-labelledby="library-tracks-heading">
      <h2 id="library-tracks-heading" tabIndex={-1} ref={headingRef}>
        {t.tracks.heading}
      </h2>
      <div className={styles.filters}>
        <TextInput
          className={styles.search}
          type="search"
          label={t.tracks.filterSearch}
          placeholder={t.tracks.searchPlaceholder}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          maxLength={SEARCH_MAX}
          autoComplete="off"
        />
        <Select
          label={t.tracks.filterSource}
          value={source}
          options={[{ value: '', label: t.tracks.any }, ...t.tracks.sourceOptions]}
          onValueChange={(next) => {
            setSource(next as Source | '')
            setOffset(0)
          }}
        />
        <Select
          label={t.tracks.filterRisk}
          value={risk}
          options={[{ value: '', label: t.tracks.any }, ...t.tracks.riskOptions]}
          onValueChange={(next) => {
            setRisk(next as Risk | '')
            setOffset(0)
          }}
        />
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
                  <th scope="col" className={styles.wideOnly}>
                    {t.tracks.columns.source}
                  </th>
                  <th scope="col" className={styles.wideOnly}>
                    {t.tracks.columns.duration}
                  </th>
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
      <TrackDrawer
        trackId={openId}
        onClose={() => setOpenId(null)}
        onRemoved={() => {
          setOpenId(null)
          // The last track of a page is gone: do not stay on an empty page.
          if (tracks.data?.items.length === 1 && offset > 0) setOffset(Math.max(0, offset - PAGE_SIZE))
          onCatalogChanged()
        }}
        onChanged={onCatalogChanged}
      />
    </section>
  )
}

function TrackRow({ track, onOpen }: { track: TrackSummary; onOpen: (id: number) => void }) {
  const player = usePlayer()
  const title = track.title || t.tracks.untitled
  const active = player.current?.id === track.id && player.isPlaying
  const source = sourceLabel(track.source)
  const length = formatTime(track.duration_s)
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
        <div className={styles.meta}>{t.tracks.meta(source, length)}</div>
      </td>
      <td className={styles.wrap}>{track.artist || t.tracks.unknownArtist}</td>
      <td className={styles.wideOnly}>{source}</td>
      <td className={cx(styles.number, styles.wideOnly)}>{length}</td>
      <td>
        <LicenseBadge risk={track.risk} code={track.license_code} />
      </td>
      <td>
        <AddToProjectMenu trackId={track.id} trackTitle={title} compact />
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
