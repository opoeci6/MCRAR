import { useState } from 'react'
import type { FormEvent } from 'react'
import { createProject, listProjects, putProjectItem } from '../../api/endpoints'
import { errorMessage, useAsync } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { PlusIcon } from '../../ui/icons'
import { Notice } from '../../ui/Notice'
import { Popover } from '../../ui/Popover'
import { Spinner } from '../../ui/Spinner'
import { TextInput } from '../../ui/TextInput'
import { projectsFeatureStrings as t } from './strings'
import styles from './AddToProjectMenu.module.css'

export interface AddToProjectMenuProps {
  trackId: number
  trackTitle: string
}

/** A button that opens the list of projects; picking one adds the track to its shortlist. */
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

function ProjectPicker({
  trackId,
  trackTitle,
  close,
}: AddToProjectMenuProps & { close: () => void }) {
  const toast = useToast()
  const projects = useAsync((signal) => listProjects({ signal }), [])
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const track = trackTitle || t.untitled

  const addTo = async (projectId: number, projectName: string) => {
    setBusy(true)
    try {
      await putProjectItem(projectId, trackId)
      toast.info(t.added(track, projectName))
      close()
    } catch (error) {
      toast.error(errorMessage(error))
      setBusy(false)
    }
  }

  const create = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    try {
      const project = await createProject(trimmed)
      await putProjectItem(project.id, trackId)
      toast.info(t.createdAndAdded(track, project.name))
      close()
    } catch (error) {
      toast.error(errorMessage(error))
      setBusy(false)
    }
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
      {projects.loading && !projects.data ? (
        <div className={styles.center}>
          <Spinner />
        </div>
      ) : null}
      {projects.error ? (
        <Notice
          kind="error"
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
        <p className={styles.empty}>{t.noProjects}</p>
      ) : null}
      {projects.data && projects.data.length > 0 ? (
        <ul className={styles.list}>
          {projects.data.map((project) => (
            <li key={project.id}>
              <button
                type="button"
                className={styles.item}
                disabled={busy}
                onClick={() => void addTo(project.id, project.name)}
              >
                <span className={styles.name}>{project.name}</span>
                <span className={styles.count}>{t.tracks(project.item_count)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <button type="button" className={styles.item} disabled={busy} onClick={() => setCreating(true)}>
        <PlusIcon />
        <span className={styles.name}>{t.newProject}</span>
      </button>
    </div>
  )
}
