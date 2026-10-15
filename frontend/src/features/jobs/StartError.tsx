import { ApiError } from '../../api'
import { errorMessage } from '../../api/useAsync'
import { hrefFor } from '../../app/route'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { jobStrings as t } from './strings'

export interface StartErrorProps {
  error: Error | null
  /** Finds the running job and shows it. Without it, a 409 links to the Library tab instead. */
  onShowRunning?: () => void
}

/** Why a job could not be started: another job runs (409), the Jamendo key is missing (503), or the request. */
export function StartError({ error, onShowRunning }: StartErrorProps) {
  if (!error) return null
  if (error instanceof ApiError && error.status === 409) {
    return (
      <Notice
        kind="warning"
        title={t.start.busyTitle}
        action={
          onShowRunning ? (
            <Button size="sm" onClick={onShowRunning}>
              {t.start.showRunning}
            </Button>
          ) : (
            <a href={hrefFor('library')}>{t.start.openLibrary}</a>
          )
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
        title={t.start.missingKeyTitle}
        action={<a href={hrefFor('settings')}>{t.start.openSettings}</a>}
      >
        {t.start.missingKeyBody}
      </Notice>
    )
  }
  return (
    <Notice kind="error" title={t.start.failed}>
      {errorMessage(error)}
    </Notice>
  )
}
