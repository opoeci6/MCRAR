import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearPersistentState } from '../../app/usePersistentState'
import { jsonResponse, stubApi } from '../../test/fetch'
import type { Routes } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import LibraryPage from './index'

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
    const event = new MessageEvent(type, { data: JSON.stringify(data) })
    act(() => this.listeners.get(type)?.forEach((listener) => listener(event)))
  }
}

const STATS = {
  tracks: 120,
  tracks_by_source: { jamendo: 100, local: 20 },
  tracks_by_risk: { green: 80, amber: 30, red: 10 },
  features: { tracks_with_features: 90, coverage: 0.75 },
  embeddings_by_model: { clap: 60 },
  ingest_failures_by_stage: {},
}

const track = (id: number, title: string) => ({
  id,
  title,
  artist: `Artist ${id}`,
  source: 'jamendo',
  duration_s: 187,
  risk: 'green',
  license_code: 'CC BY 4.0',
})

function page(offset: number, total: number, items = [track(1, 'Rainy Window')]) {
  return { items, total, limit: 50, offset }
}

const job = (overrides: Record<string, unknown> = {}) => ({
  id: 'j1',
  kind: 'ingest-jamendo',
  params: {},
  status: 'running',
  created_at: '2026-10-15T10:00:00Z',
  finished_at: null,
  cancel_requested: false,
  error: null,
  progress: null,
  ...overrides,
})

const REPORT = {
  seen: 10,
  new: 7,
  updated: 1,
  processed: 8,
  skipped: 1,
  failed: 1,
  failures: [{ source_id: '9', title: 'Broken Song', stage: 'analysis', message: 'decode error' }],
  failures_total: 1,
  elapsed_s: 12.5,
  aborted: null,
}

function baseRoutes(extra: Routes = {}): Routes {
  return {
    'GET /api/stats': STATS,
    'GET /api/tracks': page(0, 1),
    'GET /api/jobs': { jobs: [] },
    ...extra,
  }
}

function source(): FakeEventSource {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1]!
}

function bodyOf(mock: ReturnType<typeof stubApi>, path: string, method = 'POST') {
  const call = mock.mock.calls.find(([input, init]) => String(input) === path && init?.method === method)
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

beforeEach(() => {
  clearPersistentState()
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Library catalog overview and tracks', () => {
  it('shows the catalog numbers, with the risk as text', async () => {
    stubApi(baseRoutes())
    renderWithProviders(<LibraryPage />)
    expect(await screen.findByTestId('stat-tracks')).toHaveTextContent('120')
    const overview = screen.getByRole('region', { name: 'Catalog overview' })
    expect(within(overview).getByText('Jamendo')).toBeInTheDocument()
    expect(within(overview).getByText('Safe')).toBeInTheDocument()
    expect(within(overview).getByText('Check terms')).toBeInTheDocument()
    expect(overview).toHaveTextContent('90 analysed (75%)')
    expect(overview).toHaveTextContent('60 embedded with clap')
  })

  it('lists tracks and asks for the filter and page it needs', async () => {
    const user = userEvent.setup()
    const api = stubApi(
      baseRoutes({
        'GET /api/tracks': (url: URL) =>
          page(Number(url.searchParams.get('offset') ?? 0), 120, [
            track(Number(url.searchParams.get('offset') ?? 0) + 1, 'Song'),
          ]),
      }),
    )
    renderWithProviders(<LibraryPage />)
    const table = await screen.findByRole('table', { name: 'Tracks in the catalog' })
    expect(within(table).getByRole('button', { name: 'Show details of Song' })).toBeInTheDocument()
    expect(screen.getByText('1 to 1 of 120')).toBeInTheDocument()

    const urls = () => api.mock.calls.map(([input]) => String(input)).filter((u) => u.startsWith('/api/tracks'))
    expect(urls()[0]).toContain('limit=50')
    expect(urls()[0]).toContain('offset=0')

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(urls().some((u) => u.includes('offset=50'))).toBe(true))

    await user.selectOptions(screen.getByLabelText('Source'), 'local')
    await user.selectOptions(screen.getByLabelText('Licence risk'), 'amber')
    await waitFor(() => {
      const last = urls()[urls().length - 1]!
      expect(last).toContain('source=local')
      expect(last).toContain('risk=amber')
      expect(last).toContain('offset=0')
    })
  })

  it('plays a track from the table', async () => {
    const user = userEvent.setup()
    stubApi(baseRoutes())
    renderWithProviders(<LibraryPage />)
    await user.click(await screen.findByRole('button', { name: 'Play Rainy Window' }))
    expect(document.querySelector('audio')?.getAttribute('src')).toBe('/api/tracks/1/stream')
  })

  it('says so when the catalog is empty', async () => {
    stubApi(baseRoutes({ 'GET /api/tracks': page(0, 0, []) }))
    renderWithProviders(<LibraryPage />)
    expect(await screen.findByText(/The catalog is empty/)).toBeInTheDocument()
  })
})

describe('Library jobs', () => {
  it('starts a Jamendo ingest, follows it live and shows the report', async () => {
    const user = userEvent.setup()
    const api = stubApi(
      baseRoutes({ 'POST /api/ingest/jamendo': jsonResponse({ job: job() }, 202) }),
    )
    renderWithProviders(<LibraryPage />)
    await screen.findByTestId('stat-tracks')

    await user.type(screen.getByLabelText('Tags'), 'ambient, calm')
    await user.type(screen.getByLabelText('Search text (optional)'), 'rain')
    await user.selectOptions(screen.getByLabelText('Vocals'), 'instrumental')
    await user.click(screen.getByLabelText(/Only commercially usable licences/))
    await user.clear(screen.getByLabelText('Number of tracks'))
    await user.type(screen.getByLabelText('Number of tracks'), '25')
    await user.click(screen.getByRole('button', { name: 'Add from Jamendo' }))

    await waitFor(() =>
      expect(bodyOf(api, '/api/ingest/jamendo')).toEqual({
        tags: ['ambient', 'calm'],
        search: 'rain',
        vocalinstrumental: 'instrumental',
        commercial_only: true,
        limit: 25,
        embed: true,
      }),
    )

    const panel = await screen.findByRole('region', { name: 'Job progress' })
    expect(FakeEventSource.instances[0]!.url).toBe('/api/jobs/j1/events')
    expect(within(panel).getByRole('button', { name: 'Cancel job' })).toBeEnabled()

    source().emit('progress', { kind: 'track_done', index: 1, total: 4, title: 'Alpha Song', message: null })
    expect(within(panel).getByRole('progressbar', { name: 'Progress' })).toHaveAttribute('value', '1')
    expect(within(panel).getByRole('progressbar', { name: 'Progress' })).toHaveAttribute('max', '4')
    expect(panel).toHaveTextContent('1 of 4')
    expect(panel).toHaveTextContent('Alpha Song')
    source().emit('progress', { kind: 'track_skipped', index: 2, total: 4, title: 'Beta Song', message: null })
    source().emit('progress', { kind: 'track_failed', index: 3, total: 4, title: 'Gamma Song', message: 'x' })
    source().emit('warning', { message: 'embedding skipped: torch is not installed' })
    expect(panel).toHaveTextContent('embedding skipped: torch is not installed')
    expect(within(panel).getByText('Done:').parentElement).toHaveTextContent('Done: 1')
    expect(within(panel).getByText('Skipped:').parentElement).toHaveTextContent('Skipped: 1')
    expect(within(panel).getByText('Failed:').parentElement).toHaveTextContent('Failed: 1')

    const statsCalls = () => api.mock.calls.filter(([input]) => String(input) === '/api/stats').length
    expect(statsCalls()).toBe(1)
    source().emit('done', { report: REPORT })

    expect(await within(panel).findByText('Finished')).toBeInTheDocument()
    expect(panel).toHaveTextContent('Seen')
    expect(panel).toHaveTextContent('12.5 s')
    // The failures list is collapsed until opened.
    const failures = within(panel).getByText('Failures (1)').closest('details')!
    expect(failures).not.toHaveAttribute('open')
    expect(failures).toHaveTextContent('Broken Song (analysis): decode error')
    expect(source().closed).toBe(true)
    // The catalog numbers are loaded again.
    await waitFor(() => expect(statsCalls()).toBe(2))
    const tracksCalls = () => api.mock.calls.filter(([input]) => String(input).startsWith('/api/tracks')).length
    const before = tracksCalls()
    await user.click(within(panel).getByRole('button', { name: 'View new tracks' }))
    await waitFor(() => expect(tracksCalls()).toBeGreaterThan(before))
  })

  it('shows an indeterminate bar while the total is unknown', async () => {
    const user = userEvent.setup()
    stubApi(baseRoutes({ 'POST /api/ingest/reprocess': jsonResponse({ job: job({ kind: 'reprocess-tag' }) }, 202) }))
    renderWithProviders(<LibraryPage />)
    await user.click(await screen.findByRole('tab', { name: 'Maintenance' }))
    await user.click(screen.getByRole('button', { name: 'Re-tag catalog' }))
    const panel = await screen.findByRole('region', { name: 'Job progress' })
    source().emit('progress', { kind: 'track_done', index: 3, total: null, title: 'T', message: null })
    const bar = within(panel).getByRole('progressbar', { name: 'Progress' })
    expect(bar).not.toHaveAttribute('value')
    expect(panel).toHaveTextContent('3 so far')
  })

  it('starts the maintenance jobs with the right body', async () => {
    const user = userEvent.setup()
    const api = stubApi(baseRoutes({ 'POST /api/ingest/reprocess': jsonResponse({ job: job({ kind: 'reprocess-embed' }) }, 202) }))
    renderWithProviders(<LibraryPage />)
    await user.click(await screen.findByRole('tab', { name: 'Maintenance' }))
    await user.click(screen.getByRole('button', { name: 'Re-embed missing tracks' }))
    await waitFor(() => expect(bodyOf(api, '/api/ingest/reprocess')).toEqual({ what: 'embed' }))
  })

  it('shows the detail when maintenance cannot start (503)', async () => {
    const user = userEvent.setup()
    stubApi(
      baseRoutes({
        'POST /api/ingest/reprocess': jsonResponse({ detail: 'torch is not installed' }, 503),
      }),
    )
    renderWithProviders(<LibraryPage />)
    await user.click(await screen.findByRole('tab', { name: 'Maintenance' }))
    await user.click(screen.getByRole('button', { name: 'Re-embed missing tracks' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('torch is not installed')
  })

  it('cancels the running job once', async () => {
    const user = userEvent.setup()
    const api = stubApi(
      baseRoutes({
        'GET /api/jobs': { jobs: [job()] },
        'POST /api/jobs/j1/cancel': jsonResponse({ job: job({ cancel_requested: true }) }, 202),
      }),
    )
    renderWithProviders(<LibraryPage />)
    const cancel = await screen.findByRole('button', { name: 'Cancel job' })
    await user.click(cancel)
    await waitFor(() => expect(api.mock.calls.some(([u]) => String(u) === '/api/jobs/j1/cancel')).toBe(true))
    expect(await screen.findByRole('button', { name: 'Cancelling' })).toBeDisabled()
    expect(screen.getByText(/the job stops after the current track/)).toBeInTheDocument()

    source().emit('cancelled', { report: { ...REPORT, failures: [], failed: 0 } })
    expect(await screen.findByText('Cancelled', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel job' })).not.toBeInTheDocument()
  })

  it('reattaches to a job that is still running when the page opens', async () => {
    stubApi(
      baseRoutes({
        'GET /api/jobs': {
          jobs: [
            job({ id: 'j2', status: 'running', progress: { index: 2, total: 5 } }),
            job({ id: 'j0', status: 'done', finished_at: '2026-10-14T10:00:00Z' }),
          ],
        },
      }),
    )
    renderWithProviders(<LibraryPage />)
    const panel = await screen.findByRole('region', { name: 'Job progress' })
    expect(FakeEventSource.instances.map((s) => s.url)).toEqual(['/api/jobs/j2/events'])
    // The server replays the events: the panel is rebuilt from them.
    source().emit('progress', { kind: 'track_done', index: 1, total: 5, title: 'First', message: null })
    source().emit('progress', { kind: 'track_done', index: 2, total: 5, title: 'Second', message: null })
    expect(panel).toHaveTextContent('2 of 5')
    expect(panel).toHaveTextContent('Second')
    // The start buttons wait for it.
    expect(screen.getByRole('button', { name: 'Add from Jamendo' })).toBeDisabled()
    // The history lists both jobs.
    const history = screen.getByRole('table', { name: 'Recent jobs' })
    expect(within(history).getAllByRole('row')).toHaveLength(3)
  })

  it('explains a 409 and leads to the running job', async () => {
    const user = userEvent.setup()
    let polled = 0
    stubApi(
      baseRoutes({
        'GET /api/jobs': () => ({ jobs: polled++ === 0 ? [] : [job({ id: 'other' })] }),
        'POST /api/ingest/jamendo': jsonResponse({ detail: 'job other is already running' }, 409),
      }),
    )
    renderWithProviders(<LibraryPage />)
    await screen.findByTestId('stat-tracks')
    await user.click(screen.getByRole('button', { name: 'Add from Jamendo' }))
    expect(await screen.findByText('Another job is running')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show the running job' }))
    await screen.findByRole('region', { name: 'Job progress' })
    expect(source().url).toBe('/api/jobs/other/events')
  })

  it('links to Settings when the Jamendo client id is missing (503)', async () => {
    const user = userEvent.setup()
    stubApi(
      baseRoutes({
        'POST /api/ingest/jamendo': jsonResponse({ detail: 'Jamendo client id is not set' }, 503),
      }),
    )
    renderWithProviders(<LibraryPage />)
    await screen.findByTestId('stat-tracks')
    await user.click(screen.getByRole('button', { name: 'Add from Jamendo' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Jamendo client id is not set')
    expect(within(alert).getByRole('link', { name: 'Open Settings' })).toHaveAttribute('href', '#/settings')
  })

  it('refuses a limit outside 1 to 1000 without calling the backend', async () => {
    const user = userEvent.setup()
    const api = stubApi(baseRoutes())
    renderWithProviders(<LibraryPage />)
    await screen.findByTestId('stat-tracks')
    await user.clear(screen.getByLabelText('Number of tracks'))
    await user.type(screen.getByLabelText('Number of tracks'), '5000')
    await user.click(screen.getByRole('button', { name: 'Add from Jamendo' }))
    expect(screen.getByText('Enter a whole number from 1 to 1000.')).toBeInTheDocument()
    expect(bodyOf(api, '/api/ingest/jamendo')).toBeUndefined()
  })

  it('starts a local ingest and shows the backend detail on a 422', async () => {
    const user = userEvent.setup()
    const api = stubApi(
      baseRoutes({
        'POST /api/ingest/local': (_url: URL, init?: RequestInit) =>
          JSON.parse(String(init?.body)).path === 'D:\\Nope'
            ? jsonResponse({ detail: 'folder not found: D:\\Nope' }, 422)
            : jsonResponse({ job: job({ kind: 'ingest-local' }) }, 202),
      }),
    )
    renderWithProviders(<LibraryPage />)
    await user.click(await screen.findByRole('tab', { name: 'Local folder' }))
    expect(screen.getByText(/e\.g\. D:\\Music\\MyAssetPack/)).toBeInTheDocument()
    expect(screen.getByText(/mcrar-license\.toml/)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: 'Add from folder' })
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText('Folder path'), 'D:\\Nope')
    await user.click(submit)
    expect(await screen.findByRole('alert')).toHaveTextContent('folder not found: D:\\Nope')

    await user.clear(screen.getByLabelText('Folder path'))
    await user.type(screen.getByLabelText('Folder path'), 'D:\\Music\\Pack')
    await user.type(screen.getByLabelText('Licence (optional)'), 'CC0')
    await user.click(within(screen.getByRole('tabpanel', { name: 'Local folder' })).getByLabelText(/Also embed/))
    await user.click(submit)
    const posts = () =>
      api.mock.calls
        .filter(([u, init]) => String(u) === '/api/ingest/local' && init?.method === 'POST')
        .map(([, init]) => JSON.parse(String(init?.body)))
    await waitFor(() => expect(posts()).toHaveLength(2))
    expect(posts()[1]).toEqual({ path: 'D:\\Music\\Pack', license: 'CC0', embed: false })
  })

  it('falls back to the job record when the event stream breaks', async () => {
    stubApi(
      baseRoutes({
        'GET /api/jobs': { jobs: [job()] },
        'GET /api/jobs/j1': {
          job: job({ status: 'done', finished_at: 'x', event_count: 3, report: REPORT }),
        },
      }),
    )
    renderWithProviders(<LibraryPage />)
    await screen.findByRole('region', { name: 'Job progress' })
    const es = source()
    es.readyState = FakeEventSource.CLOSED
    act(() => {
      // An `error` event with a closed stream means the stream is gone for good.
      ;(es as unknown as { listeners: Map<string, ((e: Event) => void)[]> }).listeners
        .get('error')
        ?.forEach((listener) => listener(new Event('error')))
    })
    expect(await screen.findByText('Finished')).toBeInTheDocument()
    expect(screen.getByText('Report')).toBeInTheDocument()
  })
})
