import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HEALTH, stubApi } from '../test/fetch'
import App from './App'

afterEach(() => {
  vi.useRealTimers()
})

function goTo(hash: string) {
  act(() => {
    window.location.hash = hash
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}

describe('App shell', () => {
  it('shows the search page by default, with the four tabs', async () => {
    stubApi({ 'GET /api/health': HEALTH })
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Search' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    const tabs = within(nav).getAllByRole('link')
    expect(tabs.map((tab) => tab.textContent)).toEqual(['Search', 'Projects', 'Library', 'Settings'])
    expect(within(nav).getByRole('link', { name: 'Search' })).toHaveAttribute('aria-current', 'page')
    expect(await screen.findByText('Backend online')).toBeInTheDocument()
  })

  it('switches pages with the URL hash', async () => {
    stubApi({ 'GET /api/health': HEALTH })
    render(<App />)
    goTo('#/projects')
    expect(screen.getByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Search' })).not.toHaveAttribute('aria-current')

    goTo('#/library')
    expect(screen.getByRole('heading', { level: 1, name: 'Library' })).toBeInTheDocument()
    goTo('#/settings')
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument()
    goTo('#/unknown')
    expect(screen.getByRole('heading', { level: 1, name: 'Search' })).toBeInTheDocument()
    expect(await screen.findByText('Backend online')).toBeInTheDocument()
  })

  it('opens a page when its tab is clicked and starts from a deep link', async () => {
    stubApi({ 'GET /api/health': HEALTH })
    window.location.hash = '#/projects/12'
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Settings' }))
    expect(window.location.hash).toBe('#/settings')
    expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument()
  })

  it('shows an offline banner with the start command when the backend is down', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    render(<App />)
    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent("Can't reach the backend")
    expect(banner).toHaveTextContent('mcrar serve')
    expect(screen.getByText('Backend offline')).toBeInTheDocument()
  })

  it('treats a non-JSON answer as offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html></html>', { status: 200 })))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('mcrar serve')
  })

  it('reconnects by itself when the backend comes back', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()

    stubApi({ 'GET /api/health': HEALTH })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('Backend online')).toBeInTheDocument()
  })
})
