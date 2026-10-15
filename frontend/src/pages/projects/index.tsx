import { strings } from '../../strings'
import { EmptyState } from '../../ui/EmptyState'
import { PageHeader } from '../../ui/PageHeader'
import { projectsStrings } from './strings'

// Placeholder: this folder is replaced by the Projects page slice.
export default function ProjectsPage() {
  return (
    <>
      <PageHeader title={projectsStrings.title} description={projectsStrings.description} />
      <EmptyState title={projectsStrings.placeholderTitle} description={strings.empty.comingSoon} />
    </>
  )
}
