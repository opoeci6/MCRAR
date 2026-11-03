import { screen, waitFor, within } from '@testing-library/react'
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

  it('labels the source link of a Freesound track', async () => {
    stubApi({
      'GET /api/tracks/5': { ...DETAIL, source: 'freesound', source_url: 'https://freesound.org/s/5/' },
    })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    expect(screen.getByRole('link', { name: /Open on Freesound/ })).toHaveAttribute(
      'href',
      'https://freesound.org/s/5/',
    )
    expect(screen.queryByRole('link', { name: /Open on Jamendo/ })).not.toBeInTheDocument()
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

  it('shows both readings next to the confidence when the tempo is uncertain', async () => {
    stubApi({
      'GET /api/tracks/5': { ...DETAIL, features: { ...DETAIL.features, bpm: 164.4, bpm_confidence: 0.12 } },
    })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    const features = screen.getByRole('region', { name: 'Audio features' })
    const tempo = within(features).getByText('82 / 164 BPM (12% confidence)')
    expect(tempo).toHaveAccessibleDescription('Tempo uncertain: it may be half or double')
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
    expect(within(tags).getByText('Model probability')).toBeInTheDocument()
    expect(within(genre).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Dark Ambient 90%',
      'Ambient 20%',
    ])
    const mood = within(tags).getByRole('heading', { name: 'Mood and theme' }).parentElement as HTMLElement
    expect(within(mood).getByText('Calm 70%')).toBeInTheDocument()
  })

  it('names the valence and arousal sets and shows their single value as a percentage', async () => {
    stubApi({
      'GET /api/tracks/5': {
        ...DETAIL,
        tags: [tag('valence', 'value', 0.62), tag('arousal', 'value', 0.3)],
      },
    })
    open(5)
    await screen.findByRole('heading', { name: 'Rainy Window' })
    const tags = screen.getByRole('region', { name: 'Tags' })
    const valence = within(tags).getByRole('heading', { name: 'Positivity (valence)' }).parentElement as HTMLElement
    expect(within(valence).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['62%'])
    const arousal = within(tags).getByRole('heading', { name: 'Intensity (arousal)' }).parentElement as HTMLElement
    expect(within(arousal).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['30%'])
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

  describe('removing the track', () => {
    const IMPACT = { ratings: 2, scene_labels: 1, projects: 1, copied_file: false }
    const openRemovable = (onRemoved = vi.fn()) => {
      renderWithProviders(<TrackDrawer trackId={5} onClose={() => {}} onRemoved={onRemoved} />)
      return onRemoved
    }
    const ask = async () => {
      await screen.findByRole('heading', { name: 'Rainy Window' })
      await userEvent.click(screen.getByRole('button', { name: 'Remove from library' }))
      return screen.findByRole('group', { name: 'Remove this track' })
    }

    it('offers no removal unless the caller handles it', async () => {
      stubApi({ 'GET /api/tracks/5': DETAIL })
      open(5)
      await screen.findByRole('heading', { name: 'Rainy Window' })
      expect(screen.queryByRole('button', { name: 'Remove from library' })).not.toBeInTheDocument()
    })

    it('says what goes with the track, and leaves out what is zero', async () => {
      stubApi({ 'GET /api/tracks/5': DETAIL, 'GET /api/tracks/5/removal': IMPACT })
      openRemovable()
      const group = await ask()
      expect(group).toHaveTextContent(
        'Remove "Rainy Window" from the library? This also deletes 2 ratings, 1 scene label and its place in 1 project.',
      )
      // A Jamendo track has no file of its own to mention.
      expect(group).not.toHaveTextContent('file')
    })

    it('asks only the question for a track nothing refers to', async () => {
      stubApi({
        'GET /api/tracks/5': DETAIL,
        'GET /api/tracks/5/removal': { ratings: 0, scene_labels: 0, projects: 0, copied_file: false },
      })
      openRemovable()
      expect(await ask()).toHaveTextContent(/^Remove "Rainy Window" from the library\?RemoveCancel$/)
    })

    it('says that the copy in the MCRAR folder is deleted', async () => {
      stubApi({
        'GET /api/tracks/5': { ...DETAIL, source: 'local', local_path: 'C:\\lib\\x.wav' },
        'GET /api/tracks/5/removal': { ...IMPACT, ratings: 0, scene_labels: 0, projects: 0, copied_file: true },
      })
      openRemovable()
      expect(await ask()).toHaveTextContent("The copied file in MCRAR's folder is deleted too.")
    })

    it('says that the file on disk of a local track is kept', async () => {
      stubApi({
        'GET /api/tracks/5': { ...DETAIL, source: 'local', local_path: 'D:\\Music\\x.wav' },
        'GET /api/tracks/5/removal': IMPACT,
      })
      openRemovable()
      expect(await ask()).toHaveTextContent('The file on disk is kept.')
    })

    it('removes the track on confirmation, tells the caller and says so', async () => {
      const api = stubApi({
        'GET /api/tracks/5': DETAIL,
        'GET /api/tracks/5/removal': IMPACT,
        'DELETE /api/tracks/5': new Response(null, { status: 204 }),
      })
      const onRemoved = openRemovable()
      const group = await ask()
      expect(api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
      await userEvent.click(within(group).getByRole('button', { name: 'Remove' }))
      await waitFor(() => expect(onRemoved).toHaveBeenCalledWith(5))
      expect(api.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(1)
      expect(await screen.findByText('Removed "Rainy Window".')).toBeInTheDocument()
    })

    it('shows the reason when the removal is refused, and stays', async () => {
      stubApi({
        'GET /api/tracks/5': DETAIL,
        'GET /api/tracks/5/removal': IMPACT,
        'DELETE /api/tracks/5': jsonResponse(
          { detail: 'A job is running; try again when it has finished.' },
          409,
        ),
      })
      const onRemoved = openRemovable()
      const group = await ask()
      await userEvent.click(within(group).getByRole('button', { name: 'Remove' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'A job is running; try again when it has finished.',
      )
      expect(onRemoved).not.toHaveBeenCalled()
      expect(screen.getByRole('group', { name: 'Remove this track' })).toBeInTheDocument()
    })

    it('goes back to the button on Cancel, and removes nothing', async () => {
      const api = stubApi({ 'GET /api/tracks/5': DETAIL, 'GET /api/tracks/5/removal': IMPACT })
      const onRemoved = openRemovable()
      const group = await ask()
      await userEvent.click(within(group).getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByRole('group', { name: 'Remove this track' })).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Remove from library' })).toBeInTheDocument()
      expect(onRemoved).not.toHaveBeenCalled()
      expect(api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    })

    it('shows the error when the impact cannot be loaded', async () => {
      stubApi({
        'GET /api/tracks/5': DETAIL,
        'GET /api/tracks/5/removal': jsonResponse({ detail: 'no track with id 5' }, 404),
      })
      openRemovable()
      await screen.findByRole('heading', { name: 'Rainy Window' })
      await userEvent.click(screen.getByRole('button', { name: 'Remove from library' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('no track with id 5')
    })
  })

  describe('editing the licence of a local track', () => {
    const LOCAL = {
      ...DETAIL,
      source: 'local',
      source_url: null,
      local_path: 'C:/music/a.mp3',
      risk: 'amber',
      license_code: 'CC BY-NC 4.0',
      license: {
        ...DETAIL.license,
        code: 'CC BY-NC 4.0',
        family: 'cc',
        risk: 'amber',
        attribution_text: null,
        set_by_user: false,
      },
    }
    const UPDATED = {
      ...LOCAL,
      risk: 'green',
      license_code: 'CC BY 4.0',
      license: {
        ...LOCAL.license,
        code: 'CC BY 4.0',
        risk: 'green',
        attribution_text: 'Rainy Window by Jane Doe (CC BY 4.0)',
        set_by_user: true,
      },
    }
    const openLocal = (onChanged = vi.fn()) => {
      renderWithProviders(<TrackDrawer trackId={5} onClose={() => {}} onChanged={onChanged} />)
      return onChanged
    }
    const edit = async () => {
      await screen.findByRole('heading', { name: 'Rainy Window' })
      await userEvent.click(screen.getByRole('button', { name: 'Edit licence' }))
      return screen.findByRole('form', { name: 'Edit licence' })
    }
    const putCalls = (api: ReturnType<typeof stubApi>) =>
      api.mock.calls.filter(([, init]) => init?.method === 'PUT')

    it('offers the button for a local track only', async () => {
      stubApi({ 'GET /api/tracks/5': DETAIL })
      open(5)
      await screen.findByRole('heading', { name: 'Rainy Window' })
      expect(screen.queryByRole('button', { name: 'Edit licence' })).not.toBeInTheDocument()
    })

    it('offers no button for a Freesound track either', async () => {
      stubApi({ 'GET /api/tracks/5': { ...DETAIL, source: 'freesound' } })
      open(5)
      await screen.findByRole('heading', { name: 'Rainy Window' })
      expect(screen.queryByRole('button', { name: 'Edit licence' })).not.toBeInTheDocument()
    })

    it('opens a form filled with the current code, with the suggestions', async () => {
      stubApi({ 'GET /api/tracks/5': LOCAL })
      openLocal()
      const form = await edit()
      const input = within(form).getByRole('combobox', { name: 'Licence' })
      expect(input).toHaveValue('CC BY-NC 4.0')
      expect(input).toHaveFocus()
      expect(form).toHaveTextContent('Kept when you add the folder again.')
      expect(screen.queryByRole('button', { name: 'Edit licence' })).not.toBeInTheDocument()
    })

    it('suggests the common licences in a list drawn in the page, and a pick fills the box', async () => {
      stubApi({ 'GET /api/tracks/5': LOCAL })
      openLocal()
      const form = await edit()
      await userEvent.click(within(form).getByRole('button', { name: 'Show common licences' }))
      const list = within(form).getByRole('listbox', { name: 'Common licences' })
      expect(within(list).getAllByRole('option').map((o) => o.textContent)).toEqual([
        'CC0 public domain',
        'CC BY 4.0 credit the author',
        'CC BY-SA 4.0 credit, share alike',
        'CC BY-NC 4.0 non-commercial',
        'CC BY-ND 4.0 no changes',
        'Unknown not known',
      ])
      await userEvent.click(within(list).getByRole('option', { name: /^CC0/ }))
      expect(within(form).getByRole('combobox', { name: 'Licence' })).toHaveValue('CC0')
      expect(document.querySelector('datalist')).toBeNull()
    })

    it('starts empty while the licence is unknown', async () => {
      const unknown = { ...LOCAL, license: { ...LOCAL.license, code: 'other', family: 'unknown', risk: 'unknown' } }
      stubApi({ 'GET /api/tracks/5': unknown })
      openLocal()
      const form = await edit()
      expect(within(form).getByRole('combobox', { name: 'Licence' })).toHaveValue('')
      expect(within(form).getByRole('button', { name: 'Save' })).toBeDisabled()
    })

    it('saves, shows the answer, says so and tells the caller', async () => {
      const api = stubApi({ 'GET /api/tracks/5': LOCAL, 'PUT /api/tracks/5/license': UPDATED })
      const onChanged = openLocal()
      const form = await edit()
      const input = within(form).getByRole('combobox', { name: 'Licence' })
      await userEvent.clear(input)
      await userEvent.type(input, '  CC BY 4.0 ')
      await userEvent.click(within(form).getByRole('button', { name: 'Save' }))

      expect(await screen.findByText('Licence set to CC BY 4.0.')).toBeInTheDocument()
      expect(putCalls(api)).toHaveLength(1)
      expect(putCalls(api)[0]?.[0]).toBe('/api/tracks/5/license')
      expect(JSON.parse(String(putCalls(api)[0]?.[1]?.body))).toEqual({ license: 'CC BY 4.0' })
      expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ id: 5, license_code: 'CC BY 4.0' }))
      expect(screen.queryByRole('form', { name: 'Edit licence' })).not.toBeInTheDocument()
      const licence = screen.getByRole('region', { name: 'Licence' })
      expect(within(licence).getByText('Safe')).toBeInTheDocument()
      expect(within(licence).getByText('Rainy Window by Jane Doe (CC BY 4.0)')).toBeInTheDocument()
      expect(within(licence).getByText('Set by you. Kept when you add the folder again.')).toBeInTheDocument()
      await waitFor(() => expect(screen.getByRole('button', { name: 'Edit licence' })).toHaveFocus())
    })

    it('shows why the licence was refused, and keeps the form', async () => {
      stubApi({
        'GET /api/tracks/5': LOCAL,
        'PUT /api/tracks/5/license': jsonResponse({ detail: "unrecognised license: 'zzz'" }, 422),
      })
      const onChanged = openLocal()
      const form = await edit()
      await userEvent.clear(within(form).getByRole('combobox', { name: 'Licence' }))
      await userEvent.type(within(form).getByRole('combobox', { name: 'Licence' }), 'zzz')
      await userEvent.click(within(form).getByRole('button', { name: 'Save' }))
      expect(await within(form).findByRole('alert')).toHaveTextContent("unrecognised license: 'zzz'")
      expect(screen.getByRole('form', { name: 'Edit licence' })).toBeInTheDocument()
      expect(within(form).getByRole('combobox', { name: 'Licence' })).toHaveValue('zzz')
      expect(within(form).getByRole('button', { name: 'Save' })).toBeEnabled()
      expect(onChanged).not.toHaveBeenCalled()
    })

    it('shows that a job is running, and keeps the form', async () => {
      stubApi({
        'GET /api/tracks/5': LOCAL,
        'PUT /api/tracks/5/license': jsonResponse(
          { detail: 'A job is running; try again when it has finished.' },
          409,
        ),
      })
      openLocal()
      const form = await edit()
      await userEvent.click(within(form).getByRole('button', { name: 'Save' }))
      expect(await within(form).findByRole('alert')).toHaveTextContent(
        'A job is running; try again when it has finished.',
      )
      expect(screen.getByRole('form', { name: 'Edit licence' })).toBeInTheDocument()
    })

    it('goes back on Cancel and on Escape (the drawer stays), and sends nothing', async () => {
      const api = stubApi({ 'GET /api/tracks/5': LOCAL })
      const onClose = vi.fn()
      renderWithProviders(<TrackDrawer trackId={5} onClose={onClose} />)
      const form = await edit()
      await userEvent.type(within(form).getByRole('combobox', { name: 'Licence' }), ' changed')
      await userEvent.click(within(form).getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByRole('form', { name: 'Edit licence' })).not.toBeInTheDocument()

      await userEvent.click(screen.getByRole('button', { name: 'Edit licence' }))
      // Opening again starts from the saved code, not from the abandoned text.
      expect(await screen.findByRole('combobox', { name: 'Licence' })).toHaveValue('CC BY-NC 4.0')
      await userEvent.keyboard('{Escape}')
      expect(screen.queryByRole('form', { name: 'Edit licence' })).not.toBeInTheDocument()
      expect(onClose).not.toHaveBeenCalled()
      expect(putCalls(api)).toHaveLength(0)
    })

    it('notes that the licence was set by hand', async () => {
      stubApi({ 'GET /api/tracks/5': UPDATED })
      openLocal()
      await screen.findByRole('heading', { name: 'Rainy Window' })
      expect(screen.getByText('Set by you. Kept when you add the folder again.')).toBeInTheDocument()
    })

    it('leaves out the note for a licence nobody set by hand', async () => {
      stubApi({ 'GET /api/tracks/5': LOCAL })
      openLocal()
      await screen.findByRole('heading', { name: 'Rainy Window' })
      expect(screen.queryByText(/Set by you/)).not.toBeInTheDocument()
    })
  })
})
