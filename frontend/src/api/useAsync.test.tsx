import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { useAsync } from './useAsync'

function Probe({ id, load }: { id: number; load: (id: number, signal: AbortSignal) => Promise<string> }) {
  const state = useAsync((signal) => load(id, signal), [id])
  return (
    <div>
      <p>{state.loading ? 'loading' : 'idle'}</p>
      <p>{state.data ? `data:${state.data}` : 'no data'}</p>
      <p>{state.error ? `error:${state.error.message}` : 'no error'}</p>
      <button onClick={state.reload}>reload</button>
    </div>
  )
}

describe('useAsync', () => {
  it('loads, then reloads on request', async () => {
    const load = vi.fn().mockResolvedValueOnce('one').mockResolvedValueOnce('two')
    render(<Probe id={1} load={load} />)
    expect(screen.getByText('loading')).toBeInTheDocument()
    expect(await screen.findByText('data:one')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'reload' }))
    expect(await screen.findByText('data:two')).toBeInTheDocument()
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('reports an error', async () => {
    render(<Probe id={1} load={() => Promise.reject(new Error('boom'))} />)
    expect(await screen.findByText('error:boom')).toBeInTheDocument()
    expect(screen.getByText('idle')).toBeInTheDocument()
  })

  it('aborts the request on unmount and when the deps change', async () => {
    const signals: AbortSignal[] = []
    const load = (_id: number, signal: AbortSignal) => {
      signals.push(signal)
      return new Promise<string>(() => {})
    }
    const { rerender, unmount } = render(<Probe id={1} load={load} />)
    rerender(<Probe id={2} load={load} />)
    await waitFor(() => expect(signals).toHaveLength(2))
    expect(signals[0]?.aborted).toBe(true)
    expect(signals[1]?.aborted).toBe(false)
    unmount()
    expect(signals[1]?.aborted).toBe(true)
  })

  it('drops the data of the old deps while the new ones load', async () => {
    const load = vi.fn((id: number) => Promise.resolve(`track${id}`))
    const { rerender } = render(<Probe id={1} load={load} />)
    expect(await screen.findByText('data:track1')).toBeInTheDocument()
    let release: (value: string) => void = () => {}
    rerender(<Probe id={2} load={() => new Promise<string>((resolve) => (release = resolve))} />)
    expect(screen.getByText('no data')).toBeInTheDocument()
    release('track2')
    expect(await screen.findByText('data:track2')).toBeInTheDocument()
  })
})
