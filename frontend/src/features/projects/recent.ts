/*
 * The projects the user added tracks to last, newest first, so the add-to-project menu can put
 * them at the top. Kept in localStorage; any storage failure just means no ordering.
 */
const KEY = 'mcrar.recentProjects'
const MAX = 20

export function recentProjectIds(): number[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((id): id is number => Number.isInteger(id)) : []
  } catch {
    return []
  }
}

export function markProjectUsed(projectId: number): void {
  try {
    const next = [projectId, ...recentProjectIds().filter((id) => id !== projectId)].slice(0, MAX)
    window.localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // Storage is unavailable (private mode, quota): ordering is a nicety, not a feature.
  }
}

/** The projects with the most recently used first; the rest keep their order. */
export function sortByRecent<T extends { id: number }>(projects: T[]): T[] {
  const recent = recentProjectIds()
  const rank = (id: number) => {
    const index = recent.indexOf(id)
    return index === -1 ? Number.MAX_SAFE_INTEGER : index
  }
  return [...projects].sort((a, b) => rank(a.id) - rank(b.id))
}
