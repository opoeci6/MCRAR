import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../app/ToastProvider'
import { jsonResponse, stubApi } from '../../test/fetch'
import { TrackDrawer } from './TrackDrawer'

const DETAIL = {
  id: 5,
  title: 'Rainy Window',
  artist: 'Jane Doe',
  risk: 'green',
  license_code: 'CC BY 4.0',
  license: {
    code: 'CC BY 4.0',
    url: 'https://example.org/by',
    risk: 'green',
    attribution_text: 'Rainy Window by Jane Doe',
    commercial_license_url: null,
  },
}

const wrap = (trackId: number | null, onClose = () => {}) =>
  render(
    <ToastProvider>
      <TrackDrawer trackId={trackId} onClose={onClose} />
    </ToastProvider>,
  )

describe('TrackDrawer', () => {
  it('stays closed without a track', () => {
    stubApi({})
    wrap(null)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('loads and shows the track, and closes on request', async () => {
    stubApi({ 'GET /api/tracks/5': DETAIL })
    const onClose = vi.fn()
    wrap(5, onClose)
    expect(await screen.findByRole('heading', { name: 'Rainy Window' })).toBeInTheDocument()
    expect(screen.getByText('Jane Doe')).toBeInTheDocument()
    expect(screen.getByText('Safe')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('shows the error when the track cannot be loaded', async () => {
    stubApi({ 'GET /api/tracks/5': jsonResponse({ detail: 'no track with id 5' }, 404) })
    wrap(5)
    expect(await screen.findByRole('alert')).toHaveTextContent('no track with id 5')
  })
})
