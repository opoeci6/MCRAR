/** A rectangle in window (viewport) coordinates. */
export interface Box {
  top: number
  left: number
  width: number
  height: number
}

export interface Size {
  width: number
  height: number
}

export interface Position {
  top: number
  left: number
}

/** The space kept between the card and the target, and between the card and the window edge. */
export const CARD_GAP = 12

/** Keeps `value` so that something of `size` stays inside `[start + GAP, limit - GAP]` (the start wins if it cannot fit). */
function clamp(value: number, size: number, limit: number, start = 0): number {
  return Math.max(start + CARD_GAP, Math.min(value, limit - size - CARD_GAP))
}

/**
 * Where to put the tour card for a spotlighted `target`: below it if the card fits there, else
 * above, else beside (right, then left), else pinned to the bottom of the window. The card is
 * always kept fully on screen, and below `topInset` (the sticky page header, which it would cover).
 */
export function placeCard(target: Box, card: Size, viewport: Size, topInset = 0): Position {
  const centredLeft = clamp(target.left + target.width / 2 - card.width / 2, card.width, viewport.width)
  const centredTop = clamp(
    target.top + target.height / 2 - card.height / 2,
    card.height,
    viewport.height,
    topInset,
  )

  const below = Math.max(target.top + target.height + CARD_GAP, topInset + CARD_GAP)
  if (below + card.height <= viewport.height - CARD_GAP) return { top: below, left: centredLeft }

  const above = target.top - CARD_GAP - card.height
  if (above >= topInset + CARD_GAP) return { top: above, left: centredLeft }

  const right = target.left + target.width + CARD_GAP
  if (right + card.width <= viewport.width - CARD_GAP) return { top: centredTop, left: right }

  const left = target.left - CARD_GAP - card.width
  if (left >= CARD_GAP) return { top: centredTop, left }

  return { top: clamp(viewport.height, card.height, viewport.height, topInset), left: centredLeft }
}

/** The card in the middle of the window (the welcome step, or a step whose target was not found). */
export function centerCard(card: Size, viewport: Size): Position {
  return {
    top: clamp((viewport.height - card.height) / 2, card.height, viewport.height),
    left: clamp((viewport.width - card.width) / 2, card.width, viewport.width),
  }
}
