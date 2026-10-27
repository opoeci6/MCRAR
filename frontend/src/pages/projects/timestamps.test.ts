import { describe, expect, it } from 'vitest'
import { formatTimestamp, parseTimestamp, splitTimestamps } from './timestamps'

describe('formatTimestamp', () => {
  it('writes m:ss, and h:mm:ss from one hour', () => {
    expect(formatTimestamp(0)).toBe('0:00')
    expect(formatTimestamp(18.9)).toBe('0:18')
    expect(formatTimestamp(65)).toBe('1:05')
    expect(formatTimestamp(754)).toBe('12:34')
    expect(formatTimestamp(3600)).toBe('1:00:00')
    expect(formatTimestamp(3723)).toBe('1:02:03')
  })

  it('falls back to 0:00 for a position that is not a time', () => {
    expect(formatTimestamp(Number.NaN)).toBe('0:00')
    expect(formatTimestamp(-4)).toBe('0:00')
  })
})

describe('parseTimestamp', () => {
  it.each([
    ['0:18', 18],
    ['00:18', 18],
    ['1:05', 65],
    ['12:34', 754],
    ['0:59', 59],
    ['1:02:03', 3723],
    ['01:00:00', 3600],
  ])('reads %s', (token, seconds) => {
    expect(parseTimestamp(token)).toBe(seconds)
  })

  it.each(['0:60', '1:5', '1:75', '123:45', '1:2:3', '1:60:00', '1:00:60', '18', 'a1:23', '1:23x', ' 1:23', ''])(
    'rejects %j',
    (token) => {
      expect(parseTimestamp(token)).toBeNull()
    },
  )
})

describe('splitTimestamps', () => {
  it('returns one text part for a note without times', () => {
    expect(splitTimestamps('Fits the menu')).toEqual([{ text: 'Fits the menu' }])
    expect(splitTimestamps('')).toEqual([])
  })

  it('cuts out the timestamps and keeps the text and line breaks around them', () => {
    expect(splitTimestamps('Intro 0:18, drop at 1:02:03.\nLoop from 2:30')).toEqual([
      { text: 'Intro ' },
      { text: '0:18', seconds: 18 },
      { text: ', drop at ' },
      { text: '1:02:03', seconds: 3723 },
      { text: '.\nLoop from ' },
      { text: '2:30', seconds: 150 },
    ])
  })

  it('accepts a time at the start or end, and one followed by a colon', () => {
    expect(splitTimestamps('0:18: nice')).toEqual([{ text: '0:18', seconds: 18 }, { text: ': nice' }])
    expect(splitTimestamps('(3:07)')).toEqual([
      { text: '(' },
      { text: '3:07', seconds: 187 },
      { text: ')' },
    ])
  })

  it('leaves out anything that is not a whole time', () => {
    const notes = ['0:60 is not a time', 'ratio 1:5', 'v1:23x', '12:30pm', 'a 12:75:30 b', '1234:56']
    for (const note of notes) expect(splitTimestamps(note)).toEqual([{ text: note }])
  })

  it('joins back to the note', () => {
    const note = 'a 0:05 b 10:00 c 1:00:00\nd 9:59'
    expect(
      splitTimestamps(note)
        .map((part) => part.text)
        .join(''),
    ).toBe(note)
  })
})
