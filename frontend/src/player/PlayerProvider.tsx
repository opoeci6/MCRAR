import { useCallback, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { trackStreamUrl } from '../api/endpoints'
import { useToast } from '../app/toastContext'
import { strings } from '../strings'
import { PlayerContext, PlayerTimeContext } from './playerContext'
import type { PlayableTrack, PlayerApi, PlayerTime } from './playerContext'

/**
 * Owns the one `<audio>` element of the app. The source is the backend's stream URL, which
 * redirects to the CDN (Jamendo) or serves the local file with Range support, so the browser
 * does the buffering and seeking and no audio byte passes through JavaScript.
 * Needs a ToastProvider above it (a playback error shows "Couldn't play this track").
 */
export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const toast = useToast()
  const [current, setCurrent] = useState<PlayableTrack | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [volume, setVolumeState] = useState(1)
  const [time, setTime] = useState<PlayerTime>({ currentTime: 0, duration: 0 })
  const currentRef = useRef<PlayableTrack | null>(null)
  const errorShown = useRef(false)

  const fail = useCallback(() => {
    setIsPlaying(false)
    setIsLoading(false)
    if (errorShown.current) return
    errorShown.current = true
    toast.error(strings.player.error)
  }, [toast])

  const start = useCallback(
    (audio: HTMLAudioElement) => {
      errorShown.current = false
      if (audio.error) audio.load() // a failed load needs a fresh start to retry
      setIsLoading(true)
      Promise.resolve(audio.play()).catch((error: unknown) => {
        // A newer load interrupting this one is not a failure.
        if (error instanceof DOMException && error.name === 'AbortError') return
        fail()
      })
    },
    [fail],
  )

  const play = useCallback(
    (track: PlayableTrack) => {
      const audio = audioRef.current
      if (!audio) return
      if (currentRef.current?.id === track.id) {
        if (audio.paused) start(audio)
        else audio.pause()
        return
      }
      currentRef.current = track
      setCurrent(track)
      setTime({ currentTime: 0, duration: track.duration_s ?? 0 })
      audio.src = trackStreamUrl(track.id)
      start(audio)
    },
    [start],
  )

  const toggle = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !currentRef.current) return
    if (audio.paused) start(audio)
    else audio.pause()
  }, [start])

  const pause = useCallback(() => audioRef.current?.pause(), [])

  const seek = useCallback((seconds: number) => {
    const audio = audioRef.current
    if (!audio || !Number.isFinite(seconds)) return
    audio.currentTime = Math.max(0, seconds)
    setTime((previous) => ({ ...previous, currentTime: audio.currentTime }))
  }, [])

  const setVolume = useCallback((next: number) => {
    const clamped = Math.min(1, Math.max(0, next))
    if (audioRef.current) audioRef.current.volume = clamped
    setVolumeState(clamped)
  }, [])

  const api = useMemo<PlayerApi>(
    () => ({ current, isPlaying, isLoading, volume, play, toggle, pause, seek, setVolume }),
    [current, isPlaying, isLoading, volume, play, toggle, pause, seek, setVolume],
  )

  const readTime = (audio: HTMLAudioElement) =>
    setTime((previous) => ({
      currentTime: audio.currentTime,
      duration: Number.isFinite(audio.duration) ? audio.duration : previous.duration,
    }))

  return (
    <PlayerContext.Provider value={api}>
      <PlayerTimeContext.Provider value={time}>{children}</PlayerTimeContext.Provider>
      <audio
        ref={audioRef}
        preload="none"
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
        onPlaying={() => {
          errorShown.current = false
          setIsLoading(false)
        }}
        onCanPlay={() => setIsLoading(false)}
        onWaiting={() => setIsLoading(true)}
        onTimeUpdate={(event) => readTime(event.currentTarget)}
        onDurationChange={(event) => readTime(event.currentTarget)}
        onError={fail}
      />
    </PlayerContext.Provider>
  )
}
