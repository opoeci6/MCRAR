import { act } from '@testing-library/react'

/**
 * A stand-in for `EventSource`: `vi.stubGlobal('EventSource', FakeEventSource)`, then drive a
 * job with `FakeEventSource.instances.at(-1).emit('progress', {...})`.
 */
export class FakeEventSource {
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
    const event = new MessageEvent(type, { data: JSON.stringify(data) })
    act(() => this.listeners.get(type)?.forEach((listener) => listener(event)))
  }
}
