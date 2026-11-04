import { createContext, useContext } from 'react'

export interface TourControls {
  /** The tour is on screen. */
  active: boolean
  /** Opens the welcome card (from Settings, or on the first start). */
  start: () => void
}

/** Without a provider (a page rendered alone) the tour does nothing. */
export const TourContext = createContext<TourControls>({ active: false, start: () => {} })

export function useTour(): TourControls {
  return useContext(TourContext)
}
