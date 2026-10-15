import { createContext, useContext } from 'react'

export type ToastKind = 'info' | 'error'

export interface ToastApi {
  /** Shows a message that goes away by itself after a few seconds. */
  info: (message: string) => void
  /** Shows an error (stays a little longer, announced at once to screen readers). */
  error: (message: string) => void
  dismiss: (id: number) => void
}

export const ToastContext = createContext<ToastApi | null>(null)

/**
 *   const toast = useToast()
 *   toast.error(errorMessage(caught))
 *   toast.info('Added to Level 1')
 */
export function useToast(): ToastApi {
  const api = useContext(ToastContext)
  if (!api) throw new Error('useToast needs a <ToastProvider> above it')
  return api
}
