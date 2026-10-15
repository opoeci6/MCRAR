import type { SettingsView } from '../../api'

export interface SectionProps {
  view: SettingsView
  onUpdated: (view: SettingsView) => void
}
