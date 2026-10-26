import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../api/client'
import {
  deleteRating,
  getLlmStatus,
  getVocab,
  putRating,
  rerankSearch,
  search,
  uploadReference,
} from '../../api/endpoints'
import type {
  LlmUse,
  ParsedQuery,
  RatingValue,
  RerankInfo,
  SearchFilters,
  SearchItem,
  SearchReference,
  SearchResponse,
} from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { usePersistentState } from '../../app/usePersistentState'
import { hrefFor } from '../../app/route'
import { useToast } from '../../app/toastContext'
import { InlineJobProgress } from '../../features/jobs/InlineJobProgress'
import { StartError } from '../../features/jobs/StartError'
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
import { QueryReading } from './QueryReading'
import { DEFAULT_REFERENCE_WEIGHT, toApiReference, trackLabel } from './reference'
import type { Reference } from './reference'
import { ReferenceBar } from './ReferenceBar'
import { ResultRow } from './ResultRow'
import { searchStrings as s } from './strings'
import { useJamendoImport } from './useJamendoImport'
import type { ImportOutcome } from './useJamendoImport'
import styles from './SearchPage.module.css'

const PAGE_SIZE = 20

/** What was sent to the search; ratings are filed under this, not under the edited form. */
interface SubmittedQuery {
  text?: string
  filters: SearchFilters
  /** The reference song. Absent in results saved by an older version. */
  reference?: Reference
  /** The reference's share next to a text; only set when the search has both. */
  referenceWeight?: number
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
  /** The best match was weak, so Jamendo may have more. Absent in results saved by an older version. */
  weak?: boolean
  /** The reference song as the backend used it. Absent in results saved by an older version. */
  reference?: SearchReference | null
  /** How the first page's query was read. Absent in results saved by an older version. */
  parsed?: ParsedQuery
  /** What the LLM did with the query; null when it was off. Kept from the first page. */
  llm?: LlmUse | null
  /** Set while the items are the LLM's reranking of the top results. */
  rerank?: RerankInfo | null
  /** The items from before the rerank, for Undo. */
  preRerank?: SearchItem[]
  /** Tracks imported from Jamendo for this search, marked "New". */
  newTrackIds?: number[]
  /** How many tracks the last import for this search added; unset until one has finished. */
  imported?: number | null
}

/** What a re-run after an import carries over to the new results. */
type Imported = Pick<ResultSet, 'newTrackIds' | 'imported'>

/** A reference song that failed to upload or is no longer usable, with the title to show it under. */
type ReferenceProblem = { title: string; message: string }

/** What a search is started with besides the form: a new text, or a changed reference or weight. */
interface SubmitOptions {
  text?: string
  /** `null` runs the search without the reference. */
  reference?: Reference | null
  weight?: number
}

/** The backend lost the uploaded song (404, it restarted) or embeds with another model now (409). */
function isLostUpload(error: unknown, request: SubmittedQuery): error is ApiError {
  return (
    request.reference?.kind === 'upload' &&
    error instanceof ApiError &&
    (error.status === 404 || error.status === 409)
  )
}

type Problem = { kind: 'unavailable' | 'invalid' | 'failed'; message: string }

/** Why a rerank did not happen: no LLM (503), the LLM call failed (502), or anything else. */
type RerankProblem = { kind: 'unconfigured' | 'llm' | 'failed'; message: string }

/** The first page's query reading (and any rerank) carries over to the pages loaded after it. */
type Kept = Pick<ResultSet, 'parsed' | 'llm' | 'rerank' | 'preRerank'>

function toResultSet(
  runId: number,
  request: SubmittedQuery,
  response: SearchResponse,
  previous: SearchItem[],
  imported?: Imported,
  kept?: Kept,
): ResultSet {
  const known = new Set(previous.map((item) => item.track_id))
  const added = response.items.filter((item) => !known.has(item.track_id))
  return {
    runId,
    request,
    items: [...previous, ...added],
    total: response.total_candidates,
    relaxed: response.relaxed,
    notes: response.notes,
    unembedded: response.unembedded_count,
    model: response.model_id,
    elapsedMs: response.elapsed_ms,
    weak: Boolean(request.text) && Boolean(response.match?.weak),
    reference: response.reference ?? null,
    parsed: kept ? kept.parsed : response.parsed,
    llm: kept ? kept.llm : (response.llm ?? null),
    rerank: kept?.rerank,
    // Pages loaded after a rerank also belong to the list that Undo restores.
    preRerank: kept?.preRerank ? [...kept.preRerank, ...added] : undefined,
    ...imported,
  }
}

/** What a reranked list looks like: the LLM's order first, then the other shown items as before. */
function applyRerank(current: ResultSet, response: SearchResponse): ResultSet {
  const ranked = new Set(response.items.map((item) => item.track_id))
  return {
    ...current,
    items: [...response.items, ...current.items.filter((item) => !ranked.has(item.track_id))],
    rerank: response.rerank ?? null,
    // A second rerank still undoes back to the list the search found.
    preRerank: current.preRerank ?? current.items,
  }
}

function rerankProblemFor(error: unknown): RerankProblem {
  if (error instanceof ApiError) {
    if (error.status === 503) return { kind: 'unconfigured', message: error.detail }
    if (error.status === 502) return { kind: 'llm', message: error.detail }
  }
  return { kind: 'failed', message: errorMessage(error) }
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
  const [reference, setReference] = usePersistentState<Reference | null>('search.reference', null)
  const [referenceWeight, setReferenceWeight] = usePersistentState(
    'search.referenceWeight',
    DEFAULT_REFERENCE_WEIGHT,
  )
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
  // Whether the LLM can be used. A failed call leaves it "not ready" without a message.
  const llmStatus = useAsync((signal) => getLlmStatus({ signal }), [])
  const [reranking, setReranking] = useState(false)
  const [rerankProblem, setRerankProblem] = useState<RerankProblem | null>(null)
  const rerankController = useRef<AbortController | null>(null)
  const [uploading, setUploading] = useState(false)
  const [referenceProblem, setReferenceProblem] = useState<ReferenceProblem | null>(null)
  const uploadController = useRef<AbortController | null>(null)
  const chipRef = useRef<HTMLSpanElement>(null)
  // Set by "Find similar": the focus goes to the reference chip once the search is done.
  const focusChip = useRef(false)

  useEffect(
    () => () => {
      controller.current?.abort()
      rerankController.current?.abort()
      uploadController.current?.abort()
    },
    [],
  )

  const resultsRef = useRef(results)
  useEffect(() => {
    resultsRef.current = results
  })

  const run = useCallback(
    async (request: SubmittedQuery, previous: SearchItem[], runId: number, imported?: Imported, refresh = false) => {
      controller.current?.abort()
      const own = new AbortController()
      controller.current = own
      const more = previous.length > 0
      // A new search drops a rerank that is still running; loading more pages does not.
      if (!more) {
        rerankController.current?.abort()
        setReranking(false)
        setRerankProblem(null)
      }
      const kept = more ? resultsRef.current : null
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
            reference: request.reference ? toApiReference(request.reference) : undefined,
            reference_weight: request.referenceWeight,
          },
          { signal: own.signal },
        )
        if (own.signal.aborted) return
        setResults(toResultSet(runId, request, response, previous, imported, kept ?? undefined))
      } catch (caught) {
        if (own.signal.aborted) return
        if (isLostUpload(caught, request)) {
          // The message already says to upload it again.
          setReference(null)
          setReferenceProblem({ title: s.reference.expired, message: caught.detail })
          if (!more && !refresh) setResults(null)
        } else if (more) {
          toast.error(`${s.errors.loadMoreFailed}: ${errorMessage(caught)}`)
        } else if (refresh) {
          // Keep what is on screen: the import itself worked.
          toast.error(`${s.jamendo.rerunFailed}: ${errorMessage(caught)}`)
        } else {
          setResults(null)
          setProblem(problemFor(caught))
        }
      } finally {
        if (controller.current === own) setBusy(null)
      }
    },
    [setReference, setResults, toast],
  )

  const rerank = async () => {
    if (!results?.request.text || results.request.reference) return
    const { runId, request } = results
    rerankController.current?.abort()
    const own = new AbortController()
    rerankController.current = own
    setReranking(true)
    setRerankProblem(null)
    try {
      const response = await rerankSearch(
        { text: request.text, filters: request.filters, limit: PAGE_SIZE, offset: 0, explain: true },
        { signal: own.signal },
      )
      if (own.signal.aborted) return
      setResults((current) => (current && current.runId === runId ? applyRerank(current, response) : current))
    } catch (caught) {
      if (own.signal.aborted) return
      setRerankProblem(rerankProblemFor(caught))
    } finally {
      if (rerankController.current === own) setReranking(false)
    }
  }

  const undoRerank = () =>
    setResults((current) =>
      current?.preRerank
        ? { ...current, items: current.preRerank, rerank: null, preRerank: undefined }
        : current,
    )

  // The import is for the search on screen. When it ends the same search runs again, so the
  // new tracks are ranked with the catalog.
  const onImported = useCallback(
    ({ text: importedText, newTrackIds }: ImportOutcome) => {
      const shown = resultsRef.current
      if (shown && shown.request.text === importedText) {
        runCount.current += 1
        void run(shown.request, [], runBase + runCount.current, { newTrackIds, imported: newTrackIds.length }, true)
      } else if (newTrackIds.length > 0) {
        toast.info(s.jamendo.addedElsewhere(newTrackIds.length, importedText))
      }
    },
    [run, runBase, toast],
  )
  const jamendo = useJamendoImport({
    text: results?.request.text,
    filters: results?.request.filters,
    onFinished: onImported,
  })
  const resetImport = jamendo.reset

  const submit = ({ text: override, reference: chosen = reference, weight = referenceWeight }: SubmitOptions = {}) => {
    const query = (override ?? text).trim()
    if (override !== undefined) setText(override)
    const api = toApiFilters(filters)
    if (filterProblem(filters)) return
    if (!query && Object.keys(api).length === 0 && !chosen) {
      setInputError(s.query.needInput)
      return
    }
    setInputError(null)
    setReferenceProblem(null)
    resetImport()
    runCount.current += 1
    void run(
      {
        text: query || undefined,
        filters: api,
        reference: chosen ?? undefined,
        referenceWeight: chosen && query ? weight : undefined,
      },
      [],
      runBase + runCount.current,
    )
  }
  // The upload finishes later: the search then starts with the text and filters of that moment.
  const submitRef = useRef(submit)
  useEffect(() => {
    submitRef.current = submit
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    submit()
  }

  const upload = async (file: File) => {
    uploadController.current?.abort()
    const own = new AbortController()
    uploadController.current = own
    setUploading(true)
    setReferenceProblem(null)
    try {
      const uploaded = await uploadReference(file, { signal: own.signal })
      if (own.signal.aborted) return
      const chosen: Reference = { kind: 'upload', uploadId: uploaded.upload_id, label: uploaded.filename }
      setReference(chosen)
      submitRef.current({ reference: chosen })
    } catch (caught) {
      if (own.signal.aborted) return
      setReferenceProblem({ title: s.reference.uploadFailed, message: errorMessage(caught) })
    } finally {
      if (uploadController.current === own) setUploading(false)
    }
  }

  const removeReference = () => {
    setReference(null)
    setReferenceProblem(null)
    if (text.trim() || Object.keys(toApiFilters(filters)).length > 0) {
      submit({ reference: null })
    } else {
      // Nothing left to search for: back to the empty page.
      controller.current?.abort()
      resetImport()
      setBusy(null)
      setProblem(null)
      setResults(null)
    }
  }

  const changeWeight = (weight: number) => {
    setReferenceWeight(weight)
    submit({ weight })
  }

  /** Searches for tracks like this one: the track replaces the text, the filters stay. */
  const findSimilar = (trackId: number, title: string, artist: string | null) => {
    const chosen: Reference = { kind: 'track', trackId, label: trackLabel(title, artist) }
    setReference(chosen)
    setDrawerId(null)
    focusChip.current = true
    submit({ text: '', reference: chosen })
  }

  // The drawer gives the focus back to the button that opened it as it closes, so the chip waits
  // for the search to be done.
  useEffect(() => {
    if (focusChip.current && busy === null && reference) {
      focusChip.current = false
      chipRef.current?.focus()
    }
  }, [busy, reference])

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
              preRerank: current.preRerank?.map((it) =>
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
        <ReferenceBar
          reference={reference}
          uploading={uploading}
          problem={referenceProblem}
          onUpload={(file) => void upload(file)}
          onRemove={removeReference}
          chipRef={chipRef}
          mixed={reference !== null && text.trim() !== ''}
          weight={referenceWeight}
          onWeight={changeWeight}
        />
        {results === null && !loading ? (
          <div className={styles.examples}>
            <span className={styles.examplesHeading}>{s.query.examplesHeading}</span>
            {s.query.examples.map((example) => (
              <Chip key={example} selected={false} onClick={() => submit({ text: example })}>
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
          {jamendo.active ? (
            <InlineJobProgress
              key={jamendo.active.job.id}
              job={jamendo.active.job}
              title={s.jamendo.progressTitle(jamendo.active.text)}
              onSettled={jamendo.onSettled}
            />
          ) : null}
          <StartError error={jamendo.error} />
          {jamendo.failure ? (
            <Notice kind="error" title={s.jamendo.failedTitle}>
              {jamendo.failure}
            </Notice>
          ) : null}
          {results ? (
            <ResultsView
              results={results}
              loading={loading}
              canImport={!jamendo.active}
              importPending={jamendo.pending}
              onImport={jamendo.start}
              rerankReady={llmStatus.data?.ready === true}
              rerankCount={llmStatus.data?.rerank_top_n}
              reranking={reranking}
              rerankProblem={rerankProblem}
              onRerank={() => void rerank()}
              onUndoRerank={undoRerank}
              loadingMore={busy === 'more'}
              onLoadMore={() => void run(results.request, results.items, results.runId)}
              onOpen={setDrawerId}
              onRate={rate}
              onFindSimilar={(item) => findSimilar(item.track_id, item.title || s.row.untitled, item.artist)}
            />
          ) : null}
          <p className={styles.disclaimer}>{s.results.disclaimer}</p>
        </section>
      </div>

      <TrackDrawer
        trackId={drawerId}
        onClose={() => setDrawerId(null)}
        onFindSimilar={(track) => findSimilar(track.id, track.title || s.row.untitled, track.artist)}
      />
    </>
  )
}

interface ResultsViewProps {
  results: ResultSet
  loading: boolean
  loadingMore: boolean
  /** No import is running, so one may start (a text search only). */
  canImport: boolean
  importPending: boolean
  onImport: () => void
  /** The LLM is configured and ready, so a rerank may be offered (a text search only). */
  rerankReady: boolean
  /** How many results a rerank reorders, when the backend says. */
  rerankCount?: number
  reranking: boolean
  rerankProblem: RerankProblem | null
  onRerank: () => void
  onUndoRerank: () => void
  onLoadMore: () => void
  onOpen: (trackId: number) => void
  onRate: (item: SearchItem, rating: RatingValue | null) => void
  onFindSimilar: (item: SearchItem) => void
}

function ResultsView({
  results,
  loading,
  loadingMore,
  canImport,
  importPending,
  onImport,
  rerankReady,
  rerankCount,
  reranking,
  rerankProblem,
  onRerank,
  onUndoRerank,
  onLoadMore,
  onOpen,
  onRate,
  onFindSimilar,
}: ResultsViewProps) {
  const { items, total, relaxed, notes, unembedded, model, elapsedMs, weak, newTrackIds, imported } = results
  const { parsed, llm, rerank } = results
  const hasText = Boolean(results.request.text)
  // A search by reference song has no ratings and no rerank.
  const hasReference = Boolean(results.request.reference)
  const fresh = new Set(newTrackIds)
  const importButtonText = importPending ? s.jamendo.starting : s.jamendo.action
  // Weak results: the notice carries the one import button, so the quiet one below is hidden.
  // The LLM calling the list poor counts as weak, even when the similarity score was not.
  const suggestImport =
    hasText && (Boolean(weak) || rerank?.verdict === 'poor') && canImport && imported == null
  const hasMore = items.length < total
  const summary = [
    results.reference ? s.results.similarTo(results.reference.label) : '',
    s.results.summary(items.length, total),
    model,
    s.results.elapsed(elapsedMs),
  ].filter(Boolean)
  return (
    <div className={loading ? styles.stale : undefined}>
      <div className={styles.summaryRow}>
        <p className={styles.summary}>{summary.join(' · ')}</p>
        {rerankReady && hasText && !hasReference && items.length > 0 ? (
          <Button
            size="sm"
            disabled={reranking}
            icon={reranking ? <Spinner size={14} label="" /> : undefined}
            onClick={onRerank}
          >
            {reranking ? s.rerank.pending : s.rerank.action(rerankCount)}
          </Button>
        ) : null}
      </div>
      <div className={styles.notices}>
        {rerank ? (
          <Notice
            action={
              <Button size="sm" onClick={onUndoRerank}>
                {s.rerank.undo}
              </Button>
            }
          >
            {s.rerank.done(rerank.model, rerank.summary)}
          </Notice>
        ) : null}
        {rerankProblem?.kind === 'unconfigured' ? (
          <Notice
            kind="warning"
            title={s.rerank.notConfiguredTitle}
            action={<a href={hrefFor('settings')}>{s.rerank.openSettings}</a>}
          />
        ) : null}
        {rerankProblem?.kind === 'llm' ? (
          <Notice kind="warning" title={s.rerank.failedTitle}>
            {rerankProblem.message}
          </Notice>
        ) : null}
        {rerankProblem?.kind === 'failed' ? (
          <Notice kind="error" title={s.rerank.failed}>
            {rerankProblem.message}
          </Notice>
        ) : null}
        {suggestImport ? (
          <Notice
            kind="warning"
            action={
              <Button size="sm" variant="primary" disabled={importPending} onClick={onImport}>
                {importButtonText}
              </Button>
            }
          >
            {s.jamendo.weakNotice}
          </Notice>
        ) : null}
        {imported != null ? (
          <Notice>{imported > 0 ? s.jamendo.added(imported) : s.jamendo.noneFound}</Notice>
        ) : null}
        {relaxed.length > 0 ? (
          <Notice kind="warning">{s.results.relaxed(relaxed.join('; '))}</Notice>
        ) : null}
        {notes.map((note) => (
          <Notice key={note}>{note}</Notice>
        ))}
        {unembedded > 0 ? <Notice>{s.results.unembedded(unembedded)}</Notice> : null}
      </div>
      {parsed ? <QueryReading parsed={parsed} llm={llm} /> : null}
      {items.length === 0 ? (
        <EmptyState title={s.results.empty} description={s.results.emptyHint} />
      ) : (
        <ul className={styles.list}>
          {items.map((item) => (
            <li key={item.track_id}>
              <ResultRow
                item={item}
                isNew={fresh.has(item.track_id)}
                rateable={!hasReference}
                onOpen={onOpen}
                onRate={onRate}
                onFindSimilar={onFindSimilar}
              />
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
      {hasText && canImport && !suggestImport ? (
        <div className={styles.more}>
          <Button variant="ghost" disabled={importPending} onClick={onImport}>
            {importButtonText}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
