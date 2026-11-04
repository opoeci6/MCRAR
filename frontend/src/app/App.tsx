import { TourProvider } from '../features/tour/TourProvider'
import { PlayerProvider } from '../player/PlayerProvider'
import { BackendStatusProvider } from './BackendStatusProvider'
import { Shell } from './Shell'
import { ToastProvider } from './ToastProvider'

/** The providers (toasts, backend status, tour, player) around the shell. */
export default function App() {
  return (
    <ToastProvider>
      <BackendStatusProvider>
        <TourProvider>
          <PlayerProvider>
            <Shell />
          </PlayerProvider>
        </TourProvider>
      </BackendStatusProvider>
    </ToastProvider>
  )
}
