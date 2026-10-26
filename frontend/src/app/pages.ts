import type { ComponentType } from 'react'
import LabelPage from '../pages/label'
import LibraryPage from '../pages/library'
import ProjectsPage from '../pages/projects'
import SearchPage from '../pages/search'
import SettingsPage from '../pages/settings'
import { strings } from '../strings'
import type { PageId, PageProps } from './route'

/**
 * The pages, in tab order. Each is the default export of `src/pages/<name>/index.tsx` and gets
 * the rest of the URL path as `subpath`. Adding a page means adding it here and to `PAGE_IDS`.
 */
export const PAGES: { id: PageId; label: string; component: ComponentType<PageProps> }[] = [
  { id: 'search', label: strings.nav.search, component: SearchPage },
  { id: 'projects', label: strings.nav.projects, component: ProjectsPage },
  { id: 'library', label: strings.nav.library, component: LibraryPage },
  { id: 'label', label: strings.nav.label, component: LabelPage },
  { id: 'settings', label: strings.nav.settings, component: SettingsPage },
]
