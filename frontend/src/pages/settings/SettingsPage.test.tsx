import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { SettingsView } from '../../api/types'
import { BackendStatusContext } from '../../app/backendStatus'
import { jsonResponse, stubApi } from '../../test/fetch'
import type { Routes } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import SettingsPage from './index'

const SECRET = 'jam-client-id-98765'

function view(overrides: Partial<SettingsView['editable']> = {}, extra: Partial<SettingsView> = {}): SettingsView {
  return {
    editable: {
      default_embedder: 'clap',
      search: {
        pool_size: 200,
        max_per_artist: 2,
        min_results: 1,
        weights: { semantic: 0.6, tags: 0.2, bpm: 0.1, energy: 0.1 },
      },
      ...overrides,
    },
    read_only: {
      home: 'D:\\mcrar-home',
      data_dir: 'D:\\mcrar-home\\data',
      models_dir: 'D:\\mcrar-home\\models',
      cache_dir: 'D:\\mcrar-home\\cache',
      secrets_dir: 'D:\\mcrar-home\\secrets',
      secrets_backend: 'file',
      api_host: '127.0.0.1',
      api_port: 8765,
    },
    overridden_by_env: [],
    embedders: [
      { key: 'clap', model_id: 'laion/clap', commercial_ok: true },
      { key: 'muq-mulan', model_id: 'OpenMuQ/MuQ-MuLan', commercial_ok: false },
    ],
    ...extra,
  }
}

const NO_SECRETS = { backend: 'file', items: [], known: [] }

function routes(extra: Routes = {}): Routes {
  return {
    'GET /api/settings': view(),
    'GET /api/secrets': NO_SECRETS,
    ...extra,
  }
}

function putBodies(mock: ReturnType<typeof stubApi>, path: string) {
  return mock.mock.calls
    .filter(([input, init]) => String(input) === path && init?.method === 'PUT')
    .map(([, init]) => JSON.parse(String(init?.body)))
}

describe('Settings: model', () => {
  it('offers a research-only embedder like any other and labels its licence', async () => {
    stubApi(routes())
    renderWithProviders(<SettingsPage />)
    const select = await screen.findByLabelText('Default embedder')
    const muq = within(select).getByRole('option', { name: /muq-mulan/ })
    expect(muq).toBeEnabled()
    expect(muq).toHaveTextContent('research only')
    expect(within(select).getByRole('option', { name: /^clap/ })).toHaveTextContent('commercial use OK')
    expect(screen.getByRole('button', { name: 'Save model' })).toBeDisabled()
  })

  it('saves the chosen embedder', async () => {
    const user = userEvent.setup()
    const open = view()
    const api = stubApi(
      routes({
        'GET /api/settings': open,
        'PUT /api/settings': { ...open, editable: { ...open.editable, default_embedder: 'muq-mulan' } },
      }),
    )
    renderWithProviders(<SettingsPage />)
    await user.selectOptions(await screen.findByLabelText('Default embedder'), 'muq-mulan')
    await user.click(screen.getByRole('button', { name: 'Save model' }))
    await waitFor(() => expect(putBodies(api, '/api/settings')).toEqual([{ default_embedder: 'muq-mulan' }]))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save model' })).toBeDisabled())
  })
})

describe('Settings: environment overrides', () => {
  it('shows a pinned field as read-only with the variable name', async () => {
    stubApi(
      routes({
        'GET /api/settings': view({}, { overridden_by_env: ['default_embedder', 'search.pool_size'] }),
      }),
    )
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByLabelText('Default embedder')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save model' })).toBeDisabled()
    expect(screen.getByText(/environment variable MCRAR_DEFAULT_EMBEDDER/)).toBeInTheDocument()
    expect(screen.getByLabelText('Pool size')).toBeDisabled()
    expect(screen.getByText(/environment variable MCRAR_SEARCH__POOL_SIZE/)).toBeInTheDocument()
    expect(screen.getByLabelText('Max results per artist')).toBeEnabled()
  })

  it('leaves a pinned field out of the tuning update', async () => {
    const user = userEvent.setup()
    const api = stubApi(
      routes({
        'GET /api/settings': view({}, { overridden_by_env: ['search.pool_size'] }),
        'PUT /api/settings': view(),
      }),
    )
    renderWithProviders(<SettingsPage />)
    await user.click(await screen.findByText('Search tuning'))
    await user.click(screen.getByRole('button', { name: 'Save tuning' }))
    await waitFor(() => expect(putBodies(api, '/api/settings')).toHaveLength(1))
    expect(putBodies(api, '/api/settings')[0].search).not.toHaveProperty('pool_size')
  })
})

describe('Settings: search tuning', () => {
  it('saves edited weights', async () => {
    const user = userEvent.setup()
    const api = stubApi(routes({ 'PUT /api/settings': view() }))
    renderWithProviders(<SettingsPage />)
    await user.click(await screen.findByText('Search tuning'))
    const semantic = screen.getByLabelText('Matches the description')
    await user.clear(semantic)
    await user.type(semantic, '0.5')
    await user.click(screen.getByRole('button', { name: 'Save tuning' }))
    await waitFor(() =>
      expect(putBodies(api, '/api/settings')).toEqual([
        {
          search: {
            pool_size: 200,
            max_per_artist: 2,
            min_results: 1,
            weights: { semantic: 0.5, tags: 0.2, bpm: 0.1, energy: 0.1 },
          },
        },
      ]),
    )
  })

  it('refuses invalid numbers without calling the backend', async () => {
    const user = userEvent.setup()
    const api = stubApi(routes())
    renderWithProviders(<SettingsPage />)
    await user.click(await screen.findByText('Search tuning'))
    const pool = screen.getByLabelText('Pool size')
    await user.clear(pool)
    await user.type(pool, '0')
    await user.click(screen.getByRole('button', { name: 'Save tuning' }))
    expect(screen.getByText('Enter a whole number, 1 or more.')).toBeInTheDocument()
    expect(putBodies(api, '/api/settings')).toHaveLength(0)
  })

  it('resets to the defaults', async () => {
    const user = userEvent.setup()
    const tuned = view({
      search: { pool_size: 50, max_per_artist: 5, min_results: 3, weights: { semantic: 1, tags: 0, bpm: 0, energy: 0 } },
    })
    const api = stubApi(routes({ 'GET /api/settings': tuned, 'PUT /api/settings': view() }))
    renderWithProviders(<SettingsPage />)
    await user.click(await screen.findByText('Search tuning'))
    expect(screen.getByLabelText('Pool size')).toHaveValue(50)
    await user.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    await waitFor(() =>
      expect(putBodies(api, '/api/settings')).toEqual([
        {
          search: {
            pool_size: 200,
            max_per_artist: 2,
            min_results: 1,
            weights: { semantic: 0.6, tags: 0.2, bpm: 0.1, energy: 0.1 },
          },
        },
      ]),
    )
    await waitFor(() => expect(screen.getByLabelText('Pool size')).toHaveValue(200))
  })
})

describe('Settings: API keys', () => {
  it('saves the key, clears the input and never shows the value', async () => {
    const user = userEvent.setup()
    let stored = false
    const api = stubApi({
      ...routes(),
      'GET /api/secrets': () => ({
        backend: 'file',
        items: stored ? [{ name: 'jamendo_client_id', source: 'file' }] : [],
        known: [],
      }),
      'PUT /api/secrets/jamendo_client_id': () => {
        stored = true
        return new Response(null, { status: 204 })
      },
    })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText('Not set')).toBeInTheDocument()

    const input = screen.getByLabelText('Client id')
    expect(input).toHaveAttribute('type', 'password')
    expect(input).toHaveAttribute('autocomplete', 'off')
    await user.type(input, SECRET)
    await user.click(screen.getByRole('button', { name: 'Save key' }))

    expect(await screen.findByText('Set (stored in file)')).toBeInTheDocument()
    expect(putBodies(api, '/api/secrets/jamendo_client_id')).toEqual([{ value: SECRET }])
    expect(input).toHaveValue('')
    expect(document.body.textContent).not.toContain(SECRET)
    expect(screen.getByRole('button', { name: 'Remove key' })).toBeEnabled()
    // The toast says it was saved, without the value.
    expect(screen.getByText('Jamendo client id saved.')).toBeInTheDocument()
  })

  it('shows a failed save without repeating the value', async () => {
    const user = userEvent.setup()
    stubApi({
      ...routes(),
      'PUT /api/secrets/jamendo_client_id': jsonResponse({ detail: 'value must be 1 to 4096 characters' }, 422),
    })
    renderWithProviders(<SettingsPage />)
    await user.type(await screen.findByLabelText('Client id'), SECRET)
    await user.click(screen.getByRole('button', { name: 'Save key' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('value must be 1 to 4096 characters')
    expect(screen.getByRole('alert').textContent).not.toContain(SECRET)
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('removes the key after a confirmation', async () => {
    const user = userEvent.setup()
    let stored = true
    const api = stubApi({
      ...routes(),
      'GET /api/secrets': () => ({
        backend: 'file',
        items: stored ? [{ name: 'jamendo_client_id', source: 'file' }] : [],
        known: [],
      }),
      'DELETE /api/secrets/jamendo_client_id': () => {
        stored = false
        return new Response(null, { status: 204 })
      },
    })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText('Set (stored in file)')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove key' }))
    expect(screen.getByText('Remove the Jamendo client id?')).toBeInTheDocument()
    expect(api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Remove it' }))
    expect(await screen.findByText('Not set')).toBeInTheDocument()
    expect(api.mock.calls.some(([u, init]) => String(u) === '/api/secrets/jamendo_client_id' && init?.method === 'DELETE')).toBe(true)
  })

  it('does not offer to remove a key that comes from the environment', async () => {
    stubApi({
      ...routes(),
      'GET /api/secrets': { backend: 'file', items: [{ name: 'jamendo_client_id', source: 'env' }], known: [] },
    })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByText('Set (environment variable)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove key' })).toBeDisabled()
  })
})

describe('Settings: about', () => {
  it('shows the read-only paths, address and version', async () => {
    stubApi(routes())
    renderWithProviders(
      <BackendStatusContext.Provider
        value={{
          state: 'online',
          health: { status: 'ok', version: '1.2.3', catalog: { tracks: 1 }, models_loaded: [] },
        }}
      >
        <SettingsPage />
      </BackendStatusContext.Provider>,
    )
    const about = await screen.findByRole('region', { name: 'About' })
    expect(about).toHaveTextContent('1.2.3')
    expect(about).toHaveTextContent('127.0.0.1:8765')
    expect(about).toHaveTextContent('D:\\mcrar-home\\models')
    expect(about).toHaveTextContent('D:\\mcrar-home\\cache')
  })

  it('shows an error when the settings cannot be loaded', async () => {
    stubApi({ 'GET /api/settings': jsonResponse({ detail: 'boom' }, 500), 'GET /api/secrets': NO_SECRETS })
    renderWithProviders(<SettingsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load the settings: boom")
  })
})
