import type { Job } from '../../api'

/** What every "add music" form needs from the page. */
export interface StartProps {
  /** A job is already running here: starting another would be refused. */
  busy: boolean
  onStarted: (job: Job) => void
  /** Finds the running job and shows it. */
  onShowRunning: () => void
}
