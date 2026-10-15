import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { ToastProvider } from '../app/ToastProvider'
import { PlayerBar } from '../player/PlayerBar'
import { PlayerProvider } from '../player/PlayerProvider'

/** Renders `ui` inside the toast and player providers, with the player bar. */
export function renderWithProviders(ui: ReactElement) {
  return render(
    <ToastProvider>
      <PlayerProvider>
        {ui}
        <PlayerBar />
      </PlayerProvider>
    </ToastProvider>,
  )
}
