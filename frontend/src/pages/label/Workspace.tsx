import { useCallback } from 'react'
import { ApiError } from '../../api/client'
import { getLabelPool, getLabelProgress } from '../../api/endpoints'
import type { LabelPart, LabelProgress, PartProgress, PoolEntry, Vocab } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import type { AsyncState } from '../../api/useAsync'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { EmptyState } from '../../ui/EmptyState'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { ExportLink } from './ExportLink'
import { LabelCard } from './LabelCard'
import { PoolList } from './PoolList'
import { ShortcutsHelp } from './ShortcutsHelp'
import { labelStrings as t } from './strings'
import { useLabelQueue } from './useLabelQueue'
import styles from './LabelPage.module.css'

export interface WorkspaceProps {
  labeller: string
  part: LabelPart
  /** The scenes to choose from come from the vocabulary. */
  vocab: AsyncState<Vocab>
}

/** What the part includes: `A` and `B` each take the tracks that both labellers do. */
function partProgress(progress: LabelProgress, part: LabelPart): PartProgress {
  const { A, B, both } = progress.parts
  const included = part === 'all' ? [A, B, both] : [part === 'A' ? A : B, both]
  return {
    total: included.reduce((sum, p) => sum + p.total, 0),
    labelled: included.reduce((sum, p) => sum + p.labelled, 0),
    skipped: included.reduce((sum, p) => sum + p.skipped, 0),
  }
}

/** The pool track before `position` (the pool is in order), or `undefined` at the start. */
function entryBefore(entries: PoolEntry[], position: number): PoolEntry | undefined {
  let before: PoolEntry | undefined
  for (const entry of entries) if (entry.position < position) before = entry
  return before
}

const noPool = (error: Error | undefined) => error instanceof ApiError && error.status === 409

/**
 * Everything that depends on the name and the part: progress, the track to label and the pool
 * list. The page keys it by both, so a new name or part starts from scratch.
 */
export function Workspace({ labeller, part, vocab }: WorkspaceProps) {
  const progress = useAsync((signal) => getLabelProgress(labeller, { signal }), [labeller])
  const pool = useAsync((signal) => getLabelPool(labeller, part, { signal }), [labeller, part])
  const reloadProgress = progress.reload
  const reloadPool = pool.reload
  const onChanged = useCallback(() => {
    reloadProgress()
    reloadPool()
  }, [reloadProgress, reloadPool])
  const queue = useLabelQueue(labeller, part, onChanged)

  const scenes = vocab.data?.scene ?? []
  const entries = pool.data?.items ?? []
  const slot = queue.view.kind === 'ready' ? queue.view.slot : null
  const at = slot ? entries.findIndex((entry) => entry.track_id === slot.track.id) : -1
  const previous = slot ? entryBefore(entries, slot.position) : undefined

  const content = () => {
    switch (queue.view.kind) {
      case 'loading':
        return <Spinner label={t.loading} />
      case 'nopool':
        return <EmptyState title={t.noPool.title} description={t.noPool.description} />
      case 'error':
        return (
          <Notice
            kind="error"
            title={t.loadFailed}
            action={
              <Button size="sm" onClick={queue.retry}>
                {t.retry}
              </Button>
            }
          >
            {queue.view.message}
          </Notice>
        )
      case 'done':
        return (
          <EmptyState
            title={t.done.title}
            description={`${t.done.description} ${t.done.pickAnother}`}
            action={<ExportLink labeller={labeller} />}
          />
        )
      case 'ready': {
        const current = queue.view.slot
        if (vocab.error) {
          return (
            <Notice
              kind="error"
              title={t.scenesFailed}
              action={
                <Button size="sm" onClick={vocab.reload}>
                  {strings.common.retry}
                </Button>
              }
            >
              {errorMessage(vocab.error)}
            </Notice>
          )
        }
        if (!vocab.data) return <Spinner />
        if (scenes.length === 0) return <Notice kind="warning">{t.noScenes}</Notice>
        return (
          <LabelCard
            key={`${current.track.id}:${current.label?.updated_at ?? 'new'}`}
            slot={current}
            scenes={scenes}
            index={at >= 0 ? { current: at + 1, total: entries.length } : null}
            busy={queue.busy}
            error={queue.error}
            canGoBack={previous !== undefined}
            onSave={(values) => void queue.save(current, values)}
            onSkip={() => void queue.skip(current)}
            onBack={() => {
              if (previous) queue.open(previous)
            }}
            onDelete={() => void queue.remove(current)}
          />
        )
      }
    }
  }

  return (
    <>
      {queue.view.kind === 'nopool' ? null : <Progress progress={progress.data} error={progress.error} part={part} />}
      {content()}
      <ShortcutsHelp />
      {pool.error && !pool.data && !noPool(pool.error) ? (
        <Notice kind="error">
          {t.pool.loadFailed}: {errorMessage(pool.error)}
        </Notice>
      ) : null}
      {entries.length > 0 ? (
        <PoolList
          entries={entries}
          currentTrackId={slot?.track.id ?? null}
          disabled={queue.busy}
          onOpen={queue.open}
        />
      ) : null}
    </>
  )
}

interface ProgressProps {
  progress: LabelProgress | undefined
  error: Error | undefined
  part: LabelPart
}

function Progress({ progress, error, part }: ProgressProps) {
  if (!progress) {
    // The empty state of "no pool yet" already says why there is nothing to show.
    return error && !noPool(error) ? (
      <Notice kind="error">
        {t.progress.loadFailed}: {errorMessage(error)}
      </Notice>
    ) : null
  }
  const counts = partProgress(progress, part)
  const done = counts.labelled + counts.skipped
  return (
    <div className={styles.progress}>
      <progress aria-label={t.progress.label} value={done} max={Math.max(counts.total, 1)} />
      <p>{t.progress.summary(done, counts.total, counts.skipped)}</p>
      {progress.labellers.length > 0 ? (
        <p className={styles.muted}>{t.progress.labellers(progress.labellers.join(', '))}</p>
      ) : null}
    </div>
  )
}
