import { useState } from 'react'
import type { FormEvent } from 'react'
import { createProject } from '../../api/endpoints'
import type { Project } from '../../api/types'
import { errorMessage } from '../../api/useAsync'
import type { AsyncState } from '../../api/useAsync'
import { hrefFor, navigate } from '../../app/route'
import { cx } from '../../lib/cx'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { PlusIcon } from '../../ui/icons'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { TextInput } from '../../ui/TextInput'
import { formatDate } from './format'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

export interface ProjectListProps {
  projects: AsyncState<Project[]>
  selectedId: number | null
}

/** The left pane: every project, and the "New project" form. */
export function ProjectList({ projects, selectedId }: ProjectListProps) {
  const [creating, setCreating] = useState(false)

  return (
    <aside className={styles.list} aria-label={t.listLabel}>
      <div className={styles.listHeader}>
        <h2 className={styles.listTitle}>{t.listLabel}</h2>
        {creating ? null : (
          <Button size="sm" icon={<PlusIcon />} onClick={() => setCreating(true)}>
            {t.newProject}
          </Button>
        )}
      </div>
      {creating ? (
        <NewProjectForm
          onCancel={() => setCreating(false)}
          onCreated={(project) => {
            setCreating(false)
            projects.reload()
            navigate('projects', [project.id])
          }}
        />
      ) : null}
      {projects.loading && !projects.data ? (
        <div className={styles.center}>
          <Spinner />
        </div>
      ) : null}
      {projects.error ? (
        <Notice
          kind="error"
          title={t.loadFailed}
          action={
            <Button size="sm" onClick={projects.reload}>
              {strings.common.retry}
            </Button>
          }
        >
          {errorMessage(projects.error)}
        </Notice>
      ) : null}
      {projects.data && projects.data.length === 0 ? (
        <p className={styles.muted}>{t.noProjectsBody}</p>
      ) : null}
      {projects.data && projects.data.length > 0 ? (
        <ul className={styles.items}>
          {projects.data.map((project) => (
            <li key={project.id}>
              <a
                className={cx(styles.projectLink, project.id === selectedId && styles.selected)}
                href={hrefFor('projects', [project.id])}
                aria-current={project.id === selectedId ? 'page' : undefined}
              >
                <span className={styles.projectName}>{project.name}</span>
                <span className={styles.projectMeta}>
                  {t.trackCount(project.item_count)} · {t.created(formatDate(project.created_at))}
                </span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </aside>
  )
}

function NewProjectForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void
  onCreated: (project: Project) => void
}) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | undefined>(undefined)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    setError(undefined)
    let project: Project
    try {
      project = await createProject(trimmed)
    } catch (caught) {
      // A duplicate name is a 422 whose detail says so.
      setError(errorMessage(caught))
      setBusy(false)
      return
    }
    onCreated(project)
  }

  return (
    <form
      className={styles.newForm}
      onSubmit={(event) => void submit(event)}
      onKeyDown={(event) => {
        if (event.key === 'Escape') onCancel()
      }}
    >
      <TextInput
        label={t.projectName}
        value={name}
        onChange={(event) => setName(event.target.value)}
        maxLength={120}
        error={error}
        autoFocus
      />
      <div className={styles.formActions}>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          {t.cancel}
        </Button>
        <Button type="submit" size="sm" variant="primary" disabled={busy || !name.trim()}>
          {t.createProject}
        </Button>
      </div>
    </form>
  )
}
