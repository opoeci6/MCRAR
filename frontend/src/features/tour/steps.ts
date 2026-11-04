import type { PageId } from '../../app/route'
import { tourStrings as t } from './strings'

export interface TourStep {
  id: string
  /** The tab to open before pointing at the target. Keeps the current page when missing. */
  page?: PageId
  /** The `data-tour` value of the element to spotlight. Missing: a centred card with no spotlight. */
  target?: string
  title: string
  body: string
}

/** The tour in order. Step 0 is the welcome card; the others are numbered "Step N of 7". */
export const TOUR_STEPS: readonly TourStep[] = [
  { id: 'welcome', title: t.welcome.title, body: t.welcome.body },
  { id: 'nav', target: 'nav', title: t.nav.title, body: t.nav.body },
  { id: 'keys', page: 'settings', target: 'settings-keys', title: t.keys.title, body: t.keys.body },
  { id: 'add-music', page: 'library', target: 'add-music', title: t.addMusic.title, body: t.addMusic.body },
  { id: 'search-box', page: 'search', target: 'search-box', title: t.searchBox.title, body: t.searchBox.body },
  { id: 'filters', page: 'search', target: 'search-filters', title: t.filters.title, body: t.filters.body },
  { id: 'projects', page: 'projects', target: 'projects-list', title: t.projects.title, body: t.projects.body },
  { id: 'finish', page: 'settings', target: 'settings-tutorial', title: t.finish.title, body: t.finish.body },
]
