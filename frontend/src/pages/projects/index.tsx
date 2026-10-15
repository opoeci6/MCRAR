import { listProjects } from '../../api/endpoints'
import { useAsync } from '../../api/useAsync'
import type { PageProps } from '../../app/route'
import { EmptyState } from '../../ui/EmptyState'
import { PageHeader } from '../../ui/PageHeader'
import { ProjectDetail } from './ProjectDetail'
import { ProjectList } from './ProjectList'
import { ProjectNotFound } from './ProjectNotFound'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

/** `#/projects/12` selects project 12; a part that is not a whole number is not found. */
function selectedId(part: string | undefined): number | null | 'invalid' {
  if (part === undefined) return null
  return /^\d+$/.test(part) ? Number(part) : 'invalid'
}

export default function ProjectsPage({ subpath }: PageProps) {
  const projects = useAsync((signal) => listProjects({ signal }), [])
  const selected = selectedId(subpath[0])

  let detail
  if (selected === 'invalid') {
    detail = <ProjectNotFound />
  } else if (selected !== null) {
    detail = <ProjectDetail key={selected} projectId={selected} onChanged={projects.reload} />
  } else if (projects.data && projects.data.length === 0) {
    detail = <EmptyState title={t.noProjectsTitle} description={t.noProjectsBody} />
  } else if (projects.data) {
    detail = <EmptyState title={t.selectTitle} description={t.selectBody} />
  }

  return (
    <>
      <PageHeader title={t.title} description={t.description} />
      <div className={styles.layout}>
        <ProjectList
          projects={projects}
          selectedId={typeof selected === 'number' ? selected : null}
        />
        <section className={styles.detail}>{detail}</section>
      </div>
    </>
  )
}
