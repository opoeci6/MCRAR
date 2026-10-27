import { describe, expect, it } from 'vitest'
import { sourceLabel } from './sourceLabel'

describe('sourceLabel', () => {
  it('names the known sources', () => {
    expect(sourceLabel('jamendo')).toBe('Jamendo')
    expect(sourceLabel('local')).toBe('Local')
  })

  it('falls back to the raw value for an unknown source', () => {
    expect(sourceLabel('spotify')).toBe('spotify')
    expect(sourceLabel('')).toBe('')
  })

  it('does not read inherited object keys as sources', () => {
    expect(sourceLabel('constructor')).toBe('constructor')
  })
})
