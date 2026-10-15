import { PlayerProvider } from '../player/PlayerProvider'
import { BackendStatusProvider } from './BackendStatusProvider'
import { Shell } from './Shell'
import { ToastProvider } from './ToastProvider'

/** The providers (toasts, backend status, player) around the shell. */
export default function App() {
  return (
    <ToastProvider>
      <BackendStatusProvider>
        <PlayerProvider>
          <Shell />
        </PlayerProvider>
      </BackendStatusProvider>
    </ToastProvider>
  )
}
