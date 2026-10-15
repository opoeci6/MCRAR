import { strings } from '../../strings'
import { EmptyState } from '../../ui/EmptyState'
import { PageHeader } from '../../ui/PageHeader'
import { settingsStrings } from './strings'

// Placeholder: this folder is replaced by the Settings page slice.
export default function SettingsPage() {
  return (
    <>
      <PageHeader title={settingsStrings.title} description={settingsStrings.description} />
      <EmptyState title={settingsStrings.placeholderTitle} description={strings.empty.comingSoon} />
    </>
  )
}
