import { act, fireEvent, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/render'
import { usePlayer } from './playerContext'
import type { PlayableTrack } from './playerContext'

const TRACK: PlayableTrack = {
  id: 7,
  title: 'Rainy Window',
  artist: 'Jane Doe',
  risk: 'green',
  license_code: 'CC BY 4.0',
}

function Launcher({ track = TRACK, label = 'Play it' }: { track?: PlayableTrack; label?: string }) {
  const player = usePlayer()
  return <button onClick={() => player.play(track)}>{label}</button>
}

function audioElement(): HTMLAudioElement {
  return document.querySelector('audio') as HTMLAudioElement
}

describe('PlayerBar', () => {
  it('shows nothing until a track is played', () => {
    renderWithProviders(<Launcher />)
    expect(screen.queryByRole('region', { name: 'Audio player' })).not.toBeInTheDocument()
  })

  it('plays the stream URL of the track and shows its title, artist and licence', async () => {
    renderWithProviders(<Launcher />)
    await userEvent.click(screen.getByRole('button', { name: 'Play it' }))

    expect(audioElement().getAttribute('src')).toBe('/api/tracks/7/stream')
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    const bar = screen.getByRole('region', { name: 'Audio player' })
    expect(bar).toHaveTextContent('Rainy Window')
    expect(bar).toHaveTextContent('Jane Doe')
    expect(bar).toHaveTextContent('Safe')
    expect(bar).toHaveTextContent('CC BY 4.0')
    expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
  })

  it('pauses and resumes with the button', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Launcher />)
    await user.click(screen.getByRole('button', { name: 'Play it' }))
    await user.click(await screen.findByRole('button', { name: 'Pause' }))
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled()
    await user.click(await screen.findByRole('button', { name: 'Play' }))
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2)
  })

  it('loads a new source when another track is played', async () => {
    const user = userEvent.setup()
    function Two() {
      const player = usePlayer()
      return (
        <>
          <button onClick={() => player.play(TRACK)}>one</button>
          <button onClick={() => player.play({ ...TRACK, id: 9, title: 'Second' })}>two</button>
        </>
      )
    }
    renderWithProviders(<Two />)
    await user.click(screen.getByRole('button', { name: 'one' }))
    await user.click(screen.getByRole('button', { name: 'two' }))
    expect(audioElement().getAttribute('src')).toBe('/api/tracks/9/stream')
    expect(screen.getByRole('region', { name: 'Audio player' })).toHaveTextContent('Second')
  })

  it('uses a fallback for a track without a title or artist', async () => {
    renderWithProviders(<Launcher track={{ ...TRACK, title: null, artist: null }} />)
    await userEvent.click(screen.getByRole('button', { name: 'Play it' }))
    const bar = screen.getByRole('region', { name: 'Audio player' })
    expect(bar).toHaveTextContent('Untitled')
    expect(bar).toHaveTextContent('Unknown artist')
  })

  it('seeks with the seek bar and sets the volume', async () => {
    renderWithProviders(<Launcher />)
    await userEvent.click(screen.getByRole('button', { name: 'Play it' }))
    const audio = audioElement()
    Object.defineProperty(audio, 'duration', { value: 200, configurable: true })
    act(() => {
      audio.dispatchEvent(new Event('durationchange'))
    })
    const seek = screen.getByRole('slider', { name: 'Seek' })
    expect(seek).toHaveAttribute('max', '200')
    expect(screen.getByText('3:20')).toBeInTheDocument()
    fireEvent.change(seek, { target: { value: '65' } })
    expect(audio.currentTime).toBe(65)
    expect(seek).toHaveAttribute('aria-valuetext', '1:05 of 3:20')

    fireEvent.change(screen.getByRole('slider', { name: 'Volume' }), { target: { value: '0.25' } })
    expect(audio.volume).toBe(0.25)
  })

  it('shows a toast when the audio fails', async () => {
    renderWithProviders(<Launcher />)
    await userEvent.click(screen.getByRole('button', { name: 'Play it' }))
    act(() => {
      audioElement().dispatchEvent(new Event('error'))
    })
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't play this track")
  })

  it('shows a toast once when play() is rejected', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
      new DOMException('no', 'NotSupportedError'),
    )
    renderWithProviders(<Launcher />)
    await userEvent.click(screen.getByRole('button', { name: 'Play it' }))
    act(() => {
      audioElement().dispatchEvent(new Event('error'))
    })
    expect(await screen.findAllByText("Couldn't play this track")).toHaveLength(1)
  })

  it('does not show an error when a newer load interrupts play()', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
      new DOMException('interrupted', 'AbortError'),
    )
    renderWithProviders(<Launcher />)
    await userEvent.click(screen.getByRole('button', { name: 'Play it' }))
    await act(async () => {})
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
  describe('starting at a position', () => {
    function StartAt({ at }: { at: number }) {
      const player = usePlayer()
      return <button onClick={() => player.play(TRACK, { startAt: at })}>{`Play at ${at}`}</button>
    }

    it('waits for the metadata of a new track before it jumps', async () => {
      renderWithProviders(<StartAt at={42} />)
      await userEvent.click(screen.getByRole('button', { name: 'Play at 42' }))
      const audio = audioElement()
      expect(audio.getAttribute('src')).toBe('/api/tracks/7/stream')
      expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
      expect(audio.currentTime).toBe(0)

      act(() => {
        audio.dispatchEvent(new Event('loadedmetadata'))
      })
      expect(audio.currentTime).toBe(42)
      // Applied once: a later seek is not overridden by it.
      audio.currentTime = 10
      act(() => {
        audio.dispatchEvent(new Event('loadedmetadata'))
      })
      expect(audio.currentTime).toBe(10)
    })

    it('lets a seek made while the track still loads replace the start position', async () => {
      function SeekTo() {
        const player = usePlayer()
        return <button onClick={() => player.seek(5)}>Seek to 5</button>
      }
      renderWithProviders(
        <>
          <StartAt at={42} />
          <SeekTo />
        </>,
      )
      await userEvent.click(screen.getByRole('button', { name: 'Play at 42' }))
      const audio = audioElement()
      await userEvent.click(screen.getByRole('button', { name: 'Seek to 5' }))
      expect(audio.currentTime).toBe(0)
      act(() => {
        audio.dispatchEvent(new Event('loadedmetadata'))
      })
      expect(audio.currentTime).toBe(5)
    })

    it('seeks and plays at once when the track is already loaded, also when paused', async () => {
      const user = userEvent.setup()
      renderWithProviders(
        <>
          <Launcher />
          <StartAt at={30} />
        </>,
      )
      await user.click(screen.getByRole('button', { name: 'Play it' }))
      const audio = audioElement()
      act(() => {
        audio.dispatchEvent(new Event('loadedmetadata'))
      })
      await user.click(await screen.findByRole('button', { name: 'Pause' }))
      expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)

      await user.click(screen.getByRole('button', { name: 'Play at 30' }))
      expect(audio.currentTime).toBe(30)
      expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2)

      // Playing: a jump does not pause it (a plain play() would).
      await user.click(screen.getByRole('button', { name: 'Play at 30' }))
      expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1)
      expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2)
    })

    it('does not carry the position over to the next track', async () => {
      const user = userEvent.setup()
      function Two() {
        const player = usePlayer()
        return (
          <>
            <button onClick={() => player.play(TRACK, { startAt: 42 })}>first</button>
            <button onClick={() => player.play({ ...TRACK, id: 9 })}>second</button>
          </>
        )
      }
      renderWithProviders(<Two />)
      await user.click(screen.getByRole('button', { name: 'first' }))
      await user.click(screen.getByRole('button', { name: 'second' }))
      const audio = audioElement()
      act(() => {
        audio.dispatchEvent(new Event('loadedmetadata'))
      })
      expect(audio.currentTime).toBe(0)
    })
  })

  describe('repeat', () => {
    const repeatButton = () => screen.getByRole('button', { name: 'Repeat' })

    beforeEach(() => {
      window.localStorage.clear()
    })

    it('is off by default and loops the audio natively once switched on', async () => {
      const user = userEvent.setup()
      renderWithProviders(<Launcher />)
      await user.click(screen.getByRole('button', { name: 'Play it' }))
      expect(repeatButton()).toHaveAttribute('aria-pressed', 'false')
      expect(audioElement().loop).toBe(false)

      await user.click(repeatButton())
      expect(repeatButton()).toHaveAttribute('aria-pressed', 'true')
      expect(audioElement().loop).toBe(true)

      await user.click(repeatButton())
      expect(repeatButton()).toHaveAttribute('aria-pressed', 'false')
      expect(audioElement().loop).toBe(false)
    })

    it('remembers the choice in localStorage and restores it on mount', async () => {
      const user = userEvent.setup()
      const first = renderWithProviders(<Launcher />)
      await user.click(screen.getByRole('button', { name: 'Play it' }))
      await user.click(repeatButton())
      expect(window.localStorage.getItem('mcrar.player.loop')).toBe('1')
      first.unmount()

      renderWithProviders(<Launcher />)
      expect(audioElement().loop).toBe(true)
      await user.click(screen.getByRole('button', { name: 'Play it' }))
      expect(repeatButton()).toHaveAttribute('aria-pressed', 'true')

      await user.click(repeatButton())
      expect(window.localStorage.getItem('mcrar.player.loop')).toBe('0')
    })

    it('shows not playing when a track ends without repeat', async () => {
      renderWithProviders(<Launcher />)
      await userEvent.click(screen.getByRole('button', { name: 'Play it' }))
      expect(await screen.findByRole('button', { name: 'Pause' })).toBeInTheDocument()
      act(() => {
        audioElement().dispatchEvent(new Event('ended'))
      })
      expect(await screen.findByRole('button', { name: 'Play' })).toBeInTheDocument()
    })

    it('keeps working when localStorage throws', async () => {
      const user = userEvent.setup()
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new DOMException('denied', 'SecurityError')
      })
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new DOMException('full', 'QuotaExceededError')
      })
      renderWithProviders(<Launcher />)
      await user.click(screen.getByRole('button', { name: 'Play it' }))
      expect(repeatButton()).toHaveAttribute('aria-pressed', 'false')

      await user.click(repeatButton())
      expect(repeatButton()).toHaveAttribute('aria-pressed', 'true')
      expect(audioElement().loop).toBe(true)
    })
  })
})
