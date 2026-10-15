import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearPersistentState } from '../../app/usePersistentState'
import { jsonResponse, stubApi } from '../../test/fetch'
import type { Routes } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import SearchPage from './index'

const VOCAB = {
  genre: [
    { id: 'rock', display: 'Rock', synonyms: [] },
    { id: 'dark-ambient', display: 'Dark Ambient', synonyms: [] },
  ],
  moodtheme: Array.from({ length: 15 }, (_, i) => ({ id: `mood${i}`, display: `Mood ${i}`, synonyms: [] })),
}

function item(id: number, overrides: Record<string, unknown> = {}) {
  return {
    track_id: id,
    title: `Track ${id}`,
    artist: `Artist ${id}`,
    source: 'jamendo',
    source_url: null,
    download_url: null,
    duration_s: 125,
    bpm: 98.2,
    key: 'C',
    mode: 'major',
    energy: 0.6,
    license_code: 'CC BY 4.0',
    risk: 'green',
    license_url: 'https://example.org/by',
    attribution_text: `Track ${id} by Artist ${id}`,
    commercial_license_url: null,
    top_tags: [{ label_set: 'genre', label: 'rock', display: 'Rock', score: 0.83 }],
    score: 0.9,
    breakdown: { semantic: { raw: 0.8, weight: 0.5, contribution: 0.4 } },
    explanation: `Because track ${id} fits`,
    rating: null,
    ...overrides,
  }
}

function response(items: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    items,
    total_candidates: items.length,
    parsed: {},
    relaxed: [],
    unembedded_count: 0,
    model_id: 'clap-test',
    elapsed_ms: 42,
    notes: [],
    ...overrides,
  }
}

function setup(routes: Routes) {
  return stubApi({ 'GET /api/vocab': VOCAB, 'GET /api/tracks/1': { id: 1 }, ...routes })
}

/** The JSON bodies sent to a route, in order. */
function bodies(mock: ReturnType<typeof stubApi>, route: string) {
  return mock.mock.calls
    .filter(([input, init]) => `${init?.method ?? 'GET'} ${new URL(String(input), 'http://x').pathname}` === route)
    .map(([, init]) => JSON.parse(String(init?.body)))
}

const box = () => screen.getByRole('textbox', { name: 'Describe the music you need' })
const searchButton = () => screen.getByRole('button', { name: 'Search' })

async function searchFor(text: string) {
  await userEvent.type(box(), text)
  await userEvent.click(searchButton())
}

beforeEach(() => {
  clearPersistentState()
})

describe('Search page: query', () => {
  it('sends the text with the default paging and shows the results', async () => {
    const mock = setup({ 'POST /api/search': response([item(1), item(2)]) })
    renderWithProviders(<SearchPage />)
    await searchFor('tense stealth level')
    expect(await screen.findByText('Track 1')).toBeInTheDocument()
    expect(screen.getByText('Track 2')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toEqual([
      { text: 'tense stealth level', filters: {}, limit: 20, offset: 0, explain: true },
    ])
    expect(screen.getByText('2 results of 2 candidates · clap-test · 42 ms')).toBeInTheDocument()
  })

  it('submits with Enter', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.type(box(), '8-bit boss{Enter}')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].text).toBe('8-bit boss')
  })

  it('asks for input instead of sending an empty search', async () => {
    const mock = setup({ 'POST /api/search': response([]) })
    renderWithProviders(<SearchPage />)
    await userEvent.click(searchButton())
    expect(screen.getByText('Describe the music you need, or pick at least one filter.')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toEqual([])
  })

  it('runs an example query when its chip is clicked', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.click(screen.getByRole('button', { name: '8-bit boss battle' }))
    await screen.findByText('Track 1')
    expect(box()).toHaveValue('8-bit boss battle')
    expect(bodies(mock, 'POST /api/search')[0].text).toBe('8-bit boss battle')
    expect(screen.queryByRole('button', { name: 'cozy town theme' })).not.toBeInTheDocument()
  })
})

describe('Search page: filters', () => {
  it('searches with filters alone', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await userEvent.click(searchButton())
    await screen.findByText('Track 1')
    const [body] = bodies(mock, 'POST /api/search')
    expect(body.text).toBeUndefined()
    expect(body.filters).toEqual({ genres: ['rock'] })
  })

  it('maps the safe toggle to max_risk green and hides the risk select', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    expect(screen.getByLabelText('Max licence risk')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('switch', { name: 'Safe for commercial game' }))
    expect(screen.queryByLabelText('Max licence risk')).not.toBeInTheDocument()
    await searchFor('rain')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].filters).toEqual({ max_risk: 'green' })
  })

  it('maps the max risk select when the toggle is off', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.selectOptions(screen.getByLabelText('Max licence risk'), 'amber')
    await searchFor('rain')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].filters).toEqual({ max_risk: 'amber' })
  })

  it('maps vocals, source, BPM, genres and moods', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await screen.findByRole('button', { name: 'Rock' })
    await userEvent.selectOptions(screen.getByLabelText('Vocals'), 'instrumental')
    await userEvent.selectOptions(screen.getByLabelText('Source'), 'local')
    await userEvent.type(screen.getByLabelText('Min BPM'), '80')
    await userEvent.type(screen.getByLabelText('Max BPM'), '100')
    await userEvent.click(screen.getByRole('button', { name: 'Dark Ambient' }))
    await userEvent.click(screen.getByRole('button', { name: 'Mood 3' }))
    await searchFor('calm')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].filters).toEqual({
      vocal: 'instrumental',
      sources: ['local'],
      bpm_min: 80,
      bpm_max: 100,
      genres: ['dark-ambient'],
      moods: ['mood3'],
    })
  })

  it.each([
    ['Jingle (under 15 s)', { duration_max_s: 15 }],
    ['Short (under 60 s)', { duration_max_s: 60 }],
    ['BGM (over 60 s)', { duration_min_s: 60 }],
  ])('maps the duration preset %s', async (option, expected) => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.selectOptions(screen.getByLabelText('Duration'), option)
    await searchFor('x')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].filters).toEqual(expected)
  })

  it('maps a custom duration range', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.selectOptions(screen.getByLabelText('Duration'), 'Custom')
    await userEvent.type(screen.getByLabelText('Min seconds'), '20')
    await userEvent.type(screen.getByLabelText('Max seconds'), '90')
    await searchFor('x')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].filters).toEqual({ duration_min_s: 20, duration_max_s: 90 })
  })

  it('does not send a search when a range is back to front', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.type(screen.getByLabelText('Min BPM'), '120')
    await userEvent.type(screen.getByLabelText('Max BPM'), '80')
    expect(screen.getByRole('alert')).toHaveTextContent('Min BPM must not exceed max BPM.')
    await searchFor('x')
    expect(bodies(mock, 'POST /api/search')).toEqual([])
  })

  it('shows the first moods and the rest on request', async () => {
    setup({})
    renderWithProviders(<SearchPage />)
    expect(await screen.findByRole('button', { name: 'Mood 11' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mood 12' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show all 15' }))
    expect(screen.getByRole('button', { name: 'Mood 14' })).toBeInTheDocument()
  })

  it('clears the filters', async () => {
    setup({})
    renderWithProviders(<SearchPage />)
    const rock = await screen.findByRole('button', { name: 'Rock' })
    await userEvent.click(rock)
    await userEvent.selectOptions(screen.getByLabelText('Vocals'), 'vocal')
    expect(screen.getByRole('button', { name: 'Filters (2)' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByRole('button', { name: 'Rock' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByLabelText('Vocals')).toHaveValue('')
  })
})

describe('Search page: results', () => {
  it('shows track facts, tags, explanation and the licence', async () => {
    setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    const row = await screen.findByRole('article', { name: 'Track 1' })
    expect(within(row).getByText('by Artist 1')).toBeInTheDocument()
    expect(within(row).getByText('2:05')).toBeInTheDocument()
    expect(within(row).getByText('98 BPM')).toBeInTheDocument()
    expect(within(row).getByText('C major')).toBeInTheDocument()
    expect(within(row).getByRole('img', { name: 'Energy 60%' })).toBeInTheDocument()
    expect(within(row).getByText('Rock 83%')).toBeInTheDocument()
    expect(within(row).getByText('Because track 1 fits')).toBeInTheDocument()
    expect(within(row).getByText('Safe')).toBeInTheDocument()
  })

  it('expands the score breakdown', async () => {
    setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    const row = await screen.findByRole('article', { name: 'Track 1' })
    expect(within(row).queryByText('Matches the description')).not.toBeInTheDocument()
    await userEvent.click(within(row).getByRole('button', { name: 'Why this result' }))
    expect(within(row).getAllByText(/Matches the description/).length).toBeGreaterThan(0)
  })

  it('loads more results with an offset and appends them', async () => {
    const mock = setup({
      'POST /api/search': (_url: URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body))
        const first = body.offset === 0
        return response(first ? [item(1), item(2)] : [item(3)], { total_candidates: 3 })
      },
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    await screen.findByText('Track 2')
    expect(screen.getByText('2 results of 3 candidates · clap-test · 42 ms')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('Track 3')).toBeInTheDocument()
    expect(screen.getByText('Track 1')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search').map((b) => b.offset)).toEqual([0, 2])
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })

  it('loads more with the submitted query, not the edited form', async () => {
    const mock = setup({
      'POST /api/search': (_url: URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body))
        return response(body.offset === 0 ? [item(1)] : [item(2)], { total_candidates: 2 })
      },
    })
    renderWithProviders(<SearchPage />)
    await searchFor('first')
    await screen.findByText('Track 1')
    await userEvent.type(box(), ' edited')
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await screen.findByText('Track 2')
    expect(bodies(mock, 'POST /api/search').map((b) => b.text)).toEqual(['first', 'first'])
  })

  it('shows relaxed, note and unembedded notices', async () => {
    setup({
      'POST /api/search': response([item(1)], {
        relaxed: ['dropped the BPM range', 'dropped the vocal filter'],
        notes: ['3 matching track(s) have no embedding'],
        unembedded_count: 3,
      }),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    expect(
      await screen.findByText('No exact matches, so we relaxed: dropped the BPM range; dropped the vocal filter'),
    ).toBeInTheDocument()
    expect(screen.getByText('3 matching track(s) have no embedding')).toBeInTheDocument()
    expect(screen.getByText("3 tracks aren't embedded yet and can't match text.")).toBeInTheDocument()
  })

  it('shows an empty state with a hint', async () => {
    setup({ 'POST /api/search': response([]) })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    expect(await screen.findByText('No tracks match')).toBeInTheDocument()
    expect(screen.getByText(/Try fewer or looser filters/)).toBeInTheDocument()
  })

  it('always shows the licence disclaimer', () => {
    setup({})
    renderWithProviders(<SearchPage />)
    expect(screen.getByText(/guidance, not legal advice/)).toBeInTheDocument()
  })

  it('opens the track drawer from the title', async () => {
    setup({
      'POST /api/search': response([item(1)]),
      'GET /api/tracks/1': {
        id: 1,
        title: 'Track 1',
        artist: 'Artist 1',
        album: null,
        source: 'jamendo',
        source_url: null,
        local_path: null,
        duration_s: 125,
        vocal_instrumental: null,
        features: null,
        tags: [],
        license: { code: 'CC BY 4.0', url: null, risk: 'green', attribution_text: null, commercial_license_url: null },
      },
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    await userEvent.click(await screen.findByRole('button', { name: 'Track 1' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Licence' })).toBeInTheDocument()
  })
})

describe('Search page: errors', () => {
  it('explains a missing ML extra on 503', async () => {
    setup({ 'POST /api/search': jsonResponse({ detail: 'text search needs the ml extra' }, 503) })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Text search is not available')
    expect(alert).toHaveTextContent('text search needs the ml extra')
  })

  it('falls back to the standard 503 text without a detail', async () => {
    setup({ 'POST /api/search': new Response('', { status: 503 }) })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Text search needs the ML extra (torch). Filter-only search still works.',
    )
  })

  it('shows the 422 detail next to the form', async () => {
    setup({ 'POST /api/search': jsonResponse({ detail: 'bpm_min must not exceed bpm_max' }, 422) })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    expect(await screen.findByText('bpm_min must not exceed bpm_max')).toBeInTheDocument()
    expect(box()).toHaveAttribute('aria-invalid', 'true')
  })
})

describe('Search page: ratings', () => {
  it('rates with the submitted text and filters, not the edited form', async () => {
    const mock = setup({
      'POST /api/search': response([item(1)]),
      'PUT /api/ratings': { query_key: 'k', track_id: 1, rating: 2 },
    })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await searchFor('cozy town')
    const row = await screen.findByRole('article', { name: 'Track 1' })
    // Edit the form after the search: the rating must still use the submitted query.
    await userEvent.type(box(), ' CHANGED')
    await userEvent.click(screen.getByRole('button', { name: 'Dark Ambient' }))
    await userEvent.click(within(row).getByRole('button', { name: 'Good fit' }))
    expect(within(row).getByRole('button', { name: 'Good fit' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(bodies(mock, 'PUT /api/ratings')).toHaveLength(1))
    expect(bodies(mock, 'PUT /api/ratings')[0]).toEqual({
      text: 'cozy town',
      filters: { genres: ['rock'] },
      track_id: 1,
      rating: 2,
    })
  })

  it('shows the stored rating and clears it with deleteRating', async () => {
    const mock = setup({
      'POST /api/search': response([item(1, { rating: 1 })]),
      'DELETE /api/ratings': new Response(null, { status: 204 }),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    const row = await screen.findByRole('article', { name: 'Track 1' })
    const ok = within(row).getByRole('button', { name: 'OK' })
    expect(ok).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(ok)
    expect(ok).toHaveAttribute('aria-pressed', 'false')
    await waitFor(() => expect(bodies(mock, 'DELETE /api/ratings')).toHaveLength(1))
    expect(bodies(mock, 'DELETE /api/ratings')[0]).toEqual({ text: 'cozy town', filters: {}, track_id: 1 })
  })

  it('rolls back and shows a toast when saving the rating fails', async () => {
    setup({
      'POST /api/search': response([item(1, { rating: 1 })]),
      'PUT /api/ratings': jsonResponse({ detail: 'database is locked' }, 500),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    const row = await screen.findByRole('article', { name: 'Track 1' })
    await userEvent.click(within(row).getByRole('button', { name: 'Good fit' }))
    expect(await screen.findByText(/Couldn't save the rating: database is locked/)).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'OK' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(row).getByRole('button', { name: 'Good fit' })).toHaveAttribute('aria-pressed', 'false')
  })
})

describe('Search page: download and play', () => {
  it('shows Download only for tracks with a download_url', async () => {
    setup({
      'POST /api/search': response([
        item(1, { download_url: 'https://example.org/dl/1' }),
        item(2),
      ]),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    const first = await screen.findByRole('article', { name: 'Track 1' })
    const second = screen.getByRole('article', { name: 'Track 2' })
    expect(within(first).getByRole('button', { name: /^Download/ })).toBeInTheDocument()
    expect(within(second).queryByRole('button', { name: /^Download/ })).not.toBeInTheDocument()
  })

  it('opens the download page and saves the licence file', async () => {
    setup({
      'POST /api/search': response([item(1, { download_url: 'https://example.org/dl/1' })]),
    })
    const open = vi.fn()
    vi.stubGlobal('open', open)
    const clicked: { href: string; download: string }[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.getAttribute('href') ?? '', download: this.getAttribute('download') ?? 'none' })
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    await userEvent.click(await screen.findByRole('button', { name: /^Download/ }))
    expect(open).toHaveBeenCalledWith('https://example.org/dl/1', '_blank', 'noopener')
    expect(clicked).toEqual([{ href: '/api/tracks/1/credits?format=txt', download: '' }])
  })

  it('plays the track through the player and shows the playing state', async () => {
    setup({ 'POST /api/search': response([item(7)]) })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    const row = await screen.findByRole('article', { name: 'Track 7' })
    await userEvent.click(within(row).getByRole('button', { name: 'Play Track 7' }))
    expect(document.querySelector('audio')?.getAttribute('src')).toBe('/api/tracks/7/stream')
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled()
    expect(await within(row).findByRole('button', { name: 'Pause Track 7' })).toBeInTheDocument()
  })
})

describe('Search page: persistent state', () => {
  it('keeps the query, filters and results when the page is left and opened again', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    const first = renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    first.unmount()

    renderWithProviders(<SearchPage />)
    expect(box()).toHaveValue('cozy town')
    expect(await screen.findByRole('button', { name: 'Rock' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Track 1')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toHaveLength(1)
  })
})
