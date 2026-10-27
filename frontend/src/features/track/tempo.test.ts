import { describe, expect, it } from 'vitest'
import { formatTempo } from './tempo'

describe('formatTempo', () => {
  it.each([
    [113.4, 0.8, '113', false],
    [113.4, 0.5, '113', false], // 0.5 is confident enough
    [175, 0.5, '175', false],
    [175, null, '175', false],
    [175, undefined, '175', false],
    [60, 0.9, '60', false],
    [140, 0.49, '70 / 140', true], // half first, from 140
    [139.9, 0.49, '140', false],
    [175, 0.2, '88 / 175', true], // 87.5 rounds up
    [180, 0.1, '90 / 180', true],
    [89.9, 0.49, '90 / 180', true], // double second, below 90
    [90, 0.49, '90', false],
    [75, 0.3, '75 / 150', true],
    [70, 0, '70 / 140', true],
    [113, 0.4, '113', false], // the other reading falls outside 70 to 180
  ])('bpm %s at confidence %s reads %s', (bpm, confidence, value, uncertain) => {
    expect(formatTempo(bpm, confidence)).toEqual({ value, uncertain })
  })
})
