import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  deleteProject,
  deleteProjectItem,
  getProject,
  putProjectItem,
  renameProject,
} from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { ProjectDetail as ProjectDetailData, ShortlistEntry } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { navigate } from '../../app/route'
import { useToast } from '../../app/toastContext'
import { cx } from '../../lib/cx'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { EmptyState } from '../../ui/EmptyState'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { TextInput } from '../../ui/TextInput'
import { CreditsPanel } from './CreditsPanel'
import { formatDate, RISK_ORDER, riskCounts } from './format'
import { ProjectNotFound } from './ProjectNotFound'
import { Shortlist } from './Shortlist'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

export interface ProjectDetailProps {
  projectId: number
  /** Called after anything that changes the project list (name, track count, deletion). */
  onChanged: () => void
}

/** Loads one project; a 404 is "not found" (for a deleted project or a stale link). */
export function ProjectDetail({ projectId, onChanged }: ProjectDetailProps) {
  const project = useAsync((signal) => getProject(projectId, { signal }), [projectId])

  if (project.error) {
    if (project.error instanceof ApiError && project.error.status === 404) return <ProjectNotFound />
    return (
      <Notice
        kind="error"
        title={t.detailLoadFailed}
        action={
          <Button size="sm" onClick={project.reload}>
            {strings.common.retry}
          </Button>
        }
      >
        {errorMessage(project.error)}
      </Notice>
    )
  }
  if (!project.data) {
    return (
      <div className={styles.center}>
        <Spinner />
      </div>
    )
  }
  return <ProjectView initial={project.data} onChanged={onChanged} />
}

function ProjectView({
  initial,
  onChanged,
}: {
  initial: ProjectDetailData
  onChanged: () => void
}) {
  const toast = useToast()
  const [name, setName] = useState(initial.name)
  const [items, setItems] = useState(initial.items)
  const [removed, setRemoved] = useState<ShortlistEntry | null>(null)
  const projectId = initial.id

  const saveNote = async (trackId: number, note: string) => {
    try {
      // Leaving the note out clears it, so an empty note is sent as none.
      const entry = await putProjectItem(projectId, trackId, note === '' ? undefined : note)
      setItems((current) => current.map((item) => (item.track.id === trackId ? entry : item)))
    } catch (error) {
      toast.error(errorMessage(error))
      throw error
    }
  }

  const remove = async (entry: ShortlistEntry) => {
    try {
      await deleteProjectItem(projectId, entry.track.id)
    } catch (error) {
      toast.error(errorMessage(error))
      return
    }
    setItems((current) => current.filter((item) => item.track.id !== entry.track.id))
    setRemoved(entry)
    onChanged()
  }

  const undo = async () => {
    if (!removed) return
    try {
      const entry = await putProjectItem(projectId, removed.track.id, removed.note)
      setItems((current) => [...current, entry])
      setRemoved(null)
      toast.info(t.restored(removed.track.title || t.untitled))
      onChanged()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const counts = riskCounts(items)
  const summary = RISK_ORDER.filter((risk) => counts[risk] > 0)

  return (
    <div className={styles.view}>
      <ProjectHeading
        projectId={projectId}
        name={name}
        createdAt={initial.created_at}
        onRenamed={(next) => {
          setName(next)
          onChanged()
        }}
        onDeleted={() => {
          toast.info(t.deleted(name))
          onChanged()
          navigate('projects')
        }}
      />

      {summary.length > 0 ? (
        <p className={styles.summary}>
          <span className="sr-only">{`${t.riskSummaryLabel}: `}</span>
          {summary.map((risk, index) => (
            <span key={risk}>
              {index > 0 ? ' · ' : ''}
              <span className={cx(styles.count, styles[risk])}>
                {counts[risk]} {t.riskCounts[risk]}
              </span>
            </span>
          ))}
        </p>
      ) : null}
      {counts.red > 0 ? (
        <Notice kind="error" title={t.redWarningTitle}>
          {t.redWarning(counts.red)}
        </Notice>
      ) : null}

      <h3>{t.shortlist}</h3>
      {removed ? (
        <Notice
          action={
            <Button size="sm" onClick={() => void undo()}>
              {t.undo}
            </Button>
          }
        >
          {t.removedNotice(removed.track.title || t.untitled)}
        </Notice>
      ) : null}
      {items.length === 0 ? (
        <EmptyState title={t.emptyShortlistTitle} description={t.emptyShortlistBody} />
      ) : (
        <>
          <Shortlist items={items} onSaveNote={saveNote} onRemove={(entry) => void remove(entry)} />
          <CreditsPanel key={items.map((item) => item.track.id).join(',')} projectId={projectId} />
        </>
      )}
    </div>
  )
}

function ProjectHeading({
  projectId,
  name,
  createdAt,
  onRenamed,
  onDeleted,
}: {
  projectId: number
  name: string
  createdAt: string
  onRenamed: (name: string) => void
  onDeleted: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(name)
  const [error, setError] = useState<string | undefined>(undefined)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const startRename = () => {
    setDraft(name)
    setError(undefined)
    setRenaming(true)
  }

  const submitRename = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = draft.trim()
    if (!trimmed) return
    if (trimmed === name) {
      setRenaming(false)
      return
    }
    setBusy(true)
    try {
      const project = await renameProject(projectId, trimmed)
      onRenamed(project.name)
      setRenaming(false)
    } catch (caught) {
      // A duplicate name is a 422 whose detail says so.
      setError(errorMessage(caught))
    }
    setBusy(false)
  }

  const confirmDelete = async () => {
    setBusy(true)
    try {
      await deleteProject(projectId)
      onDeleted()
    } catch (caught) {
      toast.error(errorMessage(caught))
      setBusy(false)
    }
  }

  return (
    <div className={styles.heading}>
      {renaming ? (
        <form
          className={styles.renameForm}
          onSubmit={(event) => void submitRename(event)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation()
              setRenaming(false)
            }
          }}
        >
          <TextInput
            label={t.renameLabel}
            hint={t.renameHint}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            maxLength={120}
            error={error}
            autoFocus
          />
          <Button type="submit" variant="primary" size="sm" disabled={busy || !draft.trim()}>
            {t.save}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setRenaming(false)} disabled={busy}>
            {t.cancel}
          </Button>
        </form>
      ) : (
        <>
          <div className={styles.headingText}>
            <h2>{name}</h2>
            <p className={styles.muted}>{t.created(formatDate(createdAt))}</p>
          </div>
          {confirming ? (
            <div className={styles.confirm} role="group" aria-label={t.deleteProject}>
              <span>{t.deleteConfirm}</span>
              <Button size="sm" variant="danger" onClick={() => void confirmDelete()} disabled={busy}>
                {t.confirm}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setConfirming(false)}
                disabled={busy}
                autoFocus
              >
                {t.cancel}
              </Button>
            </div>
          ) : (
            <div className={styles.headingActions}>
              <Button size="sm" onClick={startRename}>
                {t.rename}
              </Button>
              <Button size="sm" variant="danger" onClick={() => setConfirming(true)}>
                {t.deleteProject}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
