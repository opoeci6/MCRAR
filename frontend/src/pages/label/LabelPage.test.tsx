import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PoolEntry, SceneLabel } from '../../api/types'
import { clearPersistentState } from '../../app/usePersistentState'
import { jsonResponse, stubApi } from '../../test/fetch'
import type { Routes } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import LabelPage from './index'

const SCENE_IDS = [
  'combat',
  'boss',
  'exploration',
  'menu',
  'town',
  'puzzle',
  'stealth',
  'horror',
  'victory',
  'defeat',
  'credits',
  'cutscene',
  'chase',
  'ambient',
]
const SCENE_NAMES = SCENE_IDS.map((id) => id[0]!.toUpperCase() + id.slice(1))
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'q', 'w', 'e', 'r']

const VOCAB = {
  genre: [{ id: 'rock', display: 'Rock', synonyms: [] }],
  moodtheme: [],
  scene: SCENE_IDS.map((id, i) => ({ id, display: SCENE_NAMES[i], synonyms: [] })),
}

const POOL: PoolEntry[] = [10, 20, 30].map((position, i) => ({
  position,
  part: i === 2 ? 'both' : 'A',
  track_id: i + 1,
  title: `Song ${i + 1}`,
  artist: `Artist ${i + 1}`,
  status: null,
}))

const PROGRESS = {
  pool_size: 250,
  parts: {
    A: { total: 100, labelled: 10, skipped: 2 },
    B: { total: 120, labelled: 5, skipped: 0 },
    both: { total: 30, labelled: 7, skipped: 1 },
  },
  labelled: 22,
  skipped: 3,
  labellers: ['owner', 'Ann Lee'],
}

interface Backend {
  pool?: PoolEntry[]
  /** The reply to every PUT, instead of storing the label. */
  put?: Response
  /** Extra or replacing routes. */
  routes?: Routes
}

/** A small in-memory labelling backend: next, pool, progress, tracks and labels of the pool. */
function backend({ pool = POOL, put, routes = {} }: Backend = {}) {
  const labels = new Map<number, SceneLabel>()
  let clock = 0
  const table: Routes = {
    'GET /api/vocab': VOCAB,
    'GET /api/labels/progress': PROGRESS,
    'GET /api/labels/pool': () => ({
      items: pool.map((entry) => ({ ...entry, status: labels.get(entry.track_id)?.status ?? null })),
      total: pool.length,
    }),
    'GET /api/labels/next': (url: URL) => {
      const after = url.searchParams.get('after')
      const next = pool.find(
        (entry) => entry.position > (after === null ? -1 : Number(after)) && !labels.has(entry.track_id),
      )
      if (!next) return { track: null }
      return {
        track: {
          id: next.track_id,
          title: next.title,
          artist: next.artist,
          duration_s: 200,
          source: 'jamendo',
          risk: 'green',
          license_code: 'CC BY 4.0',
          license_url: null,
          commercial_license_url: null,
          attribution: null,
          stream_url: `/api/tracks/${next.track_id}/stream`,
        },
        position: next.position,
        part: next.part,
        label: null,
      }
    },
  }
  for (const entry of pool) {
    const id = entry.track_id
    table[`GET /api/tracks/${id}`] = {
      id,
      title: entry.title,
      artist: entry.artist,
      duration_s: 200,
      license: { risk: 'green', code: 'CC BY 4.0', url: null, attribution_text: null, commercial_license_url: null },
    }
    table[`GET /api/labels/${id}`] = () => labels.get(id) ?? jsonResponse({ detail: 'no label' }, 404)
    table[`PUT /api/labels/${id}`] = (_url: URL, init?: RequestInit) => {
      if (put) return put
      const body = JSON.parse(String(init?.body))
      clock += 1
      const label: SceneLabel = {
        track_id: id,
        labeller: body.labeller,
        scenes: body.scenes,
        intensity: body.intensity,
        status: body.status,
        created_at: `t${clock}`,
        updated_at: `t${clock}`,
      }
      labels.set(id, label)
      return label
    }
    table[`DELETE /api/labels/${id}`] = () =>
      labels.delete(id) ? new Response(null, { status: 204 }) : jsonResponse({ detail: 'no label' }, 404)
  }
  return stubApi({ ...table, ...routes })
}

type Mock = ReturnType<typeof stubApi>

/** The calls to a route in order: the query and the JSON body of each. */
function calls(mock: Mock, route: string) {
  return mock.mock.calls
    .filter(([input, init]) => `${init?.method ?? 'GET'} ${new URL(String(input), 'http://x').pathname}` === route)
    .map(([input, init]) => ({
      params: Object.fromEntries(new URL(String(input), 'http://x').searchParams),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    }))
}

const button = (name: string) => screen.getByRole('button', { name })
const pressed = (name: string) => button(name).getAttribute('aria-pressed') === 'true'
const nameField = () => screen.getByRole('textbox', { name: 'Your name' })
const trackTitle = (title: string) => screen.findByRole('heading', { level: 2, name: title })

async function renderLabelling(options?: Backend) {
  const mock = backend(options)
  renderWithProviders(<LabelPage />)
  await trackTitle('Song 1')
  return mock
}

beforeEach(() => {
  clearPersistentState()
})

describe('Labelling page: name and part', () => {
  it('asks for a valid name and sends no request while it is not', async () => {
    const mock = await renderLabelling()
    mock.mockClear()

    fireEvent.change(nameField(), { target: { value: '   ' } })
    expect(screen.getByText('Enter a name of 1 to 40 characters.')).toBeInTheDocument()
    expect(nameField()).toBeInvalid()
    expect(screen.queryByRole('heading', { level: 2, name: 'Song 1' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Export my labels' })).not.toBeInTheDocument()

    fireEvent.change(nameField(), { target: { value: 'x'.repeat(41) } })
    expect(screen.getByText('Enter a name of 1 to 40 characters.')).toBeInTheDocument()
    expect(mock).not.toHaveBeenCalled()

    fireEvent.change(nameField(), { target: { value: '  Ann Lee ' } })
    await trackTitle('Song 1')
    expect(calls(mock, 'GET /api/labels/next').map((call) => call.params.labeller)).toEqual(['Ann Lee'])
  })

  it('works on the chosen part and counts it in the progress', async () => {
    const mock = await renderLabelling()
    expect(calls(mock, 'GET /api/labels/next')[0]!.params).toEqual({ labeller: 'owner', part: 'all' })
    expect(screen.getByText('25 of 250 done · 3 skipped')).toBeInTheDocument()
    expect(screen.getByText('Labellers so far: owner, Ann Lee')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Labelling progress' }) as HTMLProgressElement
    expect([bar.value, bar.max]).toEqual([25, 250])

    mock.mockClear()
    await userEvent.selectOptions(screen.getByLabelText('Part'), 'Part B')
    await trackTitle('Song 1')
    expect(calls(mock, 'GET /api/labels/next')[0]!.params).toEqual({ labeller: 'owner', part: 'B' })
    expect(calls(mock, 'GET /api/labels/pool')[0]!.params).toEqual({ labeller: 'owner', part: 'B' })
    // Part B is its own tracks plus the shared ones.
    expect(await screen.findByText('13 of 150 done · 1 skipped')).toBeInTheDocument()
  })
})

describe('Labelling page: states', () => {
  it('explains how to make the pool when there is none', async () => {
    const none = () => jsonResponse({ detail: 'No labelling pool yet: run mcrar scenes pool' }, 409)
    backend({
      routes: { 'GET /api/labels/next': none, 'GET /api/labels/pool': none, 'GET /api/labels/progress': none },
    })
    renderWithProviders(<LabelPage />)
    expect(await screen.findByRole('heading', { name: 'No labelling pool yet' })).toBeInTheDocument()
    expect(screen.getByText(/mcrar scenes pool/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save and next' })).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('says when the part is done and offers the export of the labels', async () => {
    backend({ routes: { 'GET /api/labels/next': { track: null } } })
    renderWithProviders(<LabelPage />)
    await screen.findByRole('heading', { name: 'All done for this part' })
    fireEvent.change(nameField(), { target: { value: 'Ann Lee' } })
    await screen.findByRole('heading', { name: 'All done for this part' })
    const links = screen.getAllByRole('link', { name: 'Export my labels' })
    expect(links).toHaveLength(2)
    for (const link of links) {
      expect(link).toHaveAttribute('href', '/api/labels/export?labeller=Ann%20Lee')
      expect(link).toHaveAttribute('download')
    }
  })

  it('shows a failure to load the next track with a retry', async () => {
    let fail = true
    const mock = backend({
      routes: {
        'GET /api/labels/next': () => (fail ? jsonResponse({ detail: 'database is locked' }, 500) : { track: null }),
      },
    })
    renderWithProviders(<LabelPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('database is locked')
    fail = false
    await userEvent.click(button('Try again'))
    await screen.findByRole('heading', { name: 'All done for this part' })
    expect(calls(mock, 'GET /api/labels/next')).toHaveLength(2)
  })
})

describe('Labelling page: the form', () => {
  it('shows the scenes with their keys, the intensity and a disabled save', async () => {
    await renderLabelling()
    expect(screen.getByRole('heading', { level: 2, name: 'Song 1' })).toBeInTheDocument()
    expect(screen.getByText('by Artist 1 · 3:20')).toBeInTheDocument()
    expect(await screen.findByText('Track 1 of 3')).toBeInTheDocument()

    const scenes = screen.getByRole('group', { name: /Which game scenes/ })
    const chips = within(scenes).getAllByRole('button')
    expect(chips.map((chip) => chip.textContent)).toEqual([
      ...SCENE_NAMES.map((name, i) => `${KEYS[i]!.toUpperCase()}${name}`),
      'NNone of these',
    ])
    expect(within(chips[0]!).getByText('1')).toHaveAttribute('aria-hidden', 'true')
    expect(chips[0]).toHaveAccessibleName('Combat')
    expect(chips[0]).toHaveAttribute('title', 'Fighting ordinary enemies, action sequences')

    const intensity = screen.getByRole('group', { name: /Intensity/ })
    expect(within(intensity).getAllByRole('button').map((chip) => chip.textContent)).toEqual(['ALow', 'SMid', 'DHigh'])
    expect(button('Save and next')).toBeDisabled()
    expect(button('Back')).toBeDisabled()
  })

  it('toggles scenes by click and by their keys', async () => {
    await renderLabelling()
    await userEvent.click(button('Boss'))
    expect(pressed('Boss')).toBe(true)
    await userEvent.click(button('Boss'))
    expect(pressed('Boss')).toBe(false)

    // The keys of scenes 10 to 14 are 0, q, w, e and r.
    await userEvent.keyboard('1')
    await userEvent.keyboard('0qwer')
    for (const name of ['Combat', 'Defeat', 'Credits', 'Cutscene', 'Chase', 'Ambient']) {
      expect(pressed(name)).toBe(true)
    }
    expect(pressed('Boss')).toBe(false)
    expect(button('Save and next')).toBeEnabled()
    await userEvent.keyboard('1')
    expect(pressed('Combat')).toBe(false)
  })

  it('keeps None of these and the scenes apart', async () => {
    await renderLabelling()
    await userEvent.click(button('Combat'))
    await userEvent.click(button('Stealth'))
    await userEvent.click(button('None of these'))
    expect(pressed('None of these')).toBe(true)
    expect(pressed('Combat')).toBe(false)
    expect(pressed('Stealth')).toBe(false)
    expect(button('Save and next')).toBeEnabled()

    await userEvent.keyboard('2')
    expect(pressed('None of these')).toBe(false)
    expect(pressed('Boss')).toBe(true)
    await userEvent.keyboard('n')
    expect(pressed('None of these')).toBe(true)
    expect(pressed('Boss')).toBe(false)
    await userEvent.keyboard('n')
    expect(pressed('None of these')).toBe(false)
    expect(button('Save and next')).toBeDisabled()
  })

  it('picks one optional intensity by click and by a, s and d', async () => {
    await renderLabelling()
    await userEvent.keyboard('a')
    expect(pressed('Low')).toBe(true)
    await userEvent.keyboard('s')
    expect(pressed('Low')).toBe(false)
    expect(pressed('Mid')).toBe(true)
    await userEvent.keyboard('s')
    expect(pressed('Mid')).toBe(false)
    await userEvent.keyboard('d')
    expect(pressed('High')).toBe(true)
    await userEvent.click(button('Low'))
    expect(pressed('Low')).toBe(true)
    expect(pressed('High')).toBe(false)
    // An intensity alone is not a label.
    expect(button('Save and next')).toBeDisabled()
  })

  it('shows no scores, tags or reasons for the track', async () => {
    await renderLabelling()
    expect(screen.queryByRole('list')).not.toBeInTheDocument() // no tag list (the pool list is closed)
    expect(screen.queryByText(/zero-shot|reason|tags?\b/i)).not.toBeInTheDocument()
  })
})

describe('Labelling page: saving', () => {
  it('saves the label and moves on after its position', async () => {
    const mock = await renderLabelling()
    await userEvent.keyboard('7') // stealth, ticked before boss
    await userEvent.keyboard('2')
    await userEvent.click(button('Mid'))
    await userEvent.click(button('Save and next'))

    await trackTitle('Song 2')
    expect(calls(mock, 'PUT /api/labels/1')).toEqual([
      {
        params: {},
        body: { labeller: 'owner', scenes: ['boss', 'stealth'], intensity: 'mid', status: 'labelled' },
      },
    ])
    expect(calls(mock, 'GET /api/labels/next').map((call) => call.params.after)).toEqual([undefined, '10'])
    // A fresh form for the next track, and the pool list and progress are asked again.
    expect(pressed('Boss')).toBe(false)
    expect(pressed('Mid')).toBe(false)
    await waitFor(() => expect(calls(mock, 'GET /api/labels/progress')).toHaveLength(2))
    expect(calls(mock, 'GET /api/labels/pool')).toHaveLength(2)
    expect(await screen.findByText('Track 2 of 3')).toBeInTheDocument()
  })

  it('saves "none of these" as a label without scenes, with Enter', async () => {
    const mock = await renderLabelling()
    await userEvent.keyboard('{Enter}') // nothing is chosen yet
    expect(calls(mock, 'PUT /api/labels/1')).toEqual([])
    await userEvent.keyboard('n')
    await userEvent.keyboard('{Enter}')
    await trackTitle('Song 2')
    expect(calls(mock, 'PUT /api/labels/1')[0]!.body).toEqual({
      labeller: 'owner',
      scenes: [],
      intensity: null,
      status: 'labelled',
    })
  })

  it('still saves with Enter after a chip was clicked with the mouse', async () => {
    const mock = await renderLabelling()
    await userEvent.click(button('Combat'))
    await userEvent.keyboard('{Enter}')
    await trackTitle('Song 2')
    expect(calls(mock, 'PUT /api/labels/1')).toHaveLength(1)
  })

  it('skips a track, with the button or with K', async () => {
    const mock = await renderLabelling()
    await userEvent.click(button('Combat')) // a skip keeps nothing of the form
    await userEvent.click(button('Skip'))
    await trackTitle('Song 2')
    await userEvent.keyboard('k')
    await trackTitle('Song 3')
    const puts = [...calls(mock, 'PUT /api/labels/1'), ...calls(mock, 'PUT /api/labels/2')]
    expect(puts.map((call) => call.body)).toEqual([
      { labeller: 'owner', scenes: [], intensity: null, status: 'skipped' },
      { labeller: 'owner', scenes: [], intensity: null, status: 'skipped' },
    ])
    expect(calls(mock, 'GET /api/labels/next').map((call) => call.params.after)).toEqual([undefined, '10', '20'])
  })

  it('keeps the form and says so when saving fails', async () => {
    const mock = await renderLabelling({ put: jsonResponse({ detail: 'disk full' }, 500) })
    await userEvent.click(button('Boss'))
    await userEvent.click(button('High'))
    await userEvent.click(button('Save and next'))

    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't save the label: disk full")
    expect(screen.getByRole('heading', { level: 2, name: 'Song 1' })).toBeInTheDocument()
    expect(pressed('Boss')).toBe(true)
    expect(pressed('High')).toBe(true)
    expect(button('Save and next')).toBeEnabled()
    expect(calls(mock, 'GET /api/labels/next')).toHaveLength(1)
  })

  it('looks for a track that was left behind when none is left after this one', async () => {
    const mock = await renderLabelling()
    // Open the last track from the list, so the first two stay open.
    await userEvent.click(button('Pool list (3)'))
    await userEvent.click(screen.getByRole('button', { name: /Song 3/ }))
    await trackTitle('Song 3')
    await userEvent.keyboard('n{Enter}')

    await trackTitle('Song 1')
    expect(calls(mock, 'GET /api/labels/next').map((call) => call.params.after)).toEqual([undefined, '30', undefined])
  })

  it('is done when nothing is left, after or before', async () => {
    await renderLabelling({ pool: POOL.slice(0, 1) })
    await userEvent.keyboard('n{Enter}')
    expect(await screen.findByRole('heading', { name: 'All done for this part' })).toBeInTheDocument()
  })
})

describe('Labelling page: going back and revisiting', () => {
  async function labelFirstTwo() {
    const mock = await renderLabelling()
    await userEvent.keyboard('2')
    await userEvent.click(button('Low'))
    await userEvent.keyboard('{Enter}')
    await trackTitle('Song 2')
    await userEvent.keyboard('n{Enter}')
    await trackTitle('Song 3')
    return mock
  }

  it('goes back to the previous track with its label filled in', async () => {
    const mock = await renderLabelling()
    await userEvent.keyboard('2')
    await userEvent.click(button('Low'))
    await userEvent.keyboard('{Enter}')
    await trackTitle('Song 2')
    // The pool list is loaded again after the save: Back needs it.
    await waitFor(() => expect(button('Back')).toBeEnabled())
    await userEvent.click(button('Back'))

    await trackTitle('Song 1')
    expect(calls(mock, 'GET /api/tracks/1')).toHaveLength(1)
    expect(calls(mock, 'GET /api/labels/1')[0]!.params).toEqual({ labeller: 'owner' })
    expect(pressed('Boss')).toBe(true)
    expect(pressed('Low')).toBe(true)
    expect(pressed('Combat')).toBe(false)
    expect(screen.getByText('Saved')).toBeInTheDocument()
    expect(button('Back')).toBeDisabled() // the first track of the list
    expect(screen.getByText('Track 1 of 3')).toBeInTheDocument()
  })

  it('goes back with B and changes a label by saving it again', async () => {
    const mock = await labelFirstTwo()
    await userEvent.keyboard('b')
    await trackTitle('Song 2')
    expect(screen.getByText('Saved')).toBeInTheDocument()
    expect(pressed('None of these')).toBe(true)
    await userEvent.keyboard('n') // off again
    await userEvent.keyboard('3')
    await userEvent.keyboard('{Enter}')
    // The queue continues after this track, at the first open one.
    await trackTitle('Song 3')
    expect(calls(mock, 'PUT /api/labels/2').map((call) => call.body.scenes)).toEqual([[], ['exploration']])
  })

  it('shows a skipped track as skipped with an empty form', async () => {
    await renderLabelling()
    await userEvent.click(button('Skip'))
    await trackTitle('Song 2')
    await waitFor(() => expect(button('Back')).toBeEnabled())
    await userEvent.click(button('Back'))
    await trackTitle('Song 1')
    expect(screen.getByText('Skipped')).toBeInTheDocument()
    expect(button('Save and next')).toBeDisabled()
  })

  it('deletes a label', async () => {
    const mock = await renderLabelling()
    await userEvent.keyboard('n{Enter}')
    await trackTitle('Song 2')
    await waitFor(() => expect(button('Back')).toBeEnabled())
    await userEvent.click(button('Back'))
    await trackTitle('Song 1')

    await userEvent.click(button('Delete label'))
    await waitFor(() => expect(screen.queryByText('Saved')).not.toBeInTheDocument())
    expect(calls(mock, 'DELETE /api/labels/1')[0]!.params).toEqual({ labeller: 'owner' })
    expect(pressed('None of these')).toBe(false)
    expect(screen.queryByRole('button', { name: 'Delete label' })).not.toBeInTheDocument()
    // The pool list is told: the track is open again.
    await waitFor(() => expect(calls(mock, 'GET /api/labels/pool').length).toBeGreaterThan(2))
  })

  it('opens any track from the pool list with its label', async () => {
    const mock = await renderLabelling()
    await userEvent.keyboard('n{Enter}')
    await trackTitle('Song 2')
    await userEvent.click(button('Pool list (3)'))
    const list = screen.getByRole('list', { name: 'Tracks of this part' })
    const rows = () => within(list).getAllByRole('button')
    // The list is loaded again after the save, so the first track soon says "Labelled".
    await waitFor(() =>
      expect(rows().map((row) => row.textContent)).toEqual([
        '1Song 1Artist 1Labelled',
        '2Song 2Artist 2To do',
        '3Song 3Artist 3To do',
      ]),
    )
    expect(rows()[1]).toHaveAttribute('aria-current', 'true')

    await userEvent.click(rows()[0]!)
    await trackTitle('Song 1')
    expect(calls(mock, 'GET /api/tracks/1')).toHaveLength(1)
    expect(pressed('None of these')).toBe(true)
    expect(screen.getByText('Saved')).toBeInTheDocument()
    expect(screen.getByText('Track 1 of 3')).toBeInTheDocument()
  })

  it('keeps the track when another one cannot be opened', async () => {
    await renderLabelling({ routes: { 'GET /api/tracks/3': jsonResponse({ detail: 'gone' }, 500) } })
    await userEvent.click(button('Pool list (3)'))
    await userEvent.click(screen.getByRole('button', { name: /Song 3/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't open that track: gone")
    expect(screen.getByRole('heading', { level: 2, name: 'Song 1' })).toBeInTheDocument()
  })
})

describe('Labelling page: shortcuts', () => {
  it('ignores the keys while a name is typed', async () => {
    const mock = await renderLabelling()
    await userEvent.click(button('Combat'))
    const field = nameField()
    fireEvent.keyDown(field, { key: '2' })
    fireEvent.keyDown(field, { key: 'k' })
    fireEvent.keyDown(field, { key: 'Enter' })
    fireEvent.keyDown(field, { key: ' ' })
    expect(pressed('Boss')).toBe(false)
    expect(pressed('Combat')).toBe(true)
    expect(calls(mock, 'PUT /api/labels/1')).toEqual([])
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('ignores keys with a modifier', async () => {
    await renderLabelling()
    await userEvent.keyboard('{Control>}1{/Control}')
    expect(pressed('Combat')).toBe(false)
  })

  it('plays and pauses with Space', async () => {
    await renderLabelling()
    await userEvent.keyboard(' ')
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    expect(document.querySelector('audio')).toHaveAttribute('src', '/api/tracks/1/stream')
    expect(await screen.findByRole('button', { name: 'Pause Song 1' })).toBeInTheDocument()
    await userEvent.keyboard(' ')
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('button', { name: 'Play Song 1' })).toBeInTheDocument()
  })

  it('leaves Enter and Space to a focused button, so a key does only one thing', async () => {
    const mock = await renderLabelling()
    await userEvent.click(button('Combat'))
    const chip = button('Combat')
    chip.focus()
    fireEvent.keyDown(chip, { key: 'Enter' })
    fireEvent.keyDown(chip, { key: ' ' })
    expect(calls(mock, 'PUT /api/labels/1')).toEqual([])
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('lists the shortcuts in a help section', async () => {
    await renderLabelling()
    const help = screen.getByText('Keyboard shortcuts').closest('details')!
    expect(help).not.toHaveAttribute('open')
    expect(within(help).getByText('1–9, 0, Q, W, E, R')).toBeInTheDocument()
  })
})

describe('Labelling page: playback', () => {
  const setTime = () => vi.spyOn(HTMLMediaElement.prototype, 'currentTime', 'set').mockImplementation(() => {})
  const audio = () => document.querySelector('audio') as HTMLAudioElement

  it('starts the track and jumps once it plays', async () => {
    const seek = setTime()
    await renderLabelling()
    await userEvent.click(button('Jump to 30%'))
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    expect(audio()).toHaveAttribute('src', '/api/tracks/1/stream')
    // The audio is still loading: nothing is sought yet.
    expect(seek).not.toHaveBeenCalled()

    act(() => {
      audio().dispatchEvent(new Event('playing'))
    })
    expect(seek).toHaveBeenCalledTimes(1)
    expect(seek).toHaveBeenCalledWith(60) // 30% of 200 s

    await userEvent.click(button('Jump to 60%'))
    expect(seek).toHaveBeenLastCalledWith(120)
  })

  it('resumes a paused track at the jump', async () => {
    const seek = setTime()
    await renderLabelling()
    await userEvent.click(button('Play Song 1'))
    act(() => {
      audio().dispatchEvent(new Event('playing'))
    })
    await userEvent.click(button('Pause Song 1'))
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled()

    await userEvent.click(button('Jump to 60%'))
    act(() => {
      audio().dispatchEvent(new Event('playing'))
    })
    expect(seek).toHaveBeenCalledWith(120)
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2)
  })
})
