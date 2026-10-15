import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { strings } from '../strings'
import { IconButton } from '../ui/Button'
import { CloseIcon } from '../ui/icons'
import { ToastContext } from './toastContext'
import type { ToastApi, ToastKind } from './toastContext'
import styles from './ToastProvider.module.css'

interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

const INFO_MS = 4000
const ERROR_MS = 8000
const MAX_VISIBLE = 4

/** Renders the toasts in a live region (always present, so screen readers announce new ones). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer !== undefined) clearTimeout(timer)
    timers.current.delete(id)
    setToasts((current) => current.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId.current++
      setToasts((current) => [...current, { id, kind, message }].slice(-MAX_VISIBLE))
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), kind === 'error' ? ERROR_MS : INFO_MS),
      )
    },
    [dismiss],
  )

  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach(clearTimeout)
      pending.clear()
    }
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      info: (message) => push('info', message),
      error: (message) => push('error', message),
      dismiss,
    }),
    [push, dismiss],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className={styles.region} role="region" aria-label={strings.toast.region}>
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`${styles.toast} ${toast.kind === 'error' ? styles.error : styles.info}`}
            role={toast.kind === 'error' ? 'alert' : 'status'}
          >
            <span className={styles.message}>{toast.message}</span>
            <IconButton
              label={strings.toast.dismiss}
              size="sm"
              onClick={() => dismiss(toast.id)}
              className={styles.close}
            >
              <CloseIcon width={12} height={12} />
            </IconButton>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
