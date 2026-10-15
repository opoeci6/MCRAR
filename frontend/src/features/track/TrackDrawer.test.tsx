import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { jsonResponse, stubApi } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import { TrackDrawer } from './TrackDrawer'

const tag = (label_set: string, label: string, prob: number) => ({
  label_set,
  label,
  prob,
  method: 'model',
  model_version: 'v1',
})

const DETAIL = {
  id: 5,
  title: 'Rainy Window',
  artist: 'Jane Doe',
  album: 'Weather',
  source: 'jamendo',
  source_url: 'https://www.jamendo.com/track/5',
  local_path: null,
  duration_s: 187,
  vocal_instrumental: 'instrumental',
  risk: 'green',
  license_code: 'CC BY 4.0',
  features: {
    bpm: 92.4,
    bpm_confidence: 0.81,
    key: 'A',
    mode: 'minor',
    loudness_lufs: -14.25,
    energy: 0.42,
  },
  tags: [
    tag('genre', 'ambient', 0.2),
    tag('genre', 'dark-ambient', 0.9),
    tag('moodtheme', 'calm', 0.7),
  ],
  license: {
    code: 'CC BY 4.0',
    url: 'https://example.org/by',
    risk: 'green',
    attribution_text: 'Rainy Window by Jane Doe',
    commercial_license_url: 'https://example.org/buy',
  },
}

const open = (trackId: number | null, onClose = () => {}) =>
  renderWithProviders(<TrackDrawer trackId={trackId} onClose={onClose} />)

describe('TrackDrawer', () => {
  it('stays closed without a track', () => {
    stubApi({})
    open(null)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('loads and shows the track, and closes on request', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    const onClose = vi.fn()
    open(5, onClose)
    expect(await screen.findByRole('heading', { name: 'Rainy Window' })).toBeInTheDocument()
    expect(screen.getByText(/^by Jane Doe/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes with Escape', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    const onClose = vi.fn()
    open(5, onClose)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('shows the licence block with the credit line, links and licence files', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    const licence = screen.getByRole('region', { name: 'Licence' })
    expect(within(licence).getByText('Safe')).toBeInTheDocument()
    expect(within(licence).getByText('Rainy Window by Jane Doe')).toBeInTheDocument()
    expect(within(licence).getByRole('link', { name: /Read the licence/ })).toHaveAttribute(
      'href',
      'https://example.org/by',
    )
    expect(within(licence).getByRole('link', { name: /Buy a commercial licence/ })).toHaveAttribute(
      'href',
      'https://example.org/buy',
    )
    const txt = within(licence).getByRole('link', { name: /\.txt/ })
    expect(txt).toHaveAttribute('href', '/api/tracks/5/credits?format=txt')
    expect(txt).toHaveAttribute('download')
    expect(within(licence).getByRole('link', { name: /\.md/ })).toHaveAttribute(
      'href',
      '/api/tracks/5/credits?format=md',
    )
  })

  it('shows the source link and the audio features', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    expect(screen.getByRole('link', { name: /Open on Jamendo/ })).toHaveAttribute(
      'href',
      'https://www.jamendo.com/track/5',
    )
    const features = screen.getByRole('region', { name: 'Audio features' })
    expect(within(features).getByText('92 BPM (81% confidence)')).toBeInTheDocument()
    expect(within(features).getByText('A minor')).toBeInTheDocument()
    expect(within(features).getByText('-14.3 LUFS')).toBeInTheDocument()
    expect(within(features).getByText('42%')).toBeInTheDocument()
    expect(within(features).getByText('3:07')).toBeInTheDocument()
    expect(within(features).getByText('Instrumental')).toBeInTheDocument()
  })

  it('shows the local path of a local track', async () => {
    stubApi({
      'GET /api/tracks/6': { ...DETAIL, id: 6, source: 'local', source_url: null, local_path: 'C:/music/a.mp3' },
    })
    open(6)
    expect(await screen.findByText('C:/music/a.mp3')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Open on Jamendo/ })).not.toBeInTheDocument()
  })

  it('groups tags by label set, most probable first', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    const tags = screen.getByRole('region', { name: 'Tags' })
    const genre = within(tags).getByRole('heading', { name: 'Genre' }).parentElement as HTMLElement
    expect(within(genre).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Dark Ambient 90%',
      'Ambient 20%',
    ])
    const mood = within(tags).getByRole('heading', { name: 'Mood and theme' }).parentElement as HTMLElement
    expect(within(mood).getByText('Calm 70%')).toBeInTheDocument()
  })

  it('shows the first tags of a long set and the rest on request', async () => {
    const many = Array.from({ length: 12 }, (_, i) => tag('genre', `g${i}`, 0.9 - i * 0.05))
    stubApi({ 'GET /api/tracks/5': { ...DETAIL, tags: many } })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    const tags = screen.getByRole('region', { name: 'Tags' })
    expect(within(tags).getAllByRole('listitem')).toHaveLength(8)
    await userEvent.click(within(tags).getByRole('button', { name: 'Show all 12' }))
    expect(within(tags).getAllByRole('listitem')).toHaveLength(12)
    await userEvent.click(within(tags).getByRole('button', { name: 'Show fewer' }))
    expect(within(tags).getAllByRole('listitem')).toHaveLength(8)
  })

  it('handles a track without features or tags', async () => {
    stubApi({ 'GET /api/tracks/5': { ...DETAIL, features: null, tags: [], duration_s: null } })
    open(5)
    expect(await screen.findByText('This track has not been analysed yet.')).toBeInTheDocument()
    expect(screen.getByText('This track has no tags yet.')).toBeInTheDocument()
  })

  it('plays the track from the play button', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    open(5)
    await userEvent.click(await screen.findByRole('button', { name: 'Play Rainy Window' }))
    expect(await screen.findByRole('button', { name: 'Pause Rainy Window' })).toBeInTheDocument()
  })

  it('offers the add to project menu', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    expect(screen.getByRole('button', { name: /Add to project/i })).toBeInTheDocument()
  })

  it('shows the error when the track cannot be loaded', async () => {
    stubApi({ 'GET /api/tracks/5': jsonResponse({ detail: 'no track with id 5' }, 404) })
    open(5)
    expect(await screen.findByRole('alert')).toHaveTextContent('no track with id 5')
  })
})
