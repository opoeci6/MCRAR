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

/** The notice text for the source whose key a 503 detail says is missing (checked in table order). */
function missingKeySource(detail: string) {
  const names = Object.keys(t.start.missingKey).filter((name) => new RegExp(name, 'i').test(detail))
  return names.length > 0 ? t.start.missingKey[names[0]!]! : null
}

/** Why a job could not be started: another job runs (409), a source's key is missing (503), or the request. */
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
  const missing = error instanceof ApiError && error.status === 503 ? missingKeySource(error.detail) : null
  if (missing) {
    return (
      <Notice
        kind="error"
        title={missing.title}
        action={<a href={hrefFor('settings')}>{t.start.openSettings}</a>}
      >
        {missing.body}
      </Notice>
    )
  }
  return (
    <Notice kind="error" title={t.start.failed}>
      {errorMessage(error)}
    </Notice>
  )
}
