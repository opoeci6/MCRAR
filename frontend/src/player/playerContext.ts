import { createContext, useContext } from 'react'
import type { Risk } from '../api/types'

/** What the player needs to show a track. A search item or a track summary fits after mapping. */
export interface PlayableTrack {
  id: number
  title: string | null
  artist: string | null
  risk: Risk
  license_code: string | null
  /** Shown in the licence badge details when set. */
  attribution?: string | null
  license_url?: string | null
  commercial_license_url?: string | null
  /** Used for the seek bar until the audio reports its own length. */
  duration_s?: number | null
}

export interface PlayOptions {
  /** Start at this many seconds instead of the beginning (or the current position). */
  startAt?: number
}

export interface PlayerApi {
  current: PlayableTrack | null
  isPlaying: boolean
  /** True while the audio is buffering. */
  isLoading: boolean
  /** 0 to 1. */
  volume: number
  /** Repeat the current track (the audio loops natively). Remembered across reloads. */
  loop: boolean
  /**
   * Plays the track from the start; the track that is already loaded is toggled instead. With
   * `startAt` the track always plays, from that position (also while it is still loading).
   */
  play: (track: PlayableTrack, options?: PlayOptions) => void
  /** Pauses or resumes the current track (does nothing when there is none). */
  toggle: () => void
  pause: () => void
  /** Jumps to a position in seconds. */
  seek: (seconds: number) => void
  setVolume: (volume: number) => void
  setLoop: (next: boolean) => void
}

export interface PlayerTime {
  currentTime: number
  /** 0 until it is known. */
  duration: number
}

export const PlayerContext = createContext<PlayerApi | null>(null)
export const PlayerTimeContext = createContext<PlayerTime>({ currentTime: 0, duration: 0 })

/**
 *   const player = usePlayer()
 *   player.play({ id, title, artist, risk, license_code })
 *   const active = player.current?.id === id && player.isPlaying
 */
export function usePlayer(): PlayerApi {
  const api = useContext(PlayerContext)
  if (!api) throw new Error('usePlayer needs a <PlayerProvider> above it')
  return api
}

/** The playback position. Separate from `usePlayer` because it changes several times a second. */
export function usePlayerTime(): PlayerTime {
  return useContext(PlayerTimeContext)
}
