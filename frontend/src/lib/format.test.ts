import { describe, expect, it } from 'vitest'
import { embedderName, formatDownload } from './format'

describe('formatDownload', () => {
  it('counts in whole MB below 1 GB', () => {
    expect(formatDownload(312_400_000, 776_000_000)).toEqual({ done: '312 MB', total: '776 MB' })
    expect(formatDownload(0, 776_000_000)).toEqual({ done: '0 MB', total: '776 MB' })
  })

  it('counts both numbers in GB with one decimal once the larger one reaches 1 GB', () => {
    expect(formatDownload(300_000_000, 1_200_000_000)).toEqual({ done: '0.3 GB', total: '1.2 GB' })
    expect(formatDownload(2_500_000_000, 2_500_000_000)).toEqual({ done: '2.5 GB', total: '2.5 GB' })
  })

  it('has no total while it is unknown', () => {
    expect(formatDownload(312_000_000, null)).toEqual({ done: '312 MB', total: null })
    expect(formatDownload(1_500_000_000, null)).toEqual({ done: '1.5 GB', total: null })
    expect(formatDownload(5_000_000, 0)).toEqual({ done: '5 MB', total: null })
  })
})

describe('embedderName', () => {
  it('joins the key and the model id', () => {
    expect(embedderName({ key: 'clap', model_id: 'laion/clap' })).toBe('clap (laion/clap)')
  })
})
