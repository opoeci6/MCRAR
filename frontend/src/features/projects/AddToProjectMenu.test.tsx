import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { jsonResponse, stubApi } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import { AddToProjectMenu } from './AddToProjectMenu'

const PROJECTS = [
  { id: 1, name: 'Level 1', created_at: '2026-10-01', item_count: 2 },
  { id: 2, name: 'Trailer', created_at: '2026-10-02', item_count: 0 },
]

const ENTRY = { track: { id: 5 }, note: null, added_at: '2026-10-15' }

describe('AddToProjectMenu', () => {
  it('lists the projects and adds the track to the one picked', async () => {
    const user = userEvent.setup()
    const api = stubApi({
      'GET /api/projects': PROJECTS,
      'PUT /api/projects/2/items/5': ENTRY,
    })
    renderWithProviders(<AddToProjectMenu trackId={5} trackTitle="Rainy Window" />)

    await user.click(screen.getByRole('button', { name: 'Add to project' }))
    expect(await screen.findByRole('button', { name: /Level 1/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Trailer/ })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Trailer/ }))
    expect(await screen.findByRole('status')).toHaveTextContent('Added "Rainy Window" to Trailer')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const put = api.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(put?.[0]).toBe('/api/projects/2/items/5')
  })

  it('creates a project and adds the track to it', async () => {
    const user = userEvent.setup()
    const api = stubApi({
      'GET /api/projects': [],
      'POST /api/projects': jsonResponse({ id: 9, name: 'Boss fight', created_at: 'x', item_count: 0 }, 201),
      'PUT /api/projects/9/items/5': ENTRY,
    })
    renderWithProviders(<AddToProjectMenu trackId={5} trackTitle="Rainy Window" />)

    await user.click(screen.getByRole('button', { name: 'Add to project' }))
    expect(await screen.findByText(/No projects yet/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'New project…' }))
    await user.type(screen.getByRole('textbox', { name: 'Project name' }), '  Boss fight ')
    await user.click(screen.getByRole('button', { name: 'Create and add' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Created Boss fight and added "Rainy Window"')
    const post = api.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(post?.[1]?.body).toBe('{"name":"Boss fight"}')
  })

  it('does not allow an empty project name', async () => {
    const user = userEvent.setup()
    stubApi({ 'GET /api/projects': [] })
    renderWithProviders(<AddToProjectMenu trackId={5} trackTitle="x" />)
    await user.click(screen.getByRole('button', { name: 'Add to project' }))
    await user.click(await screen.findByRole('button', { name: 'New project…' }))
    expect(screen.getByRole('button', { name: 'Create and add' })).toBeDisabled()
  })

  it('shows the error of a failed add as a toast and keeps the menu open', async () => {
    const user = userEvent.setup()
    stubApi({
      'GET /api/projects': PROJECTS,
      'PUT /api/projects/1/items/5': jsonResponse({ detail: 'no track with id 5' }, 404),
    })
    renderWithProviders(<AddToProjectMenu trackId={5} trackTitle="Rainy Window" />)
    await user.click(screen.getByRole('button', { name: 'Add to project' }))
    await user.click(await screen.findByRole('button', { name: /Level 1/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('no track with id 5')
    expect(screen.getByRole('button', { name: /Level 1/ })).toBeEnabled()
  })

  it('shows a retry when the projects cannot be loaded', async () => {
    const user = userEvent.setup()
    stubApi({ 'GET /api/projects': jsonResponse({ detail: 'database is locked' }, 500) })
    renderWithProviders(<AddToProjectMenu trackId={5} trackTitle="x" />)
    await user.click(screen.getByRole('button', { name: 'Add to project' }))
    expect(await screen.findByText('database is locked')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
