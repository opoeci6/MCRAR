import type { Intensity, Risk, SearchFilters, Source, Vocal } from '../../api/types'
import { searchStrings } from './strings'

export type DurationPreset = 'any' | 'jingle' | 'short' | 'bgm' | 'custom'

/** The filter form as the user edits it (numbers stay text until a search is sent). */
export interface FilterState {
  /** "Safe for commercial game": sends `max_risk: "green"`. */
  safeOnly: boolean
  /** Used when `safeOnly` is off; empty means any. */
  maxRisk: '' | Exclude<Risk, 'unknown'>
  /** Label ids from `GET /api/vocab`. */
  genres: string[]
  moods: string[]
  /** Game scene ids from `GET /api/vocab`. */
  scenes: string[]
  /** Sets the energy target; empty means any. */
  intensity: '' | Intensity
  bpmMin: string
  bpmMax: string
  vocal: '' | Vocal
  duration: DurationPreset
  durationMin: string
  durationMax: string
  source: '' | Source
}

export const DEFAULT_FILTERS: FilterState = {
  safeOnly: false,
  maxRisk: '',
  genres: [],
  moods: [],
  scenes: [],
  intensity: '',
  bpmMin: '',
  bpmMax: '',
  vocal: '',
  duration: 'any',
  durationMin: '',
  durationMax: '',
  source: '',
}

/** Preset bounds in seconds. */
export const JINGLE_MAX_S = 15
export const SHORT_MAX_S = 60
export const BGM_MIN_S = 60

/** A non-negative number from a text field, or `undefined` when empty or not a number. */
function parseNumber(text: string): number | undefined {
  if (text.trim() === '') return undefined
  const value = Number(text)
  return Number.isFinite(value) && value >= 0 ? value : undefined
}

function durationBounds(f: FilterState): [number | undefined, number | undefined] {
  switch (f.duration) {
    case 'jingle':
      return [undefined, JINGLE_MAX_S]
    case 'short':
      return [undefined, SHORT_MAX_S]
    case 'bgm':
      return [BGM_MIN_S, undefined]
    case 'custom':
      return [parseNumber(f.durationMin), parseNumber(f.durationMax)]
    default:
      return [undefined, undefined]
  }
}

/** The filters of a search request. Unset filters are left out, so no filters gives `{}`. */
export function toApiFilters(f: FilterState): SearchFilters {
  const out: SearchFilters = {}
  const maxRisk = f.safeOnly ? 'green' : f.maxRisk
  if (maxRisk) out.max_risk = maxRisk
  if (f.genres.length > 0) out.genres = f.genres
  if (f.moods.length > 0) out.moods = f.moods
  if (f.scenes.length > 0) out.scenes = f.scenes
  if (f.intensity) out.intensity = f.intensity
  const bpmMin = parseNumber(f.bpmMin)
  const bpmMax = parseNumber(f.bpmMax)
  if (bpmMin !== undefined) out.bpm_min = bpmMin
  if (bpmMax !== undefined) out.bpm_max = bpmMax
  if (f.vocal) out.vocal = f.vocal
  const [durationMin, durationMax] = durationBounds(f)
  if (durationMin !== undefined) out.duration_min_s = durationMin
  if (durationMax !== undefined) out.duration_max_s = durationMax
  if (f.source) out.sources = [f.source]
  return out
}

/** A message when a range is back to front, else `null`. */
export function filterProblem(f: FilterState): string | null {
  const bpmMin = parseNumber(f.bpmMin)
  const bpmMax = parseNumber(f.bpmMax)
  if (bpmMin !== undefined && bpmMax !== undefined && bpmMin > bpmMax) {
    return searchStrings.filters.bpmOrder
  }
  if (f.duration === 'custom') {
    const [min, max] = durationBounds(f)
    if (min !== undefined && max !== undefined && min > max) return searchStrings.filters.durationOrder
  }
  return null
}

/** How many filters are set (for the "Filters (3)" button): a range or a group counts once. */
export function activeFilterCount(f: FilterState): number {
  const api = toApiFilters(f)
  const has = (...keys: (keyof SearchFilters)[]) => keys.some((key) => api[key] !== undefined)
  return [
    has('max_risk'),
    has('genres'),
    has('moods'),
    has('scenes'),
    has('intensity'),
    has('bpm_min', 'bpm_max'),
    has('vocal'),
    has('duration_min_s', 'duration_max_s'),
    has('sources'),
  ].filter(Boolean).length
}
