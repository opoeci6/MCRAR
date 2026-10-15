import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { openJobEvents } from './events'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  static readonly CLOSED = 2
  readyState = 0
  closed = false
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>()
  url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close() {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }

  emit(type: string, data: unknown) {
    const event = new MessageEvent(type, { data: typeof data === 'string' ? data : JSON.stringify(data) })
    this.listeners.get(type)?.forEach((listener) => listener(event))
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('openJobEvents', () => {
  it('opens the job stream and calls the typed handlers', () => {
    const onStarted = vi.fn()
    const onProgress = vi.fn()
    const onWarning = vi.fn()
    openJobEvents('a1b2', { onStarted, onProgress, onWarning })
    const source = FakeEventSource.instances[0]!
    expect(source.url).toBe('/api/jobs/a1b2/events')

    source.emit('started', { kind: 'ingest-local', params: {} })
    source.emit('progress', { kind: 'track_done', index: 1, total: 3, title: 'A', message: null })
    source.emit('warning', { message: 'embedding skipped' })

    expect(onStarted).toHaveBeenCalledWith({ kind: 'ingest-local', params: {} })
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ index: 1, total: 3 }))
    expect(onWarning).toHaveBeenCalledWith({ message: 'embedding skipped' })
    expect(source.closed).toBe(false)
  })

  it.each(['done', 'failed', 'cancelled'] as const)('closes itself after %s', (type) => {
    const handlers = { onDone: vi.fn(), onFailed: vi.fn(), onCancelled: vi.fn() }
    openJobEvents('x', handlers)
    const source = FakeEventSource.instances[0]!
    source.emit(type, { report: null, error: 'boom' })
    expect(source.closed).toBe(true)
    const handler = { done: handlers.onDone, failed: handlers.onFailed, cancelled: handlers.onCancelled }[type]
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('returns a function that closes the stream and silences handlers', () => {
    const onProgress = vi.fn()
    const close = openJobEvents('x', { onProgress })
    const source = FakeEventSource.instances[0]!
    close()
    expect(source.closed).toBe(true)
    source.emit('progress', { kind: 'track_done', index: 1, total: 1, title: '', message: null })
    expect(onProgress).not.toHaveBeenCalled()
  })

  it('skips a malformed event and keeps going', () => {
    const onProgress = vi.fn()
    openJobEvents('x', { onProgress })
    const source = FakeEventSource.instances[0]!
    source.emit('progress', '{not json')
    expect(onProgress).not.toHaveBeenCalled()
    expect(source.closed).toBe(false)
  })
})
