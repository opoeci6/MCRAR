/** Where an in-page popup list opens relative to its anchor control. */
export interface Placement {
  /** Open upward (above the anchor) instead of downward. */
  up: boolean
  /** The tallest the list may be, in px, so it fits the free space. */
  maxHeight: number
}

export const LIST_MAX_HEIGHT = 280
const LIST_MIN_HEIGHT = 120
/** Room below the anchor that the list should not use (the player bar sits at the window bottom). */
const BOTTOM_MARGIN = 120
/** Open upward when there is less than this below and more above. */
const MIN_SPACE_BELOW = 200
const EDGE_GAP = 12

export const DEFAULT_PLACEMENT: Placement = { up: false, maxHeight: LIST_MAX_HEIGHT }

/**
 * Picks up or down for a list under `anchor` from the space in the window. The sticky page header
 * (`--header-h`) covers the top of the window, so it counts as not free.
 */
export function measurePlacement(anchor: HTMLElement): Placement {
  const rect = anchor.getBoundingClientRect()
  const below = window.innerHeight - rect.bottom - BOTTOM_MARGIN
  const header = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h'))
  const above = rect.top - (Number.isFinite(header) ? header : 0) - EDGE_GAP
  const up = below < MIN_SPACE_BELOW && above > below
  const space = up ? above : below
  return { up, maxHeight: Math.min(LIST_MAX_HEIGHT, Math.max(LIST_MIN_HEIGHT, space)) }
}
