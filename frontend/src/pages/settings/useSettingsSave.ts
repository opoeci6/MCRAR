import { useState } from 'react'
import { updateSettings } from '../../api'
import type { SettingsUpdate, SettingsView } from '../../api'

/** Sends a partial settings update; keeps the pending state and the backend's error text. */
export function useSettingsSave(onUpdated: (view: SettingsView) => void) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  /** Resolves to true when the update was saved. */
  const save = async (update: SettingsUpdate): Promise<boolean> => {
    setPending(true)
    setError(null)
    try {
      onUpdated(await updateSettings(update))
      return true
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error(String(caught)))
      return false
    } finally {
      setPending(false)
    }
  }
  return { pending, error, save }
}
