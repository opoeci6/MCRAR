import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
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

function statusText(source: string | null | undefined): string {
  if (!source) return t.secrets.statusNotSet
  if (source === 'env') return t.secrets.statusSetEnv
  if (source === 'file') return t.secrets.statusSetFile
  return t.secrets.statusSetOther(source)
}

export interface SecretFieldProps {
  /** The secret's name in the backend (`jamendo_client_id`). */
  name: string
  /** What the key is called: the heading, and the subject of the toasts and the confirmation. */
  title: string
  /** Says what the key is for. */
  body: ReactNode
  /** Where to get the key. */
  link?: { href: string; label: string }
  /** The label of the password input. */
  inputLabel: string
  /** What stops working when the key is removed. */
  removeWarning: string
}

/**
 * One API key: whether it is set and where it comes from, a password input to set it, and a
 * confirmed remove. The value is only ever typed into the password input and sent in the
 * request body: the page never shows the key. Give it a `key` of the secret name, so switching
 * to another secret starts with an empty input.
 */
export function SecretField({ name, title, body, link, inputLabel, removeWarning }: SecretFieldProps) {
  const toast = useToast()
  const secrets = useAsync((signal) => listSecrets({ signal }), [])
  const [value, setValue] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const source = secrets.data?.items.find((item) => item.name === name)?.source ?? null
  const isSet = source !== null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (value.trim() === '') return
    setPending(true)
    setError(null)
    try {
      await setSecret(name, value)
      setValue('')
      toast.info(t.secrets.saved(title))
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
      await deleteSecret(name)
      toast.info(t.secrets.removed(title))
      secrets.reload()
    } catch (caught) {
      setError(`${t.secrets.removeFailed}: ${errorMessage(caught)}`)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className={styles.inner}>
      <h3>{title}</h3>
      <p className={styles.explain}>
        {body}
        {link ? (
          <>
            {' '}
            <a href={link.href} target="_blank" rel="noreferrer noopener">
              {link.label}
              <span className="sr-only"> {strings.common.opensInNewTab}</span>
            </a>
          </>
        ) : null}
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
          label={inputLabel}
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
          title={t.secrets.removeConfirmTitle(title)}
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
          {removeWarning}
        </Notice>
      ) : null}
      {error ? <Notice kind="error">{error}</Notice> : null}
    </div>
  )
}
