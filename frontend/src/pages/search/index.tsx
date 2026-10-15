import { strings } from '../../strings'
import { EmptyState } from '../../ui/EmptyState'
import { PageHeader } from '../../ui/PageHeader'
import { searchStrings } from './strings'

// Placeholder: this folder is replaced by the Search page slice.
export default function SearchPage() {
  return (
    <>
      <PageHeader title={searchStrings.title} description={searchStrings.description} />
      <EmptyState title={searchStrings.placeholderTitle} description={strings.empty.comingSoon} />
    </>
  )
}
