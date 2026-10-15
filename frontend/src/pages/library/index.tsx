import { strings } from '../../strings'
import { EmptyState } from '../../ui/EmptyState'
import { PageHeader } from '../../ui/PageHeader'
import { libraryStrings } from './strings'

// Placeholder: this folder is replaced by the Library page slice.
export default function LibraryPage() {
  return (
    <>
      <PageHeader title={libraryStrings.title} description={libraryStrings.description} />
      <EmptyState title={libraryStrings.placeholderTitle} description={strings.empty.comingSoon} />
    </>
  )
}
