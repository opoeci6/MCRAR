import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job } from '../../api'
import { FakeEventSource } from '../../test/eventSource'
import { jsonResponse, stubApi } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import { InlineJobProgress } from './InlineJobProgress'

const job: Job = {
  id: 'j1',
  kind: 'ingest-query',
  params: { text: 'rain' },
  status: 'running',
  created_at: '2026-10-15T10:00:00Z',
  finished_at: null,
  cancel_requested: false,
  error: null,
  progress: null,
}

const source = () => FakeEventSource.instances[FakeEventSource.instances.length - 1]!

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('InlineJobProgress', () => {
  it('shows an indeterminate bar until the total is known, then "n of total" and the track', () => {
    stubApi({})
    renderWithProviders(<InlineJobProgress job={job} title="Working" onSettled={() => {}} />)
    expect(screen.getByText('Working')).toBeInTheDocument()
    expect(screen.getByText('0 so far')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('max')
    source().emit('progress', { kind: 'track_done', index: 3, total: 10, title: 'Rain Song', message: null })
    expect(screen.getByText('3 of 10')).toBeInTheDocument()
    expect(screen.getByText('Rain Song')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('max', '10')
  })

  it('calls cancel and shows that it is cancelling', async () => {
    const mock = stubApi({ 'POST /api/jobs/j1/cancel': { job } })
    renderWithProviders(<InlineJobProgress job={job} title="Working" onSettled={() => {}} />)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(
        mock.mock.calls.some(([url, init]) => String(url) === '/api/jobs/j1/cancel' && init?.method === 'POST'),
      ).toBe(true),
    )
    expect(screen.getByRole('button', { name: 'Cancelling' })).toBeDisabled()
  })

  it('reports the final state once', async () => {
    stubApi({})
    const onSettled = vi.fn()
    renderWithProviders(<InlineJobProgress job={job} title="Working" onSettled={onSettled} />)
    source().emit('done', { report: null })
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1))
    expect(onSettled.mock.calls[0]![0]).toMatchObject({ id: 'j1', status: 'done' })
  })

  it('reports the failure of the job', async () => {
    stubApi({})
    const onSettled = vi.fn()
    renderWithProviders(<InlineJobProgress job={job} title="Working" onSettled={onSettled} />)
    source().emit('failed', { report: null, error: 'boom' })
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1))
    expect(onSettled.mock.calls[0]![0]).toMatchObject({ status: 'failed', error: 'boom' })
  })

  it('asks for the job when the stream is lost', async () => {
    stubApi({
      'GET /api/jobs/j1': jsonResponse({
        job: { ...job, status: 'failed', error: 'boom', event_count: 2, report: null },
      }),
    })
    const onSettled = vi.fn()
    renderWithProviders(<InlineJobProgress job={job} title="Working" onSettled={onSettled} />)
    const stream = source()
    stream.readyState = FakeEventSource.CLOSED
    stream.emit('error', {})
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1))
    expect(onSettled.mock.calls[0]![0]).toMatchObject({ status: 'failed', error: 'boom' })
  })
})
