import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearPersistentState, usePersistentState } from '../../app/usePersistentState'
import { FakeEventSource } from '../../test/eventSource'
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
  scene: [
    { id: 'combat', display: 'Combat', synonyms: [] },
    { id: 'stealth', display: 'Stealth', synonyms: [] },
  ],
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

const LLM_NOT_READY = {
  enabled: false,
  ready: false,
  preset: 'deepseek',
  label: 'DeepSeek',
  kind: 'openai',
  model: 'deepseek-chat',
  reason: 'disabled',
}
const LLM_READY = { ...LLM_NOT_READY, enabled: true, ready: true, reason: null, rerank_top_n: 20 }

function setup(routes: Routes) {
  return stubApi({
    'GET /api/vocab': VOCAB,
    'GET /api/tracks/1': { id: 1 },
    'GET /api/llm': LLM_NOT_READY,
    ...routes,
  })
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
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
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

  it('maps game scenes and intensity', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    const group = await screen.findByRole('group', { name: 'Game scene' })
    expect(within(group).getAllByRole('button').map((chip) => chip.textContent)).toEqual(['Combat', 'Stealth'])
    await userEvent.click(within(group).getByRole('button', { name: 'Stealth' }))
    await userEvent.click(within(group).getByRole('button', { name: 'Combat' }))
    await userEvent.selectOptions(screen.getByLabelText('Intensity'), 'High')
    await searchFor('sneaking')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].filters).toEqual({ scenes: ['stealth', 'combat'], intensity: 'high' })
  })

  it('leaves scenes and intensity out when they are not set', async () => {
    const mock = setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await screen.findByRole('group', { name: 'Game scene' })
    await searchFor('rain')
    await screen.findByText('Track 1')
    expect(bodies(mock, 'POST /api/search')[0].filters).toEqual({})
  })

  it('shows a scene tag of a result by its display name', async () => {
    setup({
      'POST /api/search': response([
        item(1, { top_tags: [{ label_set: 'scene', label: 'combat', display: 'Combat', score: 0.9 }] }),
      ]),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    expect(await screen.findByText('Combat 90%')).toBeInTheDocument()
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
    await userEvent.click(screen.getByRole('button', { name: 'Combat' }))
    expect(screen.getByRole('button', { name: 'Filters (3)' })).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Intensity'), 'Low')
    expect(screen.getByRole('button', { name: 'Filters (4)' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByRole('button', { name: 'Rock' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Combat' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByLabelText('Vocals')).toHaveValue('')
    expect(screen.getByLabelText('Intensity')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Filters' })).toBeInTheDocument()
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

describe('Search page: Jamendo import', () => {
  const WEAK = { top_cosine: 0.12, weak: true }
  const FINE = { top_cosine: 0.5, weak: false }
  const importJob = (overrides: Record<string, unknown> = {}) => ({
    id: 'j1',
    kind: 'ingest-query',
    params: { text: 'cozy town', limit: 50 },
    status: 'running',
    created_at: '2026-10-15T10:00:00Z',
    finished_at: null,
    cancel_requested: false,
    error: null,
    progress: null,
    ...overrides,
  })
  const REPORT = {
    seen: 50,
    new: 2,
    updated: 0,
    processed: 2,
    skipped: 0,
    failed: 0,
    failures: [],
    failures_total: 0,
    elapsed_s: 100,
    aborted: null,
    new_track_ids: [3, 4],
  }
  const NOTICE = 'Few close matches in your library.'
  const action = { name: 'Search Jamendo for more' }
  const source = () => FakeEventSource.instances[FakeEventSource.instances.length - 1]!
  const progressRegion = { name: 'Job progress' }

  /** First search answers with track 1, a search after the import with tracks 1, 3 and 4. */
  function twoStageSearch(match: unknown = WEAK) {
    let calls = 0
    return {
      'POST /api/search': () => {
        calls += 1
        return calls === 1
          ? response([item(1)], { match })
          : response([item(1), item(3), item(4)], { match: FINE })
      },
    }
  }

  /** Searches for "cozy town" and clicks the first Jamendo button. */
  async function startImport() {
    await searchFor('cozy town')
    await userEvent.click((await screen.findAllByRole('button', action))[0]!)
    await screen.findByRole('region', progressRegion)
  }

  it('offers the import in a notice only when the best match is weak', async () => {
    setup({ 'POST /api/search': response([item(1)], { match: WEAK }) })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    expect(await screen.findByText(new RegExp(NOTICE))).toBeInTheDocument()
    // The notice carries the only import button; the quiet one would repeat it.
    expect(screen.getAllByRole('button', action)).toHaveLength(1)
  })

  it('shows only the quiet button when the match is not weak', async () => {
    setup({ 'POST /api/search': response([item(1)], { match: FINE }) })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    expect(screen.queryByText(new RegExp(NOTICE))).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', action)).toHaveLength(1)
  })

  it('treats a response without match as not weak, and still offers the button', async () => {
    setup({ 'POST /api/search': response([item(1)]) })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    expect(screen.queryByText(new RegExp(NOTICE))).not.toBeInTheDocument()
    expect(screen.getByRole('button', action)).toBeInTheDocument()
  })

  it('offers the quiet button on an empty result of a text search', async () => {
    setup({ 'POST /api/search': response([]) })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('No tracks match')
    expect(screen.getByRole('button', action)).toBeInTheDocument()
  })

  it('offers nothing for a filter-only search', async () => {
    setup({ 'POST /api/search': response([item(1)], { match: WEAK }) })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await userEvent.click(searchButton())
    await screen.findByText('Track 1')
    expect(screen.queryByText(new RegExp(NOTICE))).not.toBeInTheDocument()
    expect(screen.queryByRole('button', action)).not.toBeInTheDocument()
  })

  it('starts the import with the text and filters of the search shown', async () => {
    const mock = setup({
      'POST /api/search': response([item(1)], { match: WEAK }),
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
    })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    // Edit the form after the search: the import must use the search shown.
    await userEvent.type(box(), ' CHANGED')
    await userEvent.click(screen.getAllByRole('button', action)[0]!)
    expect(await screen.findByRole('region', progressRegion)).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search/import')).toEqual([
      { text: 'cozy town', filters: { genres: ['rock'] }, limit: 50 },
    ])
    expect(screen.getByText('Searching Jamendo for "cozy town"')).toBeInTheDocument()
    // Another import cannot start while this one runs.
    expect(screen.queryByRole('button', action)).not.toBeInTheDocument()
    expect(source().url).toBe('/api/jobs/j1/events')
  })

  it('shows progress and cancels the job', async () => {
    const mock = setup({
      'POST /api/search': response([item(1)], { match: WEAK }),
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
      'POST /api/jobs/j1/cancel': { job: importJob({ cancel_requested: true }) },
    })
    renderWithProviders(<SearchPage />)
    await startImport()
    source().emit('progress', { kind: 'track_done', index: 12, total: 50, title: 'Rain on Glass', message: null })
    expect(screen.getByText('12 of 50')).toBeInTheDocument()
    expect(screen.getByText('Rain on Glass')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Progress' })).toHaveAttribute('value', '12')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(mock.mock.calls.some(([url]) => String(url) === '/api/jobs/j1/cancel')).toBe(true))
    expect(screen.getByRole('button', { name: 'Cancelling' })).toBeDisabled()
  })

  it('runs the search again when the job is done and marks the new tracks', async () => {
    const mock = setup({
      ...twoStageSearch(),
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
    })
    renderWithProviders(<SearchPage />)
    await startImport()
    await userEvent.type(box(), ' CHANGED')
    source().emit('done', { report: REPORT })

    expect(await screen.findByText('Added 2 tracks from Jamendo')).toBeInTheDocument()
    expect(screen.queryByRole('region', progressRegion)).not.toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toEqual([
      { text: 'cozy town', filters: {}, limit: 20, offset: 0, explain: true },
      { text: 'cozy town', filters: {}, limit: 20, offset: 0, explain: true },
    ])
    expect(within(screen.getByRole('article', { name: 'Track 3' })).getByText('New')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'Track 4' })).getByText('New')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'Track 1' })).queryByText('New')).not.toBeInTheDocument()
    // The weak notice is gone; the quiet button stays for another try.
    expect(screen.queryByText(new RegExp(NOTICE))).not.toBeInTheDocument()
    expect(screen.getByRole('button', action)).toBeInTheDocument()
  })

  it('says so when Jamendo had nothing new', async () => {
    setup({
      ...twoStageSearch(),
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
    })
    renderWithProviders(<SearchPage />)
    await startImport()
    source().emit('done', { report: { ...REPORT, new: 0, new_track_ids: [] } })
    expect(await screen.findByText('No new tracks found on Jamendo for this search')).toBeInTheDocument()
  })

  it('shows the results of a cancelled job that added tracks', async () => {
    setup({
      ...twoStageSearch(),
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
    })
    renderWithProviders(<SearchPage />)
    await startImport()
    source().emit('cancelled', { report: REPORT })
    expect(await screen.findByText('Added 2 tracks from Jamendo')).toBeInTheDocument()
  })

  it('shows the error of a failed job and keeps the results', async () => {
    const mock = setup({
      'POST /api/search': response([item(1)], { match: WEAK }),
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
    })
    renderWithProviders(<SearchPage />)
    await startImport()
    source().emit('failed', { report: null, error: 'Jamendo is down' })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The Jamendo search failed')
    expect(alert).toHaveTextContent('Jamendo is down')
    expect(screen.getByText('Track 1')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toHaveLength(1)
    expect(screen.getAllByRole('button', action).length).toBeGreaterThan(0)
  })

  it('points to the Library when another job is running', async () => {
    setup({
      'POST /api/search': response([item(1)], { match: WEAK }),
      'POST /api/search/import': jsonResponse({ detail: 'another job is running' }, 409),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click((await screen.findAllByRole('button', action))[0]!)
    expect(await screen.findByText('Another job is running')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Library' })).toHaveAttribute('href', '#/library')
  })

  it('points to Settings when the Jamendo client id is missing', async () => {
    setup({
      'POST /api/search': response([item(1)], { match: WEAK }),
      'POST /api/search/import': jsonResponse({ detail: 'Jamendo client id is not set' }, 503),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click((await screen.findAllByRole('button', action))[0]!)
    expect(await screen.findByText('Jamendo client id is not set')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Settings' })).toHaveAttribute('href', '#/settings')
  })

  it('shows any other start error as a message', async () => {
    setup({
      'POST /api/search': response([item(1)], { match: WEAK }),
      'POST /api/search/import': jsonResponse({ detail: 'nothing to describe' }, 422),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click((await screen.findAllByRole('button', action))[0]!)
    expect(await screen.findByText("Couldn't start the job")).toBeInTheDocument()
    expect(screen.getByText('nothing to describe')).toBeInTheDocument()
  })

  it('hides the finished import of an old search when a new search runs', async () => {
    setup({
      ...twoStageSearch(),
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
    })
    renderWithProviders(<SearchPage />)
    await startImport()
    source().emit('done', { report: REPORT })
    await screen.findByText('Added 2 tracks from Jamendo')
    await userEvent.clear(box())
    await searchFor('another')
    await waitFor(() => expect(screen.queryByText('Added 2 tracks from Jamendo')).not.toBeInTheDocument())
    expect(screen.queryByText('New')).not.toBeInTheDocument()
  })

  it('keeps a running import on screen when another search runs, and leaves those results alone', async () => {
    let calls = 0
    const mock = setup({
      'POST /api/search': () => {
        calls += 1
        return response([item(calls)], { match: WEAK })
      },
      'POST /api/search/import': jsonResponse({ job: importJob() }, 202),
    })
    renderWithProviders(<SearchPage />)
    await startImport()
    await userEvent.clear(box())
    await searchFor('another')
    await screen.findByText('Track 2')
    expect(screen.getByRole('region', progressRegion)).toBeInTheDocument()
    expect(screen.queryByRole('button', action)).not.toBeInTheDocument()

    source().emit('done', { report: REPORT })
    expect(await screen.findByText(/Added 2 tracks from Jamendo for "cozy town"/)).toBeInTheDocument()
    expect(screen.getByText('Track 2')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toHaveLength(2)
    expect((await screen.findAllByRole('button', action)).length).toBeGreaterThan(0)
  })

  it('reattaches to a running import for the search shown', async () => {
    setup({
      ...twoStageSearch(),
      'GET /api/jobs': {
        jobs: [
          importJob({ id: 'other', params: { text: 'something else', limit: 50 } }),
          importJob({ id: 'j9' }),
        ],
      },
    })
    const first = renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    first.unmount()
    FakeEventSource.instances = []

    renderWithProviders(<SearchPage />)
    expect(await screen.findByRole('region', progressRegion)).toBeInTheDocument()
    expect(screen.queryByRole('button', action)).not.toBeInTheDocument()
    expect(source().url).toBe('/api/jobs/j9/events')
    source().emit('done', { report: REPORT })
    expect(await screen.findByText('Added 2 tracks from Jamendo')).toBeInTheDocument()
    expect(screen.getByText('Track 3')).toBeInTheDocument()
  })

  it('does not reattach to a running import for another search', async () => {
    setup({
      'POST /api/search': response([item(1)], { match: FINE }),
      'GET /api/jobs': { jobs: [importJob({ params: { text: 'something else', limit: 50 } })] },
    })
    const first = renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    first.unmount()
    renderWithProviders(<SearchPage />)
    expect(await screen.findByRole('button', action)).toBeInTheDocument()
    expect(screen.queryByRole('region', progressRegion)).not.toBeInTheDocument()
  })
})

describe('Search page: how the search was read', () => {
  const read = () => screen.getByText(/^How your search was read/)
  const LLM_USED = { used: true, model: 'deepseek-chat', cached: false, error: null }

  it('says the rules read the query and shows the parsed query', async () => {
    setup({
      'POST /api/search': response([item(1)], {
        parsed: { source: 'rules', search_terms: [], notes: ['Read "no vocals" as instrumental'], semantic_text: 'calm' },
        notes: ['Read "no vocals" as instrumental'],
      }),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('calm, no vocals')
    await screen.findByText('Track 1')
    expect(read()).toHaveTextContent('Read by rules')
    expect(read()).not.toHaveTextContent('LLM')
    const details = read().closest('details')!
    expect(details).not.toHaveAttribute('open')
    await userEvent.click(read())
    expect(details).toHaveAttribute('open')
    // The note is listed here and, as before, shown as a notice.
    expect(within(details).getByRole('listitem')).toHaveTextContent('Read "no vocals" as instrumental')
    expect(details.querySelector('pre')).toHaveTextContent('"semantic_text": "calm"')
    expect(details.querySelector('pre')).toHaveTextContent('"source": "rules"')
    expect(screen.getAllByText('Read "no vocals" as instrumental')).toHaveLength(2)
  })

  it('says the LLM read the query, with the model and the cached marker', async () => {
    const mock = setup({
      'POST /api/search': response([item(1)], {
        parsed: { source: 'llm', search_terms: ['stealth', 'ambient drone'], notes: [], semantic_text: 'tense' },
        llm: { ...LLM_USED, cached: true },
      }),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('tense stealth')
    await screen.findByText('Track 1')
    expect(read()).toHaveTextContent('Read by LLM (deepseek-chat) · cached')
    await userEvent.click(read())
    expect(screen.getByText('Jamendo search terms: stealth, ambient drone')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')[0]).toEqual({
      text: 'tense stealth',
      filters: {},
      limit: 20,
      offset: 0,
      explain: true,
    })
  })

  it('leaves out the cached marker for a fresh LLM reading', async () => {
    setup({
      'POST /api/search': response([item(1)], { parsed: { source: 'llm' }, llm: LLM_USED }),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    await screen.findByText('Track 1')
    expect(read()).toHaveTextContent('Read by LLM (deepseek-chat)')
    expect(read()).not.toHaveTextContent('cached')
  })

  it('explains a fallback to the rules inside the details', async () => {
    setup({
      'POST /api/search': response([item(1)], {
        parsed: { source: 'rules', notes: ['The LLM did not answer in time.'] },
        llm: { used: false, model: 'deepseek-chat', cached: false, error: 'Timed out after 10 s.' },
      }),
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    await screen.findByText('Track 1')
    expect(read()).toHaveTextContent('Read by rules')
    expect(
      screen.getByText('The LLM could not read this search, so rules were used: Timed out after 10 s.'),
    ).toBeInTheDocument()
  })

  it('keeps the first page reading when more results are loaded', async () => {
    setup({
      'POST /api/search': (_url: URL, init?: RequestInit) => {
        const first = JSON.parse(String(init?.body)).offset === 0
        return first
          ? response([item(1)], { total_candidates: 2, parsed: { source: 'llm' }, llm: LLM_USED })
          : response([item(2)], { total_candidates: 2, parsed: { source: 'rules' }, llm: null })
      },
    })
    renderWithProviders(<SearchPage />)
    await searchFor('x')
    await screen.findByText('Track 1')
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await screen.findByText('Track 2')
    expect(read()).toHaveTextContent('Read by LLM (deepseek-chat)')
  })
})

describe('Search page: rerank with the LLM', () => {
  const VERDICT = {
    model: 'deepseek-chat',
    verdict: 'good',
    summary: 'The first two fit the brief.',
    search_terms: [],
    elapsed_ms: 900,
  }
  const rerankButton = () => screen.queryByRole('button', { name: /Rerank top/ })
  const order = () => screen.getAllByRole('article').map((row) => row.getAttribute('aria-label'))
  /** The LLM puts track 3 first, then 1, and leaves track 2 out. */
  const reranked = (overrides: Record<string, unknown> = {}) =>
    response(
      [
        item(3, { llm_rank: 1, llm_explanation: 'Closest to the brief.' }),
        item(1, { llm_rank: 2, llm_explanation: null }),
      ],
      { rerank: VERDICT, ...overrides },
    )
  const found = () => response([item(1), item(2), item(3)], { match: { top_cosine: 0.5, weak: false } })

  it('offers nothing while the LLM is not ready', async () => {
    setup({ 'POST /api/search': found() })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    expect(rerankButton()).not.toBeInTheDocument()
  })

  it('offers nothing when the status cannot be read', async () => {
    setup({ 'POST /api/search': found(), 'GET /api/llm': jsonResponse({ detail: 'boom' }, 500) })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 1')
    expect(rerankButton()).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('offers nothing for a search without text', async () => {
    setup({ 'POST /api/search': found(), 'GET /api/llm': LLM_READY })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await userEvent.click(searchButton())
    await screen.findByText('Track 1')
    expect(rerankButton()).not.toBeInTheDocument()
  })

  it('names the number of results to rerank, or says "results" without it', async () => {
    setup({ 'POST /api/search': found(), 'GET /api/llm': LLM_READY })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    expect(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' })).toBeInTheDocument()
    cleanup()
    clearPersistentState()

    const { rerank_top_n: _omitted, ...older } = LLM_READY
    setup({ 'POST /api/search': found(), 'GET /api/llm': older })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    expect(await screen.findByRole('button', { name: 'Rerank top results with LLM' })).toBeInTheDocument()
  })

  it('offers nothing when there are no results', async () => {
    setup({ 'POST /api/search': response([]), 'GET /api/llm': LLM_READY })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('No tracks match')
    expect(rerankButton()).not.toBeInTheDocument()
  })

  it('sends the same body, reorders, explains and can be undone', async () => {
    const mock = setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': reranked(),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 3')
    expect(order()).toEqual(['Track 1', 'Track 2', 'Track 3'])
    expect(screen.queryByText(/^LLM:/)).not.toBeInTheDocument()

    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    expect(await screen.findByText('Reranked by deepseek-chat: The first two fit the brief.')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search/rerank')).toEqual(bodies(mock, 'POST /api/search'))
    // The LLM's order first, then the shown track it left out.
    expect(order()).toEqual(['Track 3', 'Track 1', 'Track 2'])
    const first = screen.getByRole('article', { name: 'Track 3' })
    expect(within(first).getByText('LLM:')).toBeInTheDocument()
    expect(first).toHaveTextContent('Closest to the brief.')
    // The template explanation stays.
    expect(first).toHaveTextContent('Because track 3 fits')
    expect(screen.getAllByText('LLM:')).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(order()).toEqual(['Track 1', 'Track 2', 'Track 3'])
    expect(screen.queryByText(/^Reranked by/)).not.toBeInTheDocument()
    expect(screen.queryByText('LLM:')).not.toBeInTheDocument()
  })

  it('keeps pages loaded after a rerank when it is undone', async () => {
    setup({
      'POST /api/search': (_url: URL, init?: RequestInit) =>
        JSON.parse(String(init?.body)).offset === 0
          ? response([item(1), item(2), item(3)], { total_candidates: 4 })
          : response([item(4)], { total_candidates: 4 }),
      'POST /api/search/rerank': reranked(),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    await screen.findByText(/^Reranked by/)
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await screen.findByText('Track 4')
    expect(order()).toEqual(['Track 3', 'Track 1', 'Track 2', 'Track 4'])

    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(order()).toEqual(['Track 1', 'Track 2', 'Track 3', 'Track 4'])
  })

  it('shows progress and blocks a second click while it runs', async () => {
    let release!: (value: unknown) => void
    const pending = new Promise((resolve) => {
      release = resolve
    })
    const mock = setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': () => pending,
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    const busy = await screen.findByRole('button', { name: 'Reranking' })
    expect(busy).toBeDisabled()
    await userEvent.click(busy)
    release(reranked())
    expect(await screen.findByText(/^Reranked by/)).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search/rerank')).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Rerank top 20 with LLM' })).toBeEnabled()
  })

  it('suggests the Jamendo import when the LLM calls the list poor', async () => {
    setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': reranked({ rerank: { ...VERDICT, verdict: 'poor', summary: 'Nothing fits.' } }),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await screen.findByText('Track 3')
    // A fine match: only the quiet import button, no notice.
    expect(screen.queryByText(/Few close matches/)).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    expect(await screen.findByText(/Few close matches in your library/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Search Jamendo for more' })).toHaveLength(1)
  })

  it('does not suggest the import for a good verdict', async () => {
    setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': reranked(),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    await screen.findByText(/^Reranked by/)
    expect(screen.queryByText(/Few close matches/)).not.toBeInTheDocument()
  })

  it('links to Settings when no LLM is configured (503)', async () => {
    setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': jsonResponse({ detail: 'No LLM is configured. Set one up in Settings.' }, 503),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    const notice = (await screen.findByText('No LLM is configured')).closest('[role="status"]')!
    expect(within(notice as HTMLElement).getByRole('link', { name: 'Open Settings' })).toHaveAttribute(
      'href',
      '#/settings',
    )
    // The list stays as it was.
    expect(order()).toEqual(['Track 1', 'Track 2', 'Track 3'])
  })

  it('shows the server text when the LLM call fails (502)', async () => {
    setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': jsonResponse({ detail: 'Timed out after 30 s.' }, 502),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    expect(await screen.findByText('Timed out after 30 s.')).toBeInTheDocument()
    expect(screen.queryByText(/^Reranked by/)).not.toBeInTheDocument()
    expect(order()).toEqual(['Track 1', 'Track 2', 'Track 3'])
    // It can be tried again.
    expect(screen.getByRole('button', { name: 'Rerank top 20 with LLM' })).toBeEnabled()
  })

  it('shows any other failure as an error', async () => {
    setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': jsonResponse({}, 500),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't rerank")
    expect(screen.getByRole('alert')).toHaveTextContent('The request failed (HTTP 500)')
  })

  it('clears the rerank when a new search runs', async () => {
    setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': reranked(),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    await screen.findByText(/^Reranked by/)
    await userEvent.click(searchButton())
    await waitFor(() => expect(screen.queryByText(/^Reranked by/)).not.toBeInTheDocument())
    expect(order()).toEqual(['Track 1', 'Track 2', 'Track 3'])
    expect(screen.queryByText('LLM:')).not.toBeInTheDocument()
  })

  it('drops a rerank that is still running when a new search runs', async () => {
    let release!: (value: unknown) => void
    const pending = new Promise((resolve) => {
      release = resolve
    })
    setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': () => pending,
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    await screen.findByRole('button', { name: 'Reranking' })
    await userEvent.click(searchButton())
    expect(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' })).toBeEnabled()
    release(reranked())
    await waitFor(() => expect(order()).toEqual(['Track 1', 'Track 2', 'Track 3']))
    expect(screen.queryByText(/^Reranked by/)).not.toBeInTheDocument()
  })

  it('keeps ratings working on reranked items', async () => {
    const mock = setup({
      'POST /api/search': found(),
      'POST /api/search/rerank': reranked(),
      'GET /api/llm': LLM_READY,
      'PUT /api/ratings': { text: 'cozy town', filters: {}, track_id: 3, rating: 2 },
    })
    renderWithProviders(<SearchPage />)
    await searchFor('cozy town')
    await userEvent.click(await screen.findByRole('button', { name: 'Rerank top 20 with LLM' }))
    await screen.findByText(/^Reranked by/)
    const first = screen.getByRole('article', { name: 'Track 3' })
    await userEvent.click(within(first).getByRole('button', { name: /good fit/i }))
    await waitFor(() => expect(bodies(mock, 'PUT /api/ratings')).toHaveLength(1))
    expect(bodies(mock, 'PUT /api/ratings')[0]).toMatchObject({ text: 'cozy town', track_id: 3, rating: 2 })
  })
})

describe('Search page: reference song', () => {
  const echo = (label: string, weight = 0.5) => ({ kind: 'track', track_id: 1, label, weight })
  const UPLOADED = { upload_id: 'u1', filename: 'riff.mp3', duration_s: 30, model_id: 'clap-test' }
  const GONE = 'This uploaded song has expired. Upload it again.'
  const TRACK_1 = {
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
  }

  /** Answers a search with a reference like the backend does: the echo is there, ratings are not. */
  const byReference = (plain: unknown[], similar: unknown[], label = 'Track 1 — Artist 1') => (_url: URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body))
    return body.reference ? response(similar, { reference: echo(label) }) : response(plain)
  }

  const fileInput = () => document.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement
  const song = () => new File(['audio'], 'riff.mp3', { type: 'audio/mpeg' })
  const chip = (label: string) => screen.getByText(`Sounds like: ${label}`)

  it('finds similar tracks from a result: no text, the filters kept, a chip, no ratings or rerank', async () => {
    const mock = setup({
      'POST /api/search': byReference([item(1)], [item(2, { rating: null })]),
      'GET /api/llm': LLM_READY,
    })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await searchFor('rain')
    await screen.findByText('Track 1')
    expect(screen.getByRole('button', { name: 'Rerank top 20 with LLM' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /good fit/i })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Find similar to Track 1' }))
    await screen.findByText('Track 2')
    expect(bodies(mock, 'POST /api/search')[1]).toEqual({
      filters: { genres: ['rock'] },
      reference: { track_id: 1 },
      limit: 20,
      offset: 0,
      explain: true,
    })
    expect(chip('Track 1 — Artist 1')).toBeInTheDocument()
    expect(box()).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Rock' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('button', { name: /good fit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Rerank/ })).not.toBeInTheDocument()
    expect(screen.getByText(/^Similar to Track 1 — Artist 1 · 1 result of 1 candidate/)).toBeInTheDocument()
    await waitFor(() => expect(chip('Track 1 — Artist 1')).toHaveFocus())
  })

  it('uses the title alone as the label of a track without an artist', async () => {
    setup({ 'POST /api/search': byReference([item(1, { artist: null })], [item(2)], 'Track 1') })
    renderWithProviders(<SearchPage />)
    await searchFor('rain')
    await userEvent.click(await screen.findByRole('button', { name: 'Find similar to Track 1' }))
    await screen.findByText('Track 2')
    expect(chip('Track 1')).toBeInTheDocument()
  })

  it('finds similar tracks from the track drawer and closes it', async () => {
    const mock = setup({
      'POST /api/search': byReference([item(1)], [item(2)]),
      'GET /api/tracks/1': TRACK_1,
    })
    renderWithProviders(<SearchPage />)
    await searchFor('rain')
    await userEvent.click(await screen.findByRole('button', { name: 'Track 1' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Find similar' }))
    await screen.findByText('Track 2')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')[1].reference).toEqual({ track_id: 1 })
    expect(chip('Track 1 — Artist 1')).toBeInTheDocument()
    await waitFor(() => expect(chip('Track 1 — Artist 1')).toHaveFocus())
  })

  it('sends the reference with the next pages too', async () => {
    const page = (from: number) => Array.from({ length: 2 }, (_, i) => item(from + i))
    const mock = setup({
      'POST /api/search': (_url: URL, init?: RequestInit) => {
        const body = JSON.parse(String(init?.body))
        if (!body.reference) return response([item(1)])
        return response(page(body.offset + 10), { total_candidates: 4, reference: echo('Track 1 — Artist 1') })
      },
    })
    renderWithProviders(<SearchPage />)
    await searchFor('rain')
    await userEvent.click(await screen.findByRole('button', { name: 'Find similar to Track 1' }))
    await screen.findByText('Track 10')
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await screen.findByText('Track 12')
    const sent = bodies(mock, 'POST /api/search')
    expect(sent[2]).toMatchObject({ reference: { track_id: 1 }, offset: 2 })
  })

  it('offers an upload button and a hint while there is no reference', async () => {
    renderWithProviders(<SearchPage />)
    const button = screen.getByRole('button', { name: 'Upload a song' })
    const opened = vi.fn()
    fileInput().addEventListener('click', opened)
    await userEvent.click(button)
    expect(opened).toHaveBeenCalledOnce()
    expect(fileInput().accept).toContain('.mp3')
    expect(screen.getByText(/"Find similar" on any result works too/)).toBeInTheDocument()
  })

  it('uploads the song, then searches with it and the current text and filters', async () => {
    const mock = setup({
      'POST /api/reference': UPLOADED,
      'POST /api/search': response([item(2)], { reference: { kind: 'upload', track_id: null, label: 'riff.mp3', weight: 0.5 } }),
    })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await userEvent.type(box(), 'rain')
    await userEvent.upload(fileInput(), song())
    await screen.findByText('Track 2')

    const [upload] = mock.mock.calls.filter(([input]) => String(input) === '/api/reference')
    const form = upload?.[1]?.body as FormData
    expect(form).toBeInstanceOf(FormData)
    expect((form.get('file') as File).name).toBe('riff.mp3')
    expect(bodies(mock, 'POST /api/search')).toEqual([
      {
        text: 'rain',
        filters: { genres: ['rock'] },
        reference: { upload_id: 'u1' },
        reference_weight: 0.5,
        limit: 20,
        offset: 0,
        explain: true,
      },
    ])
    expect(chip('riff.mp3')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload a song' })).not.toBeInTheDocument()
  })

  it('shows a spinner while the song uploads', async () => {
    let release: (value: unknown) => void = () => {}
    setup({
      'POST /api/reference': () => new Promise((resolve) => (release = resolve)),
      'POST /api/search': response([item(2)]),
    })
    renderWithProviders(<SearchPage />)
    await userEvent.upload(fileInput(), song())
    expect(await screen.findByText('Uploading song')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload a song' })).not.toBeInTheDocument()
    release(UPLOADED)
    await screen.findByText('Track 2')
    expect(screen.queryByText('Uploading song')).not.toBeInTheDocument()
  })

  it('shows the server message when the upload fails, and searches for nothing', async () => {
    const mock = setup({
      'POST /api/reference': jsonResponse({ detail: 'This file is not a supported audio type.' }, 422),
      'POST /api/search': response([item(2)]),
    })
    renderWithProviders(<SearchPage />)
    await userEvent.upload(fileInput(), song())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("Couldn't use this song")
    expect(alert).toHaveTextContent('This file is not a supported audio type.')
    expect(bodies(mock, 'POST /api/search')).toEqual([])
    expect(screen.getByRole('button', { name: 'Upload a song' })).toBeEnabled()
  })

  it('removes the reference and searches again with the text and filters that are left', async () => {
    const mock = setup({ 'POST /api/search': byReference([item(1)], [item(2)]) })
    renderWithProviders(<SearchPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await searchFor('rain')
    await userEvent.click(await screen.findByRole('button', { name: 'Find similar to Track 1' }))
    await screen.findByText('Track 2')
    await userEvent.click(screen.getByRole('button', { name: 'Remove reference song' }))
    await screen.findByText('Track 1')
    const sent = bodies(mock, 'POST /api/search')
    expect(sent).toHaveLength(3)
    expect(sent[2]).toEqual({ filters: { genres: ['rock'] }, limit: 20, offset: 0, explain: true })
    expect(screen.queryByText(/^Sounds like:/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload a song' })).toBeInTheDocument()
  })

  it('goes back to the empty page when removing the reference leaves nothing to search for', async () => {
    const mock = setup({ 'POST /api/search': byReference([item(1)], [item(2)]) })
    renderWithProviders(<SearchPage />)
    await searchFor('rain')
    await userEvent.click(await screen.findByRole('button', { name: 'Find similar to Track 1' }))
    await screen.findByText('Track 2')
    await userEvent.click(screen.getByRole('button', { name: 'Remove reference song' }))
    expect(screen.queryByText('Track 2')).not.toBeInTheDocument()
    expect(screen.getByText('Try one of these')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toHaveLength(2)
  })

  it('shows the Text and Reference song slider only when there is both, and searches when it moves', async () => {
    const mock = setup({ 'POST /api/search': byReference([item(1)], [item(2)]) })
    renderWithProviders(<SearchPage />)
    await searchFor('rain')
    await screen.findByText('Track 1')
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Find similar to Track 1' }))
    await screen.findByText('Track 2')
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()

    await userEvent.type(box(), 'cozy')
    const slider = screen.getByRole('slider', { name: 'Text ↔ Reference song' })
    expect(slider).toHaveValue('50')
    expect(screen.getByText('Text')).toBeInTheDocument()
    fireEvent.change(slider, { target: { value: '80' } })
    await waitFor(() => expect(bodies(mock, 'POST /api/search')).toHaveLength(3))
    expect(bodies(mock, 'POST /api/search')[2]).toMatchObject({
      text: 'cozy',
      reference: { track_id: 1 },
      reference_weight: 0.8,
    })
    expect(screen.getByRole('slider')).toHaveValue('80')
  })

  it('clears an expired upload and says to upload it again', async () => {
    setup({
      'POST /api/reference': UPLOADED,
      'POST /api/search': () => jsonResponse({ detail: GONE }, 404),
    })
    renderWithProviders(<SearchPage />)
    await userEvent.type(box(), 'rain')
    await userEvent.upload(fileInput(), song())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(GONE)
    expect(screen.queryByText(/^Sounds like:/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload a song' })).toBeInTheDocument()
    expect(screen.queryByText("Couldn't search")).not.toBeInTheDocument()
  })

  it('still opens results saved by an older version, without a reference', async () => {
    function Seed() {
      const [, set] = usePersistentState<unknown>('search.results', null)
      useEffect(() => {
        set({
          runId: 1,
          request: { text: 'cozy', filters: {} },
          items: [item(1)],
          total: 1,
          relaxed: [],
          notes: [],
          unembedded: 0,
          model: 'clap-test',
          elapsedMs: 5,
        })
      }, [set])
      return null
    }
    const seeded = render(<Seed />)
    seeded.unmount()

    setup({ 'POST /api/search': byReference([item(1)], [item(2)]) })
    renderWithProviders(<SearchPage />)
    expect(screen.getByText('Track 1')).toBeInTheDocument()
    expect(screen.getByText('1 result of 1 candidate · clap-test · 5 ms')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /good fit/i })).toBeInTheDocument()
    expect(screen.queryByText(/^Sounds like:/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload a song' })).toBeInTheDocument()
  })
})

describe('Search page: ?similar= from the Projects page', () => {
  const TRACK_1 = {
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
  }
  const SIMILAR = response([item(2)], {
    reference: { kind: 'track', track_id: 1, label: 'Track 1 — Artist 1', weight: 0.5 },
  })

  /** The page as the router shows it: the param is in the hash, and a button changes it. */
  function Host({ initial }: { initial: string }) {
    const [query, setQuery] = useState(initial)
    return (
      <>
        <button onClick={() => setQuery('')}>param gone</button>
        <button onClick={() => setQuery('similar=1')}>param back</button>
        <SearchPage subpath={[]} params={new URLSearchParams(query)} />
      </>
    )
  }

  beforeEach(() => {
    window.location.hash = '#/search?similar=1'
  })

  it('searches by the track once: reference chip, no text, and the param leaves the address', async () => {
    const mock = setup({ 'POST /api/search': SIMILAR, 'GET /api/tracks/1': TRACK_1 })
    const push = vi.spyOn(window.history, 'pushState')
    const replace = vi.spyOn(window.history, 'replaceState')
    const length = window.history.length
    renderWithProviders(<Host initial="similar=1" />)

    expect(await screen.findByText('Track 2')).toBeInTheDocument()
    expect(bodies(mock, 'POST /api/search')).toEqual([
      { filters: {}, reference: { track_id: 1 }, limit: 20, offset: 0, explain: true },
    ])
    expect(screen.getByText('Sounds like: Track 1 — Artist 1')).toBeInTheDocument()
    expect(box()).toHaveValue('')
    expect(screen.getByText(/^Similar to Track 1 — Artist 1 · /)).toBeInTheDocument()

    expect(window.location.hash).toBe('#/search')
    expect(replace).toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
    expect(window.history.length).toBe(length)
  })

  it('does not search again on a re-render, and runs again when the param comes back', async () => {
    const mock = setup({ 'POST /api/search': SIMILAR, 'GET /api/tracks/1': TRACK_1 })
    renderWithProviders(<Host initial="similar=1" />)
    await screen.findByText('Track 2')

    await userEvent.type(box(), 'x')
    expect(bodies(mock, 'POST /api/search')).toHaveLength(1)

    // Visiting #/search without the param does nothing.
    await userEvent.click(screen.getByRole('button', { name: 'param gone' }))
    expect(bodies(mock, 'POST /api/search')).toHaveLength(1)

    await userEvent.click(screen.getByRole('button', { name: 'param back' }))
    await waitFor(() => expect(bodies(mock, 'POST /api/search')).toHaveLength(2))
    expect(bodies(mock, 'POST /api/search')[1].reference).toEqual({ track_id: 1 })
  })

  it('does nothing without the param', async () => {
    window.location.hash = '#/search'
    const mock = setup({ 'POST /api/search': SIMILAR, 'GET /api/tracks/1': TRACK_1 })
    renderWithProviders(<Host initial="" />)
    await screen.findByRole('textbox', { name: 'Describe the music you need' })
    expect(bodies(mock, 'POST /api/search')).toEqual([])
    expect(mock.mock.calls.some(([input]) => String(input).startsWith('/api/tracks/'))).toBe(false)
  })

  it('shows the error of an unknown track and does not search', async () => {
    window.location.hash = '#/search?similar=99'
    const mock = setup({
      'POST /api/search': SIMILAR,
      'GET /api/tracks/99': jsonResponse({ detail: 'no track with id 99' }, 404),
    })
    renderWithProviders(<Host initial="similar=99" />)
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't find similar tracks: no track with id 99")
    expect(bodies(mock, 'POST /api/search')).toEqual([])
    expect(window.location.hash).toBe('#/search')
    expect(screen.queryByText(/^Sounds like:/)).not.toBeInTheDocument()
  })

  it('shows an error for a param that is not a track id, without asking the backend', async () => {
    window.location.hash = '#/search?similar=abc'
    const mock = setup({ 'POST /api/search': SIMILAR })
    renderWithProviders(<Host initial="similar=abc" />)
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't find similar tracks")
    expect(bodies(mock, 'POST /api/search')).toEqual([])
    expect(mock.mock.calls.some(([input]) => String(input).startsWith('/api/tracks/'))).toBe(false)
  })
})
