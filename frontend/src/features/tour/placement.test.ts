import { describe, expect, it } from 'vitest'
import { CARD_GAP, centerCard, placeCard } from './placement'

const VIEWPORT = { width: 1000, height: 700 }
const CARD = { width: 380, height: 200 }

describe('placeCard', () => {
  it('goes below the target, centred on it', () => {
    const target = { top: 100, left: 300, width: 200, height: 40 }
    expect(placeCard(target, CARD, VIEWPORT)).toEqual({ top: 140 + CARD_GAP, left: 400 - 190 })
  })

  it('goes above when there is no room below', () => {
    const target = { top: 560, left: 300, width: 200, height: 100 }
    expect(placeCard(target, CARD, VIEWPORT)).toEqual({ top: 560 - CARD_GAP - 200, left: 210 })
  })

  it('goes beside the target when it is too tall for above or below', () => {
    const target = { top: 20, left: 20, width: 200, height: 660 }
    const { top, left } = placeCard(target, CARD, VIEWPORT)
    expect(left).toBe(220 + CARD_GAP)
    expect(top).toBe(350 - 100)
  })

  it('goes to the left of the target when the right side is full', () => {
    const target = { top: 20, left: 780, width: 200, height: 660 }
    const { top, left } = placeCard(target, CARD, VIEWPORT)
    expect(left).toBe(780 - CARD_GAP - 380)
    expect(top).toBe(250)
  })

  it('stays inside the window when the target is at the edge', () => {
    const target = { top: 10, left: 0, width: 60, height: 30 }
    const { top, left } = placeCard(target, CARD, VIEWPORT)
    expect(left).toBe(CARD_GAP)
    expect(top).toBe(40 + CARD_GAP)

    const farRight = { top: 10, left: 960, width: 40, height: 30 }
    expect(placeCard(farRight, CARD, VIEWPORT).left).toBe(1000 - 380 - CARD_GAP)
  })

  it('stays inside the window when the target covers it', () => {
    const target = { top: 0, left: 0, width: 1000, height: 700 }
    const { top, left } = placeCard(target, CARD, VIEWPORT)
    expect(top).toBe(700 - 200 - CARD_GAP)
    expect(left).toBe(310)
    expect(left).toBeGreaterThanOrEqual(CARD_GAP)
    expect(left + CARD.width).toBeLessThanOrEqual(VIEWPORT.width - CARD_GAP)
  })

  it('keeps a wide card on a narrow window', () => {
    const narrow = { width: 300, height: 600 }
    const { left } = placeCard({ top: 100, left: 100, width: 50, height: 30 }, { width: 320, height: 150 }, narrow)
    expect(left).toBe(CARD_GAP)
  })

  it('does not go above into the sticky header', () => {
    // 216 px free above the target, but the top 56 px are the header: below does not fit either.
    const target = { top: 228, left: 300, width: 200, height: 400 }
    const { top } = placeCard(target, CARD, VIEWPORT, 56)
    expect(top).toBeGreaterThanOrEqual(56 + CARD_GAP)
    expect(top).not.toBe(228 - CARD_GAP - 200)
  })

  it('goes above when the room under the header is enough', () => {
    const target = { top: 300, left: 300, width: 200, height: 330 }
    expect(placeCard(target, CARD, VIEWPORT, 56)).toEqual({ top: 300 - CARD_GAP - 200, left: 210 })
  })

  it('keeps a card placed below a target in the header (the tabs) under the header', () => {
    const target = { top: 4, left: 100, width: 400, height: 40 }
    expect(placeCard(target, CARD, VIEWPORT, 56).top).toBe(56 + CARD_GAP)
  })
})

describe('centerCard', () => {
  it('centres the card in the window', () => {
    expect(centerCard(CARD, VIEWPORT)).toEqual({ top: 250, left: 310 })
  })

  it('never starts off screen', () => {
    expect(centerCard({ width: 2000, height: 2000 }, VIEWPORT)).toEqual({ top: CARD_GAP, left: CARD_GAP })
  })
})
