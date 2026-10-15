import { createContext, useContext } from 'react'
import type { Health } from '../api/types'

export type BackendState = 'checking' | 'online' | 'offline'

export interface BackendStatus {
  state: BackendState
  /** The last good `/api/health` answer. */
  health: Health | null
}

export const BackendStatusContext = createContext<BackendStatus>({ state: 'checking', health: null })

/** Whether the backend answers, from the shell's poll of `/api/health`. */
export function useBackendStatus(): BackendStatus {
  return useContext(BackendStatusContext)
}
