import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useHashRoute } from '../../app/route'
import { jsonResponse, stubApi } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import ProjectsPage from '.'

function Routed() {
  const route = useHashRoute()
  return <ProjectsPage subpath={route.subpath} params={route.params} />
}

const PROJECTS = [
  { id: 1, name: 'Level 1', created_at: '2026-10-01T12:00:00Z', item_count: 3 },
  { id: 2, name: 'Trailer', created_at: '2026-10-02T12:00:00Z', item_count: 0 },
]

function entry(
  id: number,
  title: string,
  risk: string,
  note: string | null = null,
  extra: Record<string, unknown> = {},
) {
  return {
    track: {
      id,
      title,
      artist: `Artist ${id}`,
      source: 'jamendo',
      duration_s: 187,
      risk,
      license_code: risk === 'red' ? 'CC BY-NC 4.0' : 'CC BY 4.0',
      source_id: `jam-${id}`,
      source_url: null,
      download_url: null,
      license_url: 'https://example.org/by',
      commercial_license_url: null,
      attribution_text: `${title} by Artist ${id}`,
      ...extra,
    },
    note,
    added_at: '2026-10-05T12:00:00Z',
  }
}

const ITEMS = [
  entry(10, 'Rainy Window', 'green'),
  entry(11, 'Forest Walk', 'green', 'Level 2 intro'),
  entry(12, 'Dark Alley', 'red'),
]

const DETAIL = { ...PROJECTS[0], items: ITEMS }
// No restricted track, so no licence warning (which is an alert too).
const SAFE_DETAIL = { ...PROJECTS[0], items: ITEMS.slice(0, 2) }
const NO_CONTENT = () => new Response(null, { status: 204 })

/** The shortlist row of a track. */
const rowOf = (title: string) => screen.getByText(title).closest('li') as HTMLElement

/** Opens the note field of a track: "Add note" when empty, a click on the text otherwise. */
async function openNote(user: ReturnType<typeof userEvent.setup>, title: string) {
  const row = (await screen.findByText(title)).closest('li') as HTMLElement
  const add = within(row).queryByRole('button', { name: 'Add note' })
  if (add) await user.click(add)
  else await user.click(within(row).getByTitle(/^Saves as you type/))
  return within(row).getByRole('textbox', { name: `Note for ${title}` }) as HTMLTextAreaElement
}

function calls(api: ReturnType<typeof stubApi>, method: string) {
  return api.mock.calls.filter(([, init]) => init?.method === method)
}

beforeEach(() => {
  window.location.hash = ''
})

describe('Projects page', () => {
  it('lists the projects with their track count and selects one from the hash', async () => {
    window.location.hash = '#/projects/1'
    stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DETAIL })
    renderWithProviders(<Routed />)

    const link = await screen.findByRole('link', { name: /Level 1/ })
    expect(link).toHaveTextContent('3 tracks')
    expect(link).toHaveTextContent('2026')
    expect(link).toHaveAttribute('href', '#/projects/1')
    expect(link).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: /Trailer/ })).not.toHaveAttribute('aria-current')
    expect(await screen.findByRole('heading', { level: 2, name: 'Level 1' })).toBeInTheDocument()
    expect(screen.getByText('Rainy Window')).toBeInTheDocument()
  })

  it('changes the selected project when the hash changes', async () => {
    window.location.hash = '#/projects'
    stubApi({
      'GET /api/projects': PROJECTS,
      'GET /api/projects/2': { ...PROJECTS[1], items: [] },
    })
    renderWithProviders(<Routed />)
    expect(await screen.findByText('Pick a project')).toBeInTheDocument()

    await userEvent.setup().click(await screen.findByRole('link', { name: /Trailer/ }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Trailer' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/projects/2')
  })

  it('shows a not-found notice for an unknown project', async () => {
    window.location.hash = '#/projects/99'
    stubApi({
      'GET /api/projects': PROJECTS,
      'GET /api/projects/99': jsonResponse({ detail: 'no project with id 99' }, 404),
    })
    renderWithProviders(<Routed />)
    expect(await screen.findByText('Project not found')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to projects' })).toHaveAttribute(
      'href',
      '#/projects',
    )
  })

  it('shows a not-found notice for an id that is not a number', async () => {
    window.location.hash = '#/projects/abc'
    stubApi({ 'GET /api/projects': PROJECTS })
    renderWithProviders(<Routed />)
    expect(await screen.findByText('Project not found')).toBeInTheDocument()
  })

  it('invites to create a project when there are none', async () => {
    stubApi({ 'GET /api/projects': [] })
    renderWithProviders(<Routed />)
    expect(await screen.findByText('No projects yet')).toBeInTheDocument()
    expect(
      screen.getAllByText('Create a project to collect tracks for a game or level.').length,
    ).toBeGreaterThan(0)
  })

  it('shows the empty shortlist hint for a project without tracks', async () => {
    window.location.hash = '#/projects/2'
    stubApi({
      'GET /api/projects': PROJECTS,
      'GET /api/projects/2': { ...PROJECTS[1], items: [] },
    })
    renderWithProviders(<Routed />)
    expect(await screen.findByText('Add tracks from Search with the + button.')).toBeInTheDocument()
    expect(screen.queryByText('Credits')).not.toBeInTheDocument()
  })

  describe('creating', () => {
    it('creates a project and opens it', async () => {
      const user = userEvent.setup()
      const created = { id: 5, name: 'Boss fight', created_at: '2026-10-15T12:00:00Z', item_count: 0 }
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'POST /api/projects': jsonResponse(created, 201),
        'GET /api/projects/5': { ...created, items: [] },
      })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'New project' }))
      await user.type(screen.getByRole('textbox', { name: 'Project name' }), '  Boss fight ')
      await user.click(screen.getByRole('button', { name: 'Create' }))

      expect(await screen.findByRole('heading', { level: 2, name: 'Boss fight' })).toBeInTheDocument()
      expect(window.location.hash).toBe('#/projects/5')
      expect(calls(api, 'POST')[0]?.[1]?.body).toBe('{"name":"Boss fight"}')
      expect(screen.queryByRole('textbox', { name: 'Project name' })).not.toBeInTheDocument()
    })

    it('shows the detail of a duplicate name and keeps the form', async () => {
      const user = userEvent.setup()
      stubApi({
        'GET /api/projects': PROJECTS,
        'POST /api/projects': jsonResponse({ detail: 'a project named Level 1 already exists' }, 422),
      })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'New project' }))
      await user.type(screen.getByRole('textbox', { name: 'Project name' }), 'Level 1')
      await user.click(screen.getByRole('button', { name: 'Create' }))

      expect(await screen.findByText('a project named Level 1 already exists')).toBeInTheDocument()
      expect(screen.getByRole('textbox', { name: 'Project name' })).toHaveValue('Level 1')
      expect(window.location.hash).toBe('')
    })

    it('does not allow an empty name', async () => {
      const user = userEvent.setup()
      stubApi({ 'GET /api/projects': PROJECTS })
      renderWithProviders(<Routed />)
      await user.click(await screen.findByRole('button', { name: 'New project' }))
      expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled()
    })
  })

  describe('a project', () => {
    beforeEach(() => {
      window.location.hash = '#/projects/1'
    })

    it('renames with Enter', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'PATCH /api/projects/1': { ...PROJECTS[0], name: 'Level One' },
      })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Rename' }))
      const input = screen.getByRole('textbox', { name: 'New name' })
      expect(input).toHaveValue('Level 1')
      await user.clear(input)
      await user.type(input, 'Level One{Enter}')

      expect(await screen.findByRole('heading', { level: 2, name: 'Level One' })).toBeInTheDocument()
      expect(calls(api, 'PATCH')[0]?.[1]?.body).toBe('{"name":"Level One"}')
      expect(screen.queryByRole('textbox', { name: 'New name' })).not.toBeInTheDocument()
    })

    it('cancels a rename with Escape', async () => {
      const user = userEvent.setup()
      const api = stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DETAIL })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Rename' }))
      await user.type(screen.getByRole('textbox', { name: 'New name' }), 'x{Escape}')

      expect(screen.getByRole('heading', { level: 2, name: 'Level 1' })).toBeInTheDocument()
      expect(calls(api, 'PATCH')).toHaveLength(0)
    })

    it('shows the detail when the new name is taken', async () => {
      const user = userEvent.setup()
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'PATCH /api/projects/1': jsonResponse({ detail: 'a project named Trailer already exists' }, 422),
      })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Rename' }))
      const input = screen.getByRole('textbox', { name: 'New name' })
      await user.clear(input)
      await user.type(input, 'Trailer{Enter}')

      expect(await screen.findByText('a project named Trailer already exists')).toBeInTheDocument()
      expect(screen.getByRole('textbox', { name: 'New name' })).toBeInTheDocument()
    })

    it('asks to confirm before deleting, and cancel keeps the project', async () => {
      const user = userEvent.setup()
      const api = stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DETAIL })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Delete project' }))
      expect(
        screen.getByText('Delete project? This removes its shortlist, not the tracks.'),
      ).toBeInTheDocument()
      await user.click(screen.getByRole('button', { name: 'Cancel' }))

      expect(screen.getByRole('button', { name: 'Delete project' })).toBeInTheDocument()
      expect(calls(api, 'DELETE')).toHaveLength(0)
    })

    it('deletes the project after confirmation and goes back to the list', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'DELETE /api/projects/1': NO_CONTENT,
      })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Delete project' }))
      await user.click(screen.getByRole('button', { name: 'Confirm' }))

      await waitFor(() => expect(window.location.hash).toBe('#/projects'))
      expect(calls(api, 'DELETE')[0]?.[0]).toBe('/api/projects/1')
      expect(await screen.findByText('Pick a project')).toBeInTheDocument()
    })

    it('summarises the licences and warns about restricted tracks', async () => {
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': {
          ...DETAIL,
          items: [
            entry(1, 'A', 'green'),
            entry(2, 'B', 'green'),
            entry(3, 'C', 'green'),
            entry(4, 'D', 'amber'),
            entry(5, 'E', 'red'),
          ],
        },
      })
      renderWithProviders(<Routed />)

      expect(await screen.findByText(/3 safe/)).toBeInTheDocument()
      const summary = screen.getByText(/3 safe/).closest('p')
      expect(summary).toHaveTextContent('3 safe · 1 check terms · 1 restricted')
      expect(summary).not.toHaveTextContent('unknown')
      expect(screen.getByRole('alert')).toHaveTextContent(
        "Restricted licences (NC/ND) usually can't be used in a commercial game.",
      )
    })

    it('does not warn when nothing is restricted', async () => {
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': { ...DETAIL, items: [entry(1, 'A', 'green'), entry(2, 'B', 'amber')] },
      })
      renderWithProviders(<Routed />)
      expect(await screen.findByText(/1 safe/)).toBeInTheDocument()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('shows each track with its licence, duration and note', async () => {
      stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DETAIL })
      renderWithProviders(<Routed />)

      const row = (await screen.findByText('Forest Walk')).closest('li') as HTMLElement
      expect(within(row).getByText('Artist 11')).toBeInTheDocument()
      expect(within(row).getByText('3:07')).toBeInTheDocument()
      expect(within(row).getByText(/CC BY 4.0/)).toBeInTheDocument()
      expect(within(row).getByText('Level 2 intro')).toBeInTheDocument()
      const red = (screen.getByText('Dark Alley')).closest('li') as HTMLElement
      expect(within(red).getByText('Restricted')).toBeInTheDocument()
    })

    it('plays a track from the shortlist', async () => {
      const user = userEvent.setup()
      stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DETAIL })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Play Rainy Window' }))
      expect(await screen.findByRole('button', { name: 'Pause Rainy Window' })).toBeInTheDocument()
    })

    it('saves a note when the field loses focus', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'PUT /api/projects/1/items/10': entry(10, 'Rainy Window', 'green', 'Menu music'),
      })
      renderWithProviders(<Routed />)

      const field = await openNote(user, 'Rainy Window')
      await user.type(field, 'Menu music')
      expect(calls(api, 'PUT')).toHaveLength(0)
      await user.tab()

      expect(await screen.findByText('Saved')).toBeInTheDocument()
      const put = calls(api, 'PUT')[0]
      expect(put?.[0]).toBe('/api/projects/1/items/10')
      expect(put?.[1]?.body).toBe('{"note":"Menu music"}')
    })

    it('saves a note with Ctrl+Enter only once', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'PUT /api/projects/1/items/10': entry(10, 'Rainy Window', 'green', 'x'),
      })
      renderWithProviders(<Routed />)

      const field = await openNote(user, 'Rainy Window')
      await user.type(field, 'x{Control>}{Enter}{/Control}')
      expect(await screen.findByText('Saved')).toBeInTheDocument()
      await user.tab()
      expect(calls(api, 'PUT')).toHaveLength(1)
    })

    it('does not save an unchanged note', async () => {
      const user = userEvent.setup()
      const api = stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DETAIL })
      renderWithProviders(<Routed />)
      const field = await openNote(user, 'Forest Walk')
      expect(field).toHaveValue('Level 2 intro')
      await user.click(field)
      await user.tab()
      expect(calls(api, 'PUT')).toHaveLength(0)
    })

    it('clears a note by sending none, and limits it to 2000 characters', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'PUT /api/projects/1/items/11': entry(11, 'Forest Walk', 'green'),
      })
      renderWithProviders(<Routed />)

      const field = await openNote(user, 'Forest Walk')
      expect(field).toHaveAttribute('maxlength', '2000')
      await user.clear(field)
      await user.tab()

      await screen.findByText('Saved')
      expect(calls(api, 'PUT')[0]?.[1]?.body).toBeUndefined()
    })

    it('shows an error and no "Saved" when a note cannot be saved', async () => {
      const user = userEvent.setup()
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': SAFE_DETAIL,
        'PUT /api/projects/1/items/10': jsonResponse({ detail: 'database is locked' }, 500),
      })
      renderWithProviders(<Routed />)

      await user.type(await openNote(user, 'Rainy Window'), 'x')
      await user.tab()

      expect(await screen.findByRole('alert')).toHaveTextContent('database is locked')
      expect(await screen.findByText("Couldn't save")).toBeInTheDocument()
      expect(screen.queryByText('Saved')).not.toBeInTheDocument()
      // The text is still there to read and to save again.
      expect(screen.getByText('x')).toBeInTheDocument()
    })

    it('removes a track at once and can undo it with its note', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'DELETE /api/projects/1/items/11': NO_CONTENT,
        'PUT /api/projects/1/items/11': ITEMS[1],
      })
      renderWithProviders(<Routed />)

      const remove = await screen.findByRole('button', { name: 'Remove Forest Walk from the project' })
      expect(remove).toHaveTextContent('Remove')
      await user.click(remove)

      expect(await screen.findByText('Removed "Forest Walk" from the shortlist.')).toBeInTheDocument()
      expect(screen.queryByText('Level 2 intro')).not.toBeInTheDocument()
      expect(calls(api, 'DELETE')[0]?.[0]).toBe('/api/projects/1/items/11')
      expect(screen.getByText(/1 safe/)).toBeInTheDocument()

      await user.click(screen.getByRole('button', { name: 'Undo' }))
      expect(await screen.findByText('Level 2 intro')).toBeInTheDocument()
      expect(calls(api, 'PUT')[0]?.[1]?.body).toBe('{"note":"Level 2 intro"}')
      expect(screen.queryByText('Removed "Forest Walk" from the shortlist.')).not.toBeInTheDocument()
    })

    it('does not save a note that was still waiting when its track was removed', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': SAFE_DETAIL,
        'DELETE /api/projects/1/items/10': NO_CONTENT,
        // The backend's PUT is an upsert: a late save would add the track again.
        'PUT /api/projects/1/items/10': entry(10, 'Rainy Window', 'green', 'late'),
      })
      renderWithProviders(<Routed />)

      await user.type(await openNote(user, 'Rainy Window'), 'late')
      // A click event without moving the focus: the note has not been saved by a blur.
      fireEvent.click(screen.getByRole('button', { name: 'Remove Rainy Window from the project' }))

      expect(await screen.findByText('Removed "Rainy Window" from the shortlist.')).toBeInTheDocument()
      expect(screen.queryByText('late')).not.toBeInTheDocument()
      expect(calls(api, 'DELETE')).toHaveLength(1)
      expect(calls(api, 'PUT')).toHaveLength(0)
    })

    it('saves a note again when removing its track failed', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': SAFE_DETAIL,
        'DELETE /api/projects/1/items/10': jsonResponse({ detail: 'nope' }, 500),
        'PUT /api/projects/1/items/10': entry(10, 'Rainy Window', 'green', 'kept'),
      })
      renderWithProviders(<Routed />)

      const field = await openNote(user, 'Rainy Window')
      await user.type(field, 'kept')
      fireEvent.click(screen.getByRole('button', { name: 'Remove Rainy Window from the project' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('nope')
      await user.tab()
      await screen.findByText('Saved')
      expect(calls(api, 'PUT')[0]?.[1]?.body).toBe('{"note":"kept"}')
    })

    it('keeps the track and shows the error when removing fails', async () => {
      const user = userEvent.setup()
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': SAFE_DETAIL,
        'DELETE /api/projects/1/items/10': jsonResponse({ detail: 'nope' }, 500),
      })
      renderWithProviders(<Routed />)
      await user.click(await screen.findByRole('button', { name: 'Remove Rainy Window from the project' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('nope')
      expect(screen.getByText('Rainy Window')).toBeInTheDocument()
    })
  })

  describe('a shortlist row', () => {
    const DOWNLOADABLE = {
      ...DETAIL,
      items: [
        entry(10, 'Rainy Window', 'green', null, {
          download_url: 'https://example.org/dl/10',
          license_url: 'https://example.org/by',
          commercial_license_url: 'https://example.org/buy',
        }),
        entry(11, 'Forest Walk', 'green'),
      ],
    }
    const TRACK_10 = {
      ...DOWNLOADABLE.items[0]?.track,
      album: null,
      release_date: null,
      image_url: null,
      vocal_instrumental: null,
      local_path: null,
      stream_url: '/api/tracks/10/stream',
      features: null,
      tags: [],
      license: {
        code: 'CC BY 4.0',
        url: 'https://example.org/by',
        family: null,
        risk: 'green',
        commercial_ok: null,
        derivatives_ok: null,
        share_alike: null,
        attribution_required: null,
        attribution_text: 'Rainy Window by Artist 10',
        commercial_license_url: null,
      },
    }

    beforeEach(() => {
      window.location.hash = '#/projects/1'
    })

    it('opens the track details from the title, with Find similar in them', async () => {
      const user = userEvent.setup()
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DOWNLOADABLE,
        'GET /api/tracks/10': TRACK_10,
      })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Rainy Window' }))
      const dialog = await screen.findByRole('dialog')
      expect(await within(dialog).findByText('Audio features')).toBeInTheDocument()

      await user.click(within(dialog).getByRole('button', { name: 'Find similar' }))
      expect(window.location.hash).toBe('#/search?similar=10')
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('names the source of each track, and shows an unknown source as it is', async () => {
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': {
          ...DETAIL,
          items: [
            entry(10, 'Rainy Window', 'green'),
            entry(11, 'Forest Walk', 'green', null, { source: 'local' }),
            entry(12, 'Dark Alley', 'green', null, { source: 'spotify' }),
          ],
        },
      })
      renderWithProviders(<Routed />)

      await screen.findByText('Rainy Window')
      expect(within(rowOf('Rainy Window')).getByText('Jamendo')).toBeInTheDocument()
      expect(within(rowOf('Forest Walk')).getByText('Local')).toBeInTheDocument()
      expect(within(rowOf('Dark Alley')).getByText('spotify')).toBeInTheDocument()
    })

    it('opens the licence details from the badge', async () => {
      const user = userEvent.setup()
      stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DOWNLOADABLE })
      renderWithProviders(<Routed />)

      await screen.findByText('Rainy Window')
      const row = rowOf('Rainy Window')
      expect(screen.queryByText('Rainy Window by Artist 10')).not.toBeInTheDocument()
      await user.click(within(row).getByRole('button', { name: /^Licence/ }))

      expect(screen.getByText('Rainy Window by Artist 10')).toBeInTheDocument()
      expect(screen.getByRole('link', { name: /Read the licence/ })).toHaveAttribute(
        'href',
        'https://example.org/by',
      )
      expect(screen.getByRole('link', { name: /Buy a commercial licence/ })).toHaveAttribute(
        'href',
        'https://example.org/buy',
      )
    })

    it('shows Download only for a track with a download_url, and opens it with the licence file', async () => {
      const user = userEvent.setup()
      stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DOWNLOADABLE })
      const open = vi.fn()
      vi.stubGlobal('open', open)
      const clicked: string[] = []
      vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this.getAttribute('href') ?? '')
      })
      renderWithProviders(<Routed />)

      await screen.findByText('Rainy Window')
      expect(within(rowOf('Forest Walk')).queryByRole('button', { name: /^Download/ })).not.toBeInTheDocument()
      await user.click(within(rowOf('Rainy Window')).getByRole('button', { name: /^Download/ }))
      expect(open).toHaveBeenCalledWith('https://example.org/dl/10', '_blank', 'noopener')
      expect(clicked).toEqual(['/api/tracks/10/credits?format=txt'])
    })

    it('goes to the search for tracks like this one', async () => {
      const user = userEvent.setup()
      stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DOWNLOADABLE })
      renderWithProviders(<Routed />)

      await screen.findByText('Forest Walk')
      await user.click(within(rowOf('Forest Walk')).getByRole('button', { name: 'Find similar to Forest Walk' }))
      expect(window.location.hash).toBe('#/search?similar=11')
    })

    it('gives the player the licence details, so its badge opens them too', async () => {
      const user = userEvent.setup()
      stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DOWNLOADABLE })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Play Rainy Window' }))
      const bar = await screen.findByRole('region', { name: 'Audio player' })
      await user.click(within(bar).getByRole('button', { name: /^Licence/ }))
      expect(screen.getByText('Rainy Window by Artist 10')).toBeInTheDocument()
    })
  })

  describe('credits', () => {
    beforeEach(() => {
      window.location.hash = '#/projects/1'
    })

    it('links to the three export formats as downloads, with the disclaimer', async () => {
      stubApi({ 'GET /api/projects': PROJECTS, 'GET /api/projects/1': DETAIL })
      renderWithProviders(<Routed />)

      const txt = await screen.findByRole('link', { name: 'Text (.txt)' })
      expect(txt).toHaveAttribute('href', '/api/projects/1/credits?format=txt')
      expect(txt).toHaveAttribute('download')
      const md = screen.getByRole('link', { name: 'Markdown (.md)' })
      expect(md).toHaveAttribute('href', '/api/projects/1/credits?format=md')
      expect(md).toHaveAttribute('download')
      const json = screen.getByRole('link', { name: 'JSON (.json)' })
      expect(json).toHaveAttribute('href', '/api/projects/1/credits?format=json')
      expect(json).toHaveAttribute('download')
      expect(screen.getByText(/not legal advice/)).toBeInTheDocument()
    })

    it('previews the credits and copies them', async () => {
      const user = userEvent.setup()
      const api = stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'GET /api/projects/1/credits': (url: URL) =>
          new Response(url.searchParams.get('format') === 'txt' ? 'Plain credits' : '# Credits\n- Rainy Window', {
            headers: { 'Content-Type': 'text/plain' },
          }),
      })
      renderWithProviders(<Routed />)

      await user.click(await screen.findByRole('button', { name: 'Preview' }))
      const panel = await screen.findByLabelText('Credits preview')
      expect(panel).toHaveTextContent('# Credits - Rainy Window')
      expect(api.mock.calls.at(-1)?.[0]).toBe('/api/projects/1/credits?format=md')

      await user.click(screen.getByRole('button', { name: 'Copy' }))
      expect(await screen.findByText('Copied to the clipboard')).toBeInTheDocument()
      expect(await navigator.clipboard.readText()).toBe('# Credits\n- Rainy Window')

      await user.selectOptions(screen.getByLabelText('Preview format'), 'txt')
      expect(await screen.findByText('Plain credits')).toBeInTheDocument()
      expect(api.mock.calls.at(-1)?.[0]).toBe('/api/projects/1/credits?format=txt')

      await user.click(screen.getByRole('button', { name: 'Hide preview' }))
      expect(screen.queryByLabelText('Credits preview')).not.toBeInTheDocument()
    })

    it('says so when the clipboard is not available', async () => {
      const user = userEvent.setup()
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': DETAIL,
        'GET /api/projects/1/credits': new Response('text'),
      })
      renderWithProviders(<Routed />)
      await user.click(await screen.findByRole('button', { name: 'Preview' }))
      await screen.findByLabelText('Credits preview')
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })

      await user.click(screen.getByRole('button', { name: 'Copy' }))
      expect(await screen.findByText(/Couldn't copy automatically/)).toBeInTheDocument()
    })

    it('shows the error when the preview cannot be loaded', async () => {
      const user = userEvent.setup()
      stubApi({
        'GET /api/projects': PROJECTS,
        'GET /api/projects/1': SAFE_DETAIL,
        'GET /api/projects/1/credits': jsonResponse({ detail: 'credits are broken' }, 500),
      })
      renderWithProviders(<Routed />)
      await user.click(await screen.findByRole('button', { name: 'Preview' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('credits are broken')
    })
  })
})
