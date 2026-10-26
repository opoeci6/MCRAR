import { useMemo, useSyncExternalStore } from 'react'

export const PAGE_IDS = ['search', 'projects', 'library', 'label', 'settings'] as const
export type PageId = (typeof PAGE_IDS)[number]
export const DEFAULT_PAGE: PageId = 'search'

/** What every page component receives. */
export interface PageProps {
  /** The rest of the path after the page: `#/projects/12` gives `['12']`. */
  subpath: string[]
  /** The query part of the hash: `#/search?q=rain` gives `q=rain`. */
  params: URLSearchParams
}

export interface Route {
  page: PageId
  subpath: string[]
  params: URLSearchParams
}

/** Reads a location hash such as `#/projects/12?x=1`. Anything unknown is the default page. */
export function parseHash(hash: string): Route {
  const body = hash.replace(/^#\/?/, '')
  const [pathPart = '', ...queryParts] = body.split('?')
  const [first = '', ...rest] = pathPart.split('/').filter(Boolean)
  const page = (PAGE_IDS as readonly string[]).includes(first) ? (first as PageId) : null
  if (page === null) {
    return { page: DEFAULT_PAGE, subpath: [], params: new URLSearchParams() }
  }
  const subpath = rest.map((part) => {
    try {
      return decodeURIComponent(part)
    } catch {
      return part
    }
  })
  return { page, subpath, params: new URLSearchParams(queryParts.join('?')) }
}

/** `hrefFor('projects', 12)` is `#/projects/12`. For `<a href>` and `navigate`. */
export function hrefFor(
  page: PageId,
  subpath: (string | number)[] = [],
  params?: Record<string, string>,
): string {
  const path = [page, ...subpath.map((part) => encodeURIComponent(String(part)))].join('/')
  const query = params ? new URLSearchParams(params).toString() : ''
  return `#/${path}${query ? `?${query}` : ''}`
}

/** Goes to a page (adds a history entry, so the Back button returns). */
export function navigate(page: PageId, subpath: (string | number)[] = [], params?: Record<string, string>) {
  window.location.hash = hrefFor(page, subpath, params)
}

function subscribe(callback: () => void) {
  window.addEventListener('hashchange', callback)
  return () => window.removeEventListener('hashchange', callback)
}

/** The current route, kept in step with the location hash. */
export function useHashRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  return useMemo(() => parseHash(hash), [hash])
}
