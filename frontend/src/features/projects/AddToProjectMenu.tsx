import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  createProject,
  deleteProjectItem,
  listProjectItems,
  listProjects,
  putProjectItem,
} from '../../api/endpoints'
import type { Project } from '../../api/types'
import { errorMessage, useAsync } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { hrefFor } from '../../app/route'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { CheckIcon, PlusIcon } from '../../ui/icons'
import { Notice } from '../../ui/Notice'
import { Popover } from '../../ui/Popover'
import { Spinner } from '../../ui/Spinner'
import { TextInput } from '../../ui/TextInput'
import { markProjectUsed, sortByRecent } from './recent'
import { projectsFeatureStrings as t } from './strings'
import styles from './AddToProjectMenu.module.css'

export interface AddToProjectMenuProps {
  trackId: number
  trackTitle: string
}

/**
 * A button that opens the list of projects; picking one adds the track to its shortlist, and
 * picking one that already has the track (marked with a check) takes it off again.
 */
export function AddToProjectMenu({ trackId, trackTitle }: AddToProjectMenuProps) {
  return (
    <Popover
      label={t.menuLabel}
      trigger={(props) => (
        <Button size="sm" icon={<PlusIcon />} {...props}>
          {t.addToProject}
        </Button>
      )}
    >
      {({ close }) => <ProjectPicker trackId={trackId} trackTitle={trackTitle} close={close} />}
    </Popover>
  )
}

interface Loaded {
  projects: Project[]
  /** Ids of the projects whose shortlist has this track. */
  members: number[]
}

/** The projects, and which of them already hold the track. A project that fails to load is skipped. */
async function loadProjects(trackId: number, signal: AbortSignal): Promise<Loaded> {
  const projects = await listProjects({ signal })
  const checked = await Promise.all(
    projects.map(async (project) => {
      if (project.item_count === 0) return false
      try {
        const items = await listProjectItems(project.id, { signal })
        return items.some((entry) => entry.track.id === trackId)
      } catch {
        return false
      }
    }),
  )
  return {
    projects: sortByRecent(projects),
    members: projects.filter((_, index) => checked[index]).map((project) => project.id),
  }
}

function ProjectPicker({
  trackId,
  trackTitle,
  close,
}: AddToProjectMenuProps & { close: () => void }) {
  const toast = useToast()
  const loaded = useAsync((signal) => loadProjects(trackId, signal), [trackId])
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  // Changes made in this menu, on top of what was loaded: project id -> now on the shortlist.
  const [changes, setChanges] = useState<Record<number, boolean>>({})
  // Set after an add: the menu then offers a link to the project.
  const [added, setAdded] = useState<{ id: number; name: string } | null>(null)
  const track = trackTitle || t.untitled

  const isMember = (projectId: number) =>
    changes[projectId] ?? loaded.data?.members.includes(projectId) ?? false

  const toggle = async (project: Project) => {
    setBusy(true)
    try {
      if (isMember(project.id)) {
        await deleteProjectItem(project.id, trackId)
        setChanges((current) => ({ ...current, [project.id]: false }))
        toast.info(t.removed(track, project.name))
        close()
      } else {
        await putProjectItem(project.id, trackId)
        markProjectUsed(project.id)
        setChanges((current) => ({ ...current, [project.id]: true }))
        toast.info(t.added(track, project.name))
        setAdded({ id: project.id, name: project.name })
      }
    } catch (error) {
      toast.error(errorMessage(error))
    }
    setBusy(false)
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    try {
      const project = await createProject(trimmed)
      await putProjectItem(project.id, trackId)
      markProjectUsed(project.id)
      toast.info(t.createdAndAdded(track, project.name))
      setAdded({ id: project.id, name: project.name })
    } catch (error) {
      toast.error(errorMessage(error))
    }
    setBusy(false)
  }

  if (added) {
    return (
      <div className={styles.picker}>
        <p className={styles.confirmation}>
          <CheckIcon width={14} height={14} />
          {t.confirmation(added.name)}
        </p>
        <div className={styles.actions}>
          <a
            className={styles.link}
            href={hrefFor('projects', [added.id])}
            onClick={close}
            ref={(element) => element?.focus()}
          >
            {t.openProject}
          </a>
          <Button size="sm" variant="ghost" onClick={close}>
            {t.done}
          </Button>
        </div>
      </div>
    )
  }

  if (creating) {
    return (
      <form className={styles.form} onSubmit={create}>
        <TextInput
          label={t.projectName}
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={120}
          autoFocus
        />
        <div className={styles.actions}>
          <Button variant="ghost" size="sm" onClick={() => setCreating(false)} disabled={busy}>
            {strings.common.cancel}
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={busy || !name.trim()}>
            {t.create}
          </Button>
        </div>
      </form>
    )
  }

  return (
    <div className={styles.picker}>
      {loaded.loading && !loaded.data ? (
        <div className={styles.center}>
          <Spinner />
        </div>
      ) : null}
      {loaded.error ? (
        <Notice
          kind="error"
          action={
            <Button size="sm" onClick={loaded.reload}>
              {strings.common.retry}
            </Button>
          }
        >
          {errorMessage(loaded.error)}
        </Notice>
      ) : null}
      {loaded.data && loaded.data.projects.length === 0 ? (
        <p className={styles.empty}>{t.noProjects}</p>
      ) : null}
      {loaded.data && loaded.data.projects.length > 0 ? (
        <ul className={styles.list}>
          {loaded.data.projects.map((project) => {
            const member = isMember(project.id)
            return (
              <li key={project.id}>
                <button
                  type="button"
                  className={styles.item}
                  disabled={busy}
                  aria-pressed={member}
                  title={member ? t.hasTrack : undefined}
                  onClick={() => void toggle(project)}
                >
                  <span className={styles.mark} aria-hidden="true">
                    {member ? <CheckIcon width={14} height={14} /> : null}
                  </span>
                  <span className={styles.name}>{project.name}</span>
                  <span className={styles.count}>{t.tracks(project.item_count)}</span>
                </button>
              </li>
            )
          })}
        </ul>
      ) : null}
      <button type="button" className={styles.item} disabled={busy} onClick={() => setCreating(true)}>
        <PlusIcon />
        <span className={styles.name}>{t.newProject}</span>
      </button>
    </div>
  )
}
