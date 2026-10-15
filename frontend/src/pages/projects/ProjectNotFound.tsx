import { hrefFor } from '../../app/route'
import { EmptyState } from '../../ui/EmptyState'
import { projectsStrings as t } from './strings'
import styles from './ProjectsPage.module.css'

export function ProjectNotFound() {
  return (
    <EmptyState
      title={t.notFoundTitle}
      description={t.notFoundBody}
      action={
        <a className={styles.linkButton} href={hrefFor('projects')}>
          {t.backToProjects}
        </a>
      }
    />
  )
}
