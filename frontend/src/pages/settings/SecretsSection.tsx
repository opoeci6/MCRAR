import { useState } from 'react'
import type { FormEvent } from 'react'
import { deleteSecret, listSecrets, setSecret } from '../../api/endpoints'
import { errorMessage, useAsync } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { TextInput } from '../../ui/TextInput'
import { settingsStrings as t } from './strings'
import styles from './Section.module.css'

const JAMENDO = 'jamendo_client_id'

function statusText(source: string | null | undefined): string {
  if (!source) return t.secrets.statusNotSet
  if (source === 'env') return t.secrets.statusSetEnv
  if (source === 'file') return t.secrets.statusSetFile
  return t.secrets.statusSetOther(source)
}

/**
 * The Jamendo client id. The value is only ever typed into the password input and sent in the
 * request body: the page shows whether a key is set and where it comes from, never the key.
 */
export function SecretsSection() {
  const toast = useToast()
  const secrets = useAsync((signal) => listSecrets({ signal }), [])
  const [value, setValue] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const source = secrets.data?.items.find((item) => item.name === JAMENDO)?.source ?? null
  const isSet = source !== null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (value.trim() === '') return
    setPending(true)
    setError(null)
    try {
      await setSecret(JAMENDO, value)
      setValue('')
      toast.info(t.secrets.saved)
      secrets.reload()
    } catch (caught) {
      setError(`${t.secrets.saveFailed}: ${errorMessage(caught)}`)
    } finally {
      setPending(false)
    }
  }

  const remove = async () => {
    setConfirmRemove(false)
    setPending(true)
    setError(null)
    try {
      await deleteSecret(JAMENDO)
      toast.info(t.secrets.removed)
      secrets.reload()
    } catch (caught) {
      setError(`${t.secrets.removeFailed}: ${errorMessage(caught)}`)
    } finally {
      setPending(false)
    }
  }

  return (
    <section className={styles.section} aria-labelledby="settings-secrets-heading">
      <h2 id="settings-secrets-heading">{t.secrets.heading}</h2>
      <h3>{t.secrets.jamendoTitle}</h3>
      <p className={styles.explain}>
        {t.secrets.jamendoBody}{' '}
        <a href="https://devportal.jamendo.com" target="_blank" rel="noreferrer noopener">
          {t.secrets.jamendoLink}
          <span className="sr-only"> {strings.common.opensInNewTab}</span>
        </a>
      </p>
      {secrets.error && !secrets.data ? (
        <Notice kind="error">
          {t.secrets.loadFailed}: {errorMessage(secrets.error)}
        </Notice>
      ) : !secrets.data ? (
        <Spinner />
      ) : (
        <p>
          <span className={styles.note}>{t.secrets.status}: </span>
          <span className={styles.status}>{statusText(source)}</span>
        </p>
      )}
      <form onSubmit={submit} className={styles.inner}>
        <TextInput
          label={t.secrets.input}
          hint={t.secrets.inputHint}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <div className={styles.actions}>
          <Button type="submit" variant="primary" disabled={pending || value.trim() === ''}>
            {t.secrets.save}
          </Button>
          <Button
            variant="danger"
            disabled={pending || !isSet || source === 'env'}
            onClick={() => setConfirmRemove(true)}
          >
            {t.secrets.remove}
          </Button>
        </div>
      </form>
      {source === 'env' ? <p className={styles.note}>{t.secrets.envCannotRemove}</p> : null}
      {confirmRemove ? (
        <Notice
          kind="warning"
          title={t.secrets.removeConfirmTitle}
          action={
            <div className={styles.actions}>
              <Button size="sm" variant="danger" onClick={() => void remove()}>
                {t.secrets.removeConfirmAction}
              </Button>
              <Button size="sm" onClick={() => setConfirmRemove(false)}>
                {t.secrets.keep}
              </Button>
            </div>
          }
        >
          {t.secrets.removeConfirmBody}
        </Notice>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </section>
  )
}
