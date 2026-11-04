import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SettingsView } from '../../api/types'
import App from '../../app/App'
import { BackendStatusContext } from '../../app/backendStatus'
import { HEALTH, jsonResponse, stubApi } from '../../test/fetch'
import type { Routes } from '../../test/fetch'
import { TourProvider } from './TourProvider'
import { useTour } from './tourContext'

const SPOT_PAD = 8

/** Where the mocked layout puts each `data-tour` element. */
const RECTS: Record<string, { top: number; left: number; width: number; height: number }> = {
  nav: { top: 10, left: 200, width: 400, height: 40 },
  'settings-keys': { top: 120, left: 30, width: 700, height: 300 },
  'add-music': { top: 140, left: 30, width: 700, height: 260 },
  'search-box': { top: 100, left: 30, width: 800, height: 60 },
  'search-filters': { top: 200, left: 30, width: 260, height: 300 },
  // Taller than 45% of the window below the header: shown by its top part only.
  'projects-list': { top: 90, left: 30, width: 300, height: 500 },
  'settings-tutorial': { top: 500, left: 30, width: 700, height: 100 },
}

function settingsView(ui?: { tutorial_seen: boolean }): SettingsView {
  return {
    editable: {
      default_embedder: 'clap',
      llm: {
        enabled: false,
        preset: 'deepseek',
        model: '',
        base_url: '',
        parse_timeout_s: 10,
        rerank_timeout_s: 30,
        rerank_top_n: 20,
      },
      ...(ui ? { ui } : {}),
      search: {
        pool_size: 200,
        max_per_artist: 2,
        min_results: 1,
        weights: { semantic: 0.6, tags: 0.2, bpm: 0.1, energy: 0.1 },
      },
    },
    read_only: {},
    overridden_by_env: [],
    embedders: [{ key: 'clap', model_id: 'laion/clap', commercial_ok: true }],
    llm_presets: [],
  } as SettingsView
}

function api(settings: unknown, extra: Routes = {}) {
  return stubApi({
    'GET /api/health': HEALTH,
    'GET /api/settings': settings,
    'PUT /api/settings': settingsView({ tutorial_seen: true }),
    'GET /api/secrets': { backend: 'file', items: [], known: [] },
    'GET /api/projects': [],
    ...extra,
  })
}

function puts(mock: ReturnType<typeof stubApi>) {
  return mock.mock.calls
    .filter(([input, init]) => String(input) === '/api/settings' && init?.method === 'PUT')
    .map(([, init]) => String(init?.body))
}

/** The search page reads the settings too, so one tour check makes two reads on the default page. */
const READS_WITH_TOUR_CHECK = 2

function settingsGets(mock: ReturnType<typeof stubApi>) {
  return mock.mock.calls.filter(([input, init]) => String(input) === '/api/settings' && (init?.method ?? 'GET') === 'GET').length
}

const card = (title: string) => screen.findByRole('dialog', { name: title })

async function next(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /^(Next|Take the tour|Done)$/ }))
}

beforeEach(() => {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    const r = RECTS[this.getAttribute('data-tour') ?? '']
    const box = r ?? { top: 0, left: 0, width: 0, height: 0 }
    return { ...box, x: box.left, y: box.top, right: box.left + box.width, bottom: box.top + box.height, toJSON() {} }
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Tour: when it starts by itself', () => {
  it('starts on an explicit tutorial_seen false, with the welcome card', async () => {
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    const welcome = await card('Welcome to MCRAR')
    expect(welcome).toHaveAttribute('aria-modal', 'true')
    expect(welcome).toHaveAccessibleDescription(/keeps everything on your PC/)
    expect(screen.queryByText(/Step \d of 7/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('tour-spotlight')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Take the tour' })).toHaveFocus()
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()
  })

  it.each([
    ['settings without a ui part', settingsView()],
    ['tutorial_seen true', settingsView({ tutorial_seen: true })],
    ['a failing request', jsonResponse({ detail: 'broken' }, 500)],
  ])('does not start with %s', async (_name, settings) => {
    const mock = api(settings)
    render(<App />)
    expect(await screen.findByText('Backend online')).toBeInTheDocument()
    await waitFor(() => expect(settingsGets(mock)).toBe(READS_WITH_TOUR_CHECK))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20))
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('does not start while the backend is offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    render(<App />)
    expect(await screen.findByText('Backend offline')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('checks the settings once, however often the status is polled', async () => {
    const mock = api(settingsView({ tutorial_seen: true }))
    render(<App />)
    expect(await screen.findByText('Backend online')).toBeInTheDocument()
    await waitFor(() => expect(settingsGets(mock)).toBe(READS_WITH_TOUR_CHECK))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30))
    })
    expect(settingsGets(mock)).toBe(READS_WITH_TOUR_CHECK)
  })
})

describe('Tour: the steps', () => {
  it('walks through the tabs, spotlighting each target, and Back returns', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    expect(window.location.hash).toBe('')

    const steps: [string, string, string][] = [
      ['Five tabs', '', 'nav'],
      ['Free sources need a key', '#/settings', 'settings-keys'],
      ['Add music', '#/library', 'add-music'],
      ['Describe what you need', '#/search', 'search-box'],
      ['Filters', '#/search', 'search-filters'],
      ['Projects', '#/projects', 'projects-list'],
      ["That's it", '#/settings', 'settings-tutorial'],
    ]
    const expectStep = async (n: number) => {
      const [title, hash, target] = steps[n - 1]!
      await card(title)
      expect(screen.getByText(`Step ${n} of 7`)).toBeInTheDocument()
      const spotlight = await screen.findByTestId('tour-spotlight')
      await waitFor(() => expect(spotlight).toHaveAttribute('data-target', target))
      const r = RECTS[target]!
      // jsdom: a 768 px window and no header height, so a target is cut at 0.45 * 768.
      const shown = Math.min(r.height, 0.45 * window.innerHeight)
      expect(spotlight).toHaveStyle({
        top: `${r.top - SPOT_PAD}px`,
        left: `${r.left - SPOT_PAD}px`,
        width: `${r.width + 2 * SPOT_PAD}px`,
        height: `${shown + 2 * SPOT_PAD}px`,
      })
      if (target === 'projects-list') expect(shown).toBeLessThan(r.height)
      expect(window.location.hash).toBe(hash)
    }

    await next(user)
    await expectStep(1)
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()
    for (let n = 2; n <= 7; n++) {
      await next(user)
      await expectStep(n)
    }
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Skip' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Back' }))
    await expectStep(6)
    await user.click(screen.getByRole('button', { name: 'Back' }))
    await expectStep(5)
  })

  it('places the card next to the spotlight, not over it', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    await next(user)
    const dialog = await card('Five tabs')
    await screen.findByTestId('tour-spotlight')
    // jsdom has no layout (card size 0): below the padded nav box (10 - 8 + 40 + 16 = 58) plus the 12px gap.
    await waitFor(() => expect(dialog.style.top).toBe('70px'))
  })

  it('keeps the cursor keys for text fields', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    const field = screen.getByRole('textbox')
    act(() => field.focus())
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('dialog', { name: 'Welcome to MCRAR' })).toBeInTheDocument()
  })

  it('moves with ArrowRight and ArrowLeft', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    await user.keyboard('{ArrowRight}')
    await card('Five tabs')
    await user.keyboard('{ArrowRight}')
    await card('Free sources need a key')
    await user.keyboard('{ArrowLeft}')
    await card('Five tabs')
    // Back stops at the first real step.
    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('dialog', { name: 'Five tabs' })).toBeInTheDocument()
  })

  it('swallows clicks on the dimmed page', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    await user.click(screen.getByTestId('tour-layer'))
    expect(screen.getByRole('dialog', { name: 'Welcome to MCRAR' })).toBeInTheDocument()
    expect(window.location.hash).toBe('')
  })
})

describe('Tour: closing', () => {
  async function toLastStep(user: ReturnType<typeof userEvent.setup>) {
    for (let n = 0; n < 7 && !screen.queryByRole('button', { name: 'Done' }); n++) await next(user)
    await card("That's it")
  }

  const closers: [string, (user: ReturnType<typeof userEvent.setup>) => Promise<void>][] = [
    ['Skip', async (user) => user.click(screen.getByRole('button', { name: 'Skip' }))],
    ['Escape', async (user) => user.keyboard('{Escape}')],
    [
      'Done',
      async (user) => {
        await toLastStep(user)
        await user.click(screen.getByRole('button', { name: 'Done' }))
      },
    ],
  ]

  it.each(closers)('%s closes, goes back to the start page and saves once', async (_name, close) => {
    const user = userEvent.setup()
    const mock = api(settingsView({ tutorial_seen: false }))
    window.location.hash = '#/library'
    render(<App />)
    await card('Welcome to MCRAR')
    await next(user)
    await next(user)
    await card('Free sources need a key')
    expect(window.location.hash).toBe('#/settings')
    await close(user)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(window.location.hash).toBe('#/library')
    await waitFor(() => expect(puts(mock)).toEqual(['{"ui":{"tutorial_seen":true}}']))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20))
    })
    expect(puts(mock)).toHaveLength(1)
  })

  it('still closes quietly when saving fails', async () => {
    const user = userEvent.setup()
    const mock = api(settingsView({ tutorial_seen: false }), {
      'PUT /api/settings': jsonResponse({ detail: 'disk full' }, 500),
    })
    render(<App />)
    await card('Welcome to MCRAR')
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await waitFor(() => expect(puts(mock)).toHaveLength(1))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText(/disk full/)).not.toBeInTheDocument()
  })

  it('does not start again after it closed', async () => {
    const user = userEvent.setup()
    const mock = api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(puts(mock)).toHaveLength(1))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('Tour: focus', () => {
  it('keeps Tab inside the card', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    await next(user)
    await next(user)
    await card('Free sources need a key')
    const nextButton = screen.getByRole('button', { name: 'Next' })
    expect(nextButton).toHaveFocus()
    // Order: Skip, Back, Next.
    await user.tab()
    expect(screen.getByRole('button', { name: 'Skip' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(nextButton).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Back' })).toHaveFocus()
  })

  it('pulls focus back in when it was lost to the page', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    act(() => screen.getByRole('textbox').focus())
    await user.tab()
    expect(screen.getByRole('button', { name: 'Take the tour' })).toHaveFocus()
  })

  it('moves focus to the new card on every step', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(<App />)
    await card('Welcome to MCRAR')
    await next(user)
    await card('Five tabs')
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus()
    await user.tab()
    await user.keyboard('{ArrowRight}')
    await card('Free sources need a key')
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus()
  })

  it('gives focus back to the control that opened it', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: true }))
    window.location.hash = '#/settings'
    render(<App />)
    const open = await screen.findByRole('button', { name: 'Take the tour again' })
    await user.click(open)
    await card('Welcome to MCRAR')
    expect(screen.getByRole('button', { name: 'Take the tour' })).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Take the tour again' })).toHaveFocus()
  })

  it('gives focus back after the tour left and came back to the page', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: true }))
    window.location.hash = '#/settings'
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Take the tour again' }))
    await card('Welcome to MCRAR')
    await next(user)
    await next(user)
    await next(user)
    await card('Add music')
    expect(window.location.hash).toBe('#/library')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(window.location.hash).toBe('#/settings'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Take the tour again' })).toHaveFocus())
  })
})

describe('Tour: a target that is missing', () => {
  function Harness() {
    const { active } = useTour()
    return <p>{active ? 'tour on' : 'tour off'}</p>
  }

  it('shows the card in the middle with no spotlight, and Next still works', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: false }))
    render(
      <BackendStatusContext.Provider value={{ state: 'online', health: null }}>
        <TourProvider targetTimeoutMs={40}>
          <Harness />
        </TourProvider>
      </BackendStatusContext.Provider>,
    )
    await card('Welcome to MCRAR')
    expect(screen.getByText('tour on')).toBeInTheDocument()
    await next(user)
    await card('Five tabs')
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 120))
    })
    expect(screen.queryByTestId('tour-spotlight')).not.toBeInTheDocument()
    expect(screen.getByTestId('tour-layer').className).toMatch(/dim/)
    await next(user)
    await card('Free sources need a key')
    expect(window.location.hash).toBe('#/settings')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByText('tour off')).toBeInTheDocument())
  })

  it('treats a target without a size as missing', async () => {
    const user = userEvent.setup()
    RECTS['nav'] = { top: 0, left: 0, width: 0, height: 0 }
    try {
      api(settingsView({ tutorial_seen: false }))
      render(<App />)
      await card('Welcome to MCRAR')
      await next(user)
      await card('Five tabs')
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 30))
      })
      expect(screen.queryByTestId('tour-spotlight')).not.toBeInTheDocument()
    } finally {
      RECTS['nav'] = { top: 10, left: 200, width: 400, height: 40 }
    }
  })
})

describe('Tour: from Settings', () => {
  it('opens the welcome card from "Take the tour again"', async () => {
    const user = userEvent.setup()
    api(settingsView({ tutorial_seen: true }))
    window.location.hash = '#/settings'
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Tutorial' })).toBeInTheDocument()
    expect(screen.getByText('A short walk through the main tabs.')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Take the tour again' }))
    expect(await card('Welcome to MCRAR')).toBeInTheDocument()
  })

  it('shows the Tutorial section even when the settings fail to load', async () => {
    api(jsonResponse({ detail: 'broken' }, 500))
    window.location.hash = '#/settings'
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Take the tour again' })).toBeInTheDocument()
  })
})
