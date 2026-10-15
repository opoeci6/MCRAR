import { ApiError } from '../../api'
import type { Job } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { hrefFor } from '../../app/route'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { libraryStrings as t } from './strings'

/** What every "add music" form needs from the page. */
export interface StartProps {
  /** A job is already running here: starting another would be refused. */
  busy: boolean
  onStarted: (job: Job) => void
  /** Finds the running job and shows it. */
  onShowRunning: () => void
}

/** Why a job could not be started: another job runs (409), the Jamendo key is missing (503), or the request. */
export function StartError({ error, onShowRunning }: { error: Error | null; onShowRunning: () => void }) {
  if (!error) return null
  if (error instanceof ApiError && error.status === 409) {
    return (
      <Notice
        kind="warning"
        title={t.start.busyTitle}
        action={
          <Button size="sm" onClick={onShowRunning}>
            {t.start.showRunning}
          </Button>
        }
      >
        {t.start.busyBody}
      </Notice>
    )
  }
  if (error instanceof ApiError && error.status === 503 && /jamendo/i.test(error.detail)) {
    return (
      <Notice
        kind="error"
        title={t.jamendo.missingKeyTitle}
        action={
          <a href={hrefFor('settings')}>{t.jamendo.openSettings}</a>
        }
      >
        {t.jamendo.missingKeyBody}
      </Notice>
    )
  }
  return (
    <Notice kind="error" title={t.start.failed}>
      {errorMessage(error)}
    </Notice>
  )
}
