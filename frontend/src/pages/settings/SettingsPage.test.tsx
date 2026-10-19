import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { LlmPreset, SettingsView } from '../../api/types'
import { BackendStatusContext } from '../../app/backendStatus'
import { jsonResponse, stubApi } from '../../test/fetch'
import type { Routes } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import SettingsPage from './index'

const SECRET = 'jam-client-id-98765'
const LLM_SECRET = 'sk-llm-key-4455667788'

const PRESETS: LlmPreset[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    kind: 'openai',
    base_url: 'https://api.deepseek.com',
    default_model: 'deepseek-chat',
    key_secret: 'llm_api_key_deepseek',
    key_required: true,
    docs_url: 'https://platform.deepseek.com/api_keys',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    kind: 'openai',
    base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o-mini',
    key_secret: 'llm_api_key_openai',
    key_required: true,
    docs_url: 'https://platform.openai.com/api-keys',
  },
  {
    id: 'custom',
    label: 'Custom (OpenAI-compatible)',
    kind: 'openai',
    base_url: '',
    default_model: '',
    key_secret: 'llm_api_key_custom',
    key_required: false,
    docs_url: '',
  },
]

const LLM_SETTINGS = {
  enabled: false,
  preset: 'deepseek',
  model: '',
  base_url: '',
  parse_timeout_s: 10,
  rerank_timeout_s: 30,
  rerank_top_n: 20,
}

function view(overrides: Partial<SettingsView['editable']> = {}, extra: Partial<SettingsView> = {}): SettingsView {
  return {
    editable: {
      default_embedder: 'clap',
      llm: LLM_SETTINGS,
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
    llm_presets: PRESETS,
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

/** The "API keys" section once it has loaded its status. */
async function jamendoKeys() {
  const region = await screen.findByRole('region', { name: 'API keys' })
  return within(region)
}

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
    const keys = await jamendoKeys()
    expect(await keys.findByText('Not set')).toBeInTheDocument()

    const input = keys.getByLabelText('Client id')
    expect(input).toHaveAttribute('type', 'password')
    expect(input).toHaveAttribute('autocomplete', 'off')
    await user.type(input, SECRET)
    await user.click(keys.getByRole('button', { name: 'Save key' }))

    expect(await keys.findByText('Set (stored in file)')).toBeInTheDocument()
    expect(putBodies(api, '/api/secrets/jamendo_client_id')).toEqual([{ value: SECRET }])
    expect(input).toHaveValue('')
    expect(document.body.textContent).not.toContain(SECRET)
    expect(keys.getByRole('button', { name: 'Remove key' })).toBeEnabled()
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
    const keys = await jamendoKeys()
    await user.type(keys.getByLabelText('Client id'), SECRET)
    await user.click(keys.getByRole('button', { name: 'Save key' }))
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
    const keys = await jamendoKeys()
    expect(await keys.findByText('Set (stored in file)')).toBeInTheDocument()
    await user.click(keys.getByRole('button', { name: 'Remove key' }))
    expect(screen.getByText('Remove the Jamendo client id?')).toBeInTheDocument()
    expect(api.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Remove it' }))
    expect(await keys.findByText('Not set')).toBeInTheDocument()
    expect(api.mock.calls.some(([u, init]) => String(u) === '/api/secrets/jamendo_client_id' && init?.method === 'DELETE')).toBe(true)
  })

  it('does not offer to remove a key that comes from the environment', async () => {
    stubApi({
      ...routes(),
      'GET /api/secrets': { backend: 'file', items: [{ name: 'jamendo_client_id', source: 'env' }], known: [] },
    })
    renderWithProviders(<SettingsPage />)
    const keys = await jamendoKeys()
    expect(await keys.findByText('Set (environment variable)')).toBeInTheDocument()
    expect(keys.getByRole('button', { name: 'Remove key' })).toBeDisabled()
  })
})

const llmRegion = async () => within(await screen.findByRole('region', { name: 'LLM' }))

describe('Settings: LLM', () => {
  it('lists the presets in order, with the default model as the placeholder', async () => {
    stubApi(routes())
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    const options = within(llm.getByLabelText('Provider')).getAllByRole('option')
    expect(options.map((option) => option.textContent)).toEqual([
      'DeepSeek',
      'OpenAI',
      'Custom (OpenAI-compatible)',
    ])
    expect(llm.getByRole('switch', { name: 'Use an LLM' })).toHaveAttribute('aria-checked', 'false')
    expect(llm.getByLabelText('Model')).toHaveAttribute('placeholder', 'deepseek-chat')
    expect(llm.getByLabelText('Model')).toHaveValue('')
    expect(llm.getByText(/never audio/)).toBeInTheDocument()
    expect(llm.getByRole('button', { name: 'Save LLM settings' })).toBeDisabled()
  })

  it('saves the draft as one llm update', async () => {
    const user = userEvent.setup()
    const api = stubApi(routes({ 'PUT /api/settings': view() }))
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    await user.click(llm.getByRole('switch', { name: 'Use an LLM' }))
    await user.selectOptions(llm.getByLabelText('Provider'), 'openai')
    await user.type(llm.getByLabelText('Model'), 'gpt-4o')
    await user.click(llm.getByText('Advanced'))
    const topN = llm.getByLabelText('Rerank top N')
    await user.clear(topN)
    await user.type(topN, '30')
    await user.click(llm.getByRole('button', { name: 'Save LLM settings' }))
    await waitFor(() =>
      expect(putBodies(api, '/api/settings')).toEqual([
        { llm: { enabled: true, preset: 'openai', model: 'gpt-4o', base_url: '', rerank_top_n: 30 } },
      ]),
    )
  })

  it('refuses a rerank count outside 5 to 50 and a base URL that is not http(s)', async () => {
    const user = userEvent.setup()
    const api = stubApi(routes({ 'PUT /api/settings': view() }))
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    await user.click(llm.getByText('Advanced'))
    const topN = llm.getByLabelText('Rerank top N')
    await user.clear(topN)
    await user.type(topN, '4')
    await user.type(llm.getByLabelText('Base URL'), 'ftp://example.org')
    await user.click(llm.getByRole('button', { name: 'Save LLM settings' }))
    expect(llm.getByText('Enter a whole number from 5 to 50.')).toBeInTheDocument()
    expect(llm.getByText('Enter an address starting with http:// or https://.')).toBeInTheDocument()
    expect(putBodies(api, '/api/settings')).toHaveLength(0)
  })

  it('shows a pinned field as read-only and leaves it out of the update', async () => {
    const user = userEvent.setup()
    const api = stubApi(
      routes({
        'GET /api/settings': view({}, { overridden_by_env: ['llm.model', 'llm.enabled'] }),
        'PUT /api/settings': view(),
      }),
    )
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    expect(llm.getByRole('switch', { name: 'Use an LLM' })).toBeDisabled()
    expect(llm.getByLabelText('Model')).toBeDisabled()
    expect(llm.getByText(/environment variable MCRAR_LLM__MODEL/)).toBeInTheDocument()
    expect(llm.getByText(/environment variable MCRAR_LLM__ENABLED/)).toBeInTheDocument()
    expect(llm.getByLabelText('Provider')).toBeEnabled()

    await user.selectOptions(llm.getByLabelText('Provider'), 'openai')
    await user.click(llm.getByRole('button', { name: 'Save LLM settings' }))
    await waitFor(() => expect(putBodies(api, '/api/settings')).toHaveLength(1))
    expect(putBodies(api, '/api/settings')[0]).toEqual({
      llm: { preset: 'openai', base_url: '', rerank_top_n: 20 },
    })
  })

  it('keeps a typed model on a provider switch but drops the old default', async () => {
    const user = userEvent.setup()
    stubApi(routes())
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    const model = llm.getByLabelText('Model')
    await user.type(model, 'deepseek-chat')
    await user.selectOptions(llm.getByLabelText('Provider'), 'openai')
    expect(model).toHaveValue('')
    expect(model).toHaveAttribute('placeholder', 'gpt-4o-mini')

    await user.type(model, 'my-finetune')
    await user.selectOptions(llm.getByLabelText('Provider'), 'deepseek')
    expect(model).toHaveValue('my-finetune')
  })

  it('says a model is required for a provider without a default', async () => {
    const user = userEvent.setup()
    stubApi(routes())
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    await user.selectOptions(llm.getByLabelText('Provider'), 'custom')
    expect(llm.getByText(/a model name is required/)).toBeInTheDocument()
    expect(llm.getByText(/Optional for local servers/)).toBeInTheDocument()
  })

  it('sets and removes the key of the selected provider without showing it', async () => {
    const user = userEvent.setup()
    let stored = false
    const api = stubApi({
      ...routes(),
      'GET /api/secrets': () => ({
        backend: 'file',
        items: stored ? [{ name: 'llm_api_key_deepseek', source: 'file' }] : [],
        known: [],
      }),
      'PUT /api/secrets/llm_api_key_deepseek': () => {
        stored = true
        return new Response(null, { status: 204 })
      },
      'DELETE /api/secrets/llm_api_key_deepseek': () => {
        stored = false
        return new Response(null, { status: 204 })
      },
    })
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    expect(await llm.findByText('Not set')).toBeInTheDocument()
    expect(llm.getByRole('link', { name: /Get a key/ })).toHaveAttribute(
      'href',
      'https://platform.deepseek.com/api_keys',
    )
    const input = llm.getByLabelText('API key')
    expect(input).toHaveAttribute('type', 'password')
    await user.type(input, LLM_SECRET)
    await user.click(llm.getByRole('button', { name: 'Save key' }))

    expect(await llm.findByText('Set (stored in file)')).toBeInTheDocument()
    expect(putBodies(api, '/api/secrets/llm_api_key_deepseek')).toEqual([{ value: LLM_SECRET }])
    expect(input).toHaveValue('')
    expect(document.body.textContent).not.toContain(LLM_SECRET)
    expect(screen.getByText('DeepSeek API key saved.')).toBeInTheDocument()

    await user.click(llm.getByRole('button', { name: 'Remove key' }))
    expect(screen.getByText('Remove the DeepSeek API key?')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove it' }))
    expect(await llm.findByText('Not set')).toBeInTheDocument()
    expect(
      api.mock.calls.some(
        ([u, init]) => String(u) === '/api/secrets/llm_api_key_deepseek' && init?.method === 'DELETE',
      ),
    ).toBe(true)
  })

  it('switches the key field to the secret of the chosen provider', async () => {
    const user = userEvent.setup()
    const api = stubApi({
      ...routes(),
      'PUT /api/secrets/llm_api_key_openai': new Response(null, { status: 204 }),
    })
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    expect(llm.getByRole('heading', { name: 'DeepSeek API key' })).toBeInTheDocument()
    await user.type(llm.getByLabelText('API key'), 'half-typed')
    await user.selectOptions(llm.getByLabelText('Provider'), 'openai')
    expect(llm.getByRole('heading', { name: 'OpenAI API key' })).toBeInTheDocument()
    expect(llm.queryByRole('heading', { name: 'DeepSeek API key' })).not.toBeInTheDocument()
    // The half-typed key stayed with the other provider's field.
    expect(llm.getByLabelText('API key')).toHaveValue('')
    await user.type(llm.getByLabelText('API key'), LLM_SECRET)
    await user.click(llm.getByRole('button', { name: 'Save key' }))
    await waitFor(() => expect(putBodies(api, '/api/secrets/llm_api_key_openai')).toEqual([{ value: LLM_SECRET }]))
    expect(document.body.textContent).not.toContain(LLM_SECRET)
  })

  it('tests the draft values before they are saved, and shows the result', async () => {
    const user = userEvent.setup()
    let reply: unknown = { ok: true, model: 'gpt-4o', elapsed_ms: 800 }
    const api = stubApi(routes({ 'POST /api/llm/test': () => reply }))
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    await user.selectOptions(llm.getByLabelText('Provider'), 'openai')
    await user.type(llm.getByLabelText('Model'), 'gpt-4o')
    await user.click(llm.getByRole('button', { name: 'Test connection' }))
    expect(await llm.findByText('Works: gpt-4o replied in 0.8 s')).toBeInTheDocument()
    expect(putBodies(api, '/api/settings')).toHaveLength(0)
    const sent = api.mock.calls
      .filter(([input]) => String(input) === '/api/llm/test')
      .map(([, init]) => JSON.parse(String(init?.body)))
    expect(sent).toEqual([{ preset: 'openai', model: 'gpt-4o', base_url: '' }])

    reply = { ok: false, error: 'Authentication failed (HTTP 401). Check the API key.' }
    await user.click(llm.getByRole('button', { name: 'Test connection' }))
    expect(await llm.findByText('Authentication failed (HTTP 401). Check the API key.')).toBeInTheDocument()
    expect(llm.queryByText(/^Works:/)).not.toBeInTheDocument()
  })

  it('shows a test that could not run', async () => {
    const user = userEvent.setup()
    stubApi(routes({ 'POST /api/llm/test': jsonResponse({ detail: 'unknown preset' }, 422) }))
    renderWithProviders(<SettingsPage />)
    const llm = await llmRegion()
    await user.click(llm.getByRole('button', { name: 'Test connection' }))
    expect(await llm.findByText('unknown preset')).toBeInTheDocument()
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
