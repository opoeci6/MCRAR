import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { deleteRating, getVocab, putRating, search } from '../../api/endpoints'
import type { RatingValue, SearchFilters, SearchItem, SearchResponse } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { usePersistentState } from '../../app/usePersistentState'
import { useToast } from '../../app/toastContext'
import { TrackDrawer } from '../../features/track/TrackDrawer'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { EmptyState } from '../../ui/EmptyState'
import { Notice } from '../../ui/Notice'
import { PageHeader } from '../../ui/PageHeader'
import { Spinner } from '../../ui/Spinner'
import { TextInput } from '../../ui/TextInput'
import { activeFilterCount, DEFAULT_FILTERS, filterProblem, toApiFilters } from './filters'
import type { FilterState } from './filters'
import { FiltersPanel } from './FiltersPanel'
import { ResultRow } from './ResultRow'
import { searchStrings as s } from './strings'
import styles from './SearchPage.module.css'

const PAGE_SIZE = 20

/** What was sent to the search; ratings are filed under this, not under the edited form. */
interface SubmittedQuery {
  text?: string
  filters: SearchFilters
}

interface ResultSet {
  /** Tells apart the searches of one session, so a late rollback cannot touch newer results. */
  runId: number
  request: SubmittedQuery
  items: SearchItem[]
  total: number
  relaxed: string[]
  notes: string[]
  unembedded: number
  model: string
  elapsedMs: number
}

type Problem = { kind: 'unavailable' | 'invalid' | 'failed'; message: string }

function toResultSet(
  runId: number,
  request: SubmittedQuery,
  response: SearchResponse,
  previous: SearchItem[],
): ResultSet {
  const known = new Set(previous.map((item) => item.track_id))
  return {
    runId,
    request,
    items: [...previous, ...response.items.filter((item) => !known.has(item.track_id))],
    total: response.total_candidates,
    relaxed: response.relaxed,
    notes: response.notes,
    unembedded: response.unembedded_count,
    model: response.model_id,
    elapsedMs: response.elapsed_ms,
  }
}

function problemFor(error: unknown): Problem | null {
  if (error instanceof ApiError) {
    if (error.status === 0) return null // the offline banner and toast already say so
    const specific = error.detail !== strings.errors.generic(error.status) ? error.detail : ''
    if (error.status === 503) {
      return { kind: 'unavailable', message: specific || s.errors.unavailable }
    }
    if (error.status === 422) return { kind: 'invalid', message: specific }
  }
  return { kind: 'failed', message: errorMessage(error) }
}

export default function SearchPage() {
  const toast = useToast()
  const [text, setText] = usePersistentState('search.text', '')
  const [filters, setFilters] = usePersistentState<FilterState>('search.filters', DEFAULT_FILTERS)
  const [results, setResults] = usePersistentState<ResultSet | null>('search.results', null)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [busy, setBusy] = useState<'search' | 'more' | null>(null)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [inputError, setInputError] = useState<string | null>(null)
  const [drawerId, setDrawerId] = useState<number | null>(null)
  const controller = useRef<AbortController | null>(null)
  const [runBase] = useState(() => Date.now())
  const runCount = useRef(0)
  const vocab = useAsync((signal) => getVocab({ signal }), [])

  useEffect(() => () => controller.current?.abort(), [])

  const run = useCallback(
    async (request: SubmittedQuery, previous: SearchItem[], runId: number) => {
      controller.current?.abort()
      const own = new AbortController()
      controller.current = own
      const more = previous.length > 0
      setBusy(more ? 'more' : 'search')
      setProblem(null)
      try {
        const response = await search(
          {
            text: request.text,
            filters: request.filters,
            limit: PAGE_SIZE,
            offset: previous.length,
            explain: true,
          },
          { signal: own.signal },
        )
        if (own.signal.aborted) return
        setResults(toResultSet(runId, request, response, previous))
      } catch (caught) {
        if (own.signal.aborted) return
        if (more) {
          toast.error(`${s.errors.loadMoreFailed}: ${errorMessage(caught)}`)
        } else {
          setResults(null)
          setProblem(problemFor(caught))
        }
      } finally {
        if (controller.current === own) setBusy(null)
      }
    },
    [setResults, toast],
  )

  const submit = (override?: string) => {
    const query = (override ?? text).trim()
    if (override !== undefined) setText(override)
    const api = toApiFilters(filters)
    if (filterProblem(filters)) return
    if (!query && Object.keys(api).length === 0) {
      setInputError(s.query.needInput)
      return
    }
    setInputError(null)
    runCount.current += 1
    void run({ text: query || undefined, filters: api }, [], runBase + runCount.current)
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    submit()
  }

  const rate = (item: SearchItem, next: RatingValue | null) => {
    if (!results) return
    const { runId, request } = results
    const before = item.rating
    const apply = (value: RatingValue | null) =>
      setResults((current) =>
        current && current.runId === runId
          ? {
              ...current,
              items: current.items.map((it) =>
                it.track_id === item.track_id ? { ...it, rating: value } : it,
              ),
            }
          : current,
      )
    apply(next)
    const target = { text: request.text, filters: request.filters, track_id: item.track_id }
    const call =
      next === null ? deleteRating(target) : putRating({ ...target, rating: next })
    call.catch((caught: unknown) => {
      apply(before)
      toast.error(`${s.errors.ratingFailed}: ${errorMessage(caught)}`)
    })
  }

  const loading = busy === 'search'
  const filterCount = activeFilterCount(filters)

  return (
    <>
      <PageHeader title={s.title} description={s.description} />

      <form className={styles.queryBar} role="search" onSubmit={onSubmit}>
        <div className={styles.queryRow}>
          <TextInput
            className={styles.queryField}
            label={s.query.label}
            hideLabel
            placeholder={s.query.placeholder}
            value={text}
            error={inputError ?? (problem?.kind === 'invalid' ? problem.message : undefined)}
            onChange={(event) => setText(event.target.value)}
            autoComplete="off"
            maxLength={1000}
          />
          <Button type="submit" variant="primary" size="lg" disabled={loading}>
            {loading ? s.query.searching : s.query.submit}
          </Button>
        </div>
        {results === null && !loading ? (
          <div className={styles.examples}>
            <span className={styles.examplesHeading}>{s.query.examplesHeading}</span>
            {s.query.examples.map((example) => (
              <Chip key={example} selected={false} onClick={() => submit(example)}>
                {example}
              </Chip>
            ))}
          </div>
        ) : null}
      </form>

      <div className={styles.layout}>
        <aside className={styles.filters} aria-label={s.filters.heading}>
          <Button
            className={styles.filtersToggle}
            aria-expanded={filtersOpen}
            aria-controls="search-filters"
            onClick={() => setFiltersOpen(!filtersOpen)}
          >
            {filterCount > 0 ? s.filters.toggleCount(filterCount) : s.filters.toggle}
          </Button>
          <div
            id="search-filters"
            className={filtersOpen ? styles.filtersBody : `${styles.filtersBody} ${styles.collapsed}`}
          >
            <FiltersPanel
              value={filters}
              onChange={setFilters}
              vocab={vocab.data}
              vocabFailed={Boolean(vocab.error)}
            />
          </div>
        </aside>

        <section className={styles.results} aria-label={s.results.heading} aria-busy={loading}>
          {loading && results === null ? <Spinner label={s.query.searching} /> : null}
          {problem && problem.kind !== 'invalid' ? (
            <Notice
              kind="error"
              title={problem.kind === 'unavailable' ? s.errors.unavailableTitle : s.errors.failed}
            >
              {problem.message}
            </Notice>
          ) : null}
          {results ? (
            <ResultsView
              results={results}
              loading={loading}
              loadingMore={busy === 'more'}
              onLoadMore={() => void run(results.request, results.items, results.runId)}
              onOpen={setDrawerId}
              onRate={rate}
            />
          ) : null}
          <p className={styles.disclaimer}>{s.results.disclaimer}</p>
        </section>
      </div>

      <TrackDrawer trackId={drawerId} onClose={() => setDrawerId(null)} />
    </>
  )
}

interface ResultsViewProps {
  results: ResultSet
  loading: boolean
  loadingMore: boolean
  onLoadMore: () => void
  onOpen: (trackId: number) => void
  onRate: (item: SearchItem, rating: RatingValue | null) => void
}

function ResultsView({ results, loading, loadingMore, onLoadMore, onOpen, onRate }: ResultsViewProps) {
  const { items, total, relaxed, notes, unembedded, model, elapsedMs } = results
  const hasMore = items.length < total
  const summary = [
    s.results.summary(items.length, total),
    model,
    s.results.elapsed(elapsedMs),
  ].filter(Boolean)
  return (
    <div className={loading ? styles.stale : undefined}>
      <p className={styles.summary}>{summary.join(' · ')}</p>
      <div className={styles.notices}>
        {relaxed.length > 0 ? (
          <Notice kind="warning">{s.results.relaxed(relaxed.join('; '))}</Notice>
        ) : null}
        {notes.map((note) => (
          <Notice key={note}>{note}</Notice>
        ))}
        {unembedded > 0 ? <Notice>{s.results.unembedded(unembedded)}</Notice> : null}
      </div>
      {items.length === 0 ? (
        <EmptyState title={s.results.empty} description={s.results.emptyHint} />
      ) : (
        <ul className={styles.list}>
          {items.map((item) => (
            <li key={item.track_id}>
              <ResultRow item={item} onOpen={onOpen} onRate={onRate} />
            </li>
          ))}
        </ul>
      )}
      {hasMore ? (
        <div className={styles.more}>
          <Button disabled={loadingMore} onClick={onLoadMore}>
            {loadingMore ? s.results.loadingMore : s.results.loadMore}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
