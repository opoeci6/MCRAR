import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePlayer } from '../../player/playerContext'
import type { PlayableTrack } from '../../player/playerContext'
import { renderWithProviders } from '../../test/render'
import { AUTOSAVE_MS, NoteEditor } from './NoteEditor'

const TRACK: PlayableTrack = { id: 10, title: 'Rainy Window', artist: null, risk: 'green', license_code: 'CC BY 4.0' }
const OTHER: PlayableTrack = { ...TRACK, id: 11, title: 'Forest Walk' }

/** A save the test settles by hand. */
function deferred() {
  let resolve!: () => void
  let reject!: (error: Error) => void
  const promise = new Promise<void>((ok, fail) => {
    resolve = ok
    reject = fail
  })
  return { promise, resolve, reject }
}

function Harness({
  note = null,
  onSave,
}: {
  note?: string | null
  onSave: (note: string) => Promise<void>
}) {
  const player = usePlayer()
  return (
    <>
      <NoteEditor track={TRACK} trackTitle="Rainy Window" note={note} onSave={onSave} />
      <button onClick={() => player.play(TRACK)}>start this</button>
      <button onClick={() => player.play(OTHER)}>start other</button>
    </>
  )
}

const audio = () => document.querySelector('audio') as HTMLAudioElement
const field = () => screen.getByRole('textbox', { name: 'Note for Rainy Window' }) as HTMLTextAreaElement
const ok = () => vi.fn<(note: string) => Promise<void>>(() => Promise.resolve())

/** Moves the clock of the audio element, so the player reports that position. */
function setPosition(seconds: number) {
  act(() => {
    audio().currentTime = seconds
    audio().dispatchEvent(new Event('timeupdate'))
  })
}

const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

function setup() {
  return userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('NoteEditor: collapsed and read views', () => {
  it('shows only an "Add note" button for an empty note, and opens the focused field', async () => {
    const user = setup()
    renderWithProviders(<Harness onSave={ok()} />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add note' }))
    expect(field()).toHaveFocus()
    expect(field()).toHaveValue('')
    expect(screen.queryByRole('button', { name: 'Add note' })).not.toBeInTheDocument()
  })

  it('shows a note as text, keeps its line breaks, and opens the field on a click', async () => {
    const user = setup()
    renderWithProviders(<Harness note={'First line\nSecond line'} onSave={ok()} />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    const read = screen.getByText(/First line/)
    expect(read.textContent).toBe('First line\nSecond line')

    await user.click(read)
    expect(field()).toHaveValue('First line\nSecond line')
    expect(field()).toHaveFocus()
  })

  it('opens the field from the keyboard with "Edit note"', async () => {
    const user = setup()
    renderWithProviders(<Harness note="Menu music" onSave={ok()} />)
    screen.getByRole('button', { name: 'Edit note' }).focus()
    await user.keyboard('{Enter}')
    expect(field()).toHaveValue('Menu music')
    expect(field()).toHaveFocus()
  })

  it('goes back to the text when the field loses focus', async () => {
    const user = setup()
    renderWithProviders(<Harness note="Menu music" onSave={ok()} />)
    await user.click(screen.getByText('Menu music'))
    await user.tab()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.getByText('Menu music')).toBeInTheDocument()
  })
})

describe('NoteEditor: autosave', () => {
  it('saves after the typing pauses and says Saving… then Saved', async () => {
    const user = setup()
    const save = deferred()
    const onSave = vi.fn(() => save.promise)
    renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'Menu')
    expect(screen.getByRole('status')).toHaveTextContent('')

    // (The clock moves a little while typing, so stay clear of the exact edge.)
    await advance(AUTOSAVE_MS - 200)
    expect(onSave).not.toHaveBeenCalled()
    await advance(200)
    expect(onSave).toHaveBeenCalledExactlyOnceWith('Menu')
    expect(screen.getByRole('status')).toHaveTextContent('Saving…')

    await act(async () => save.resolve())
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
    await advance(AUTOSAVE_MS * 3)
    expect(onSave).toHaveBeenCalledTimes(1)
  })

  it('waits for a pause: each keystroke restarts the timer', async () => {
    const user = setup()
    const onSave = ok()
    renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'a')
    await advance(AUTOSAVE_MS - 100)
    await user.type(field(), 'b')
    await advance(AUTOSAVE_MS - 100)
    expect(onSave).not.toHaveBeenCalled()
    await advance(100)
    expect(onSave).toHaveBeenCalledExactlyOnceWith('ab')
  })

  it('saves at once on blur, and on Ctrl+Enter, but only once for the same text', async () => {
    const user = setup()
    const onSave = ok()
    renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'x{Control>}{Enter}{/Control}')
    expect(onSave).toHaveBeenCalledExactlyOnceWith('x')
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    await user.tab()
    await advance(AUTOSAVE_MS * 2)
    expect(onSave).toHaveBeenCalledTimes(1)

    await user.click(screen.getByText('x'))
    await user.type(field(), 'y')
    await user.tab()
    expect(onSave).toHaveBeenCalledTimes(2)
    expect(onSave).toHaveBeenLastCalledWith('xy')
  })

  it('does not save a note that is the same as the stored one', async () => {
    const user = setup()
    const onSave = ok()
    renderWithProviders(<Harness note="Menu" onSave={onSave} />)
    await user.click(screen.getByText('Menu'))
    await user.type(field(), 'x{Backspace}')
    await advance(AUTOSAVE_MS * 2)
    await user.tab()
    expect(onSave).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('')
  })

  it('sends an emptied note as an empty string', async () => {
    const user = setup()
    const onSave = ok()
    renderWithProviders(<Harness note="Menu" onSave={onSave} />)
    await user.click(screen.getByText('Menu'))
    await user.clear(field())
    await user.tab()
    expect(onSave).toHaveBeenCalledExactlyOnceWith('')
    expect(screen.getByRole('button', { name: 'Add note' })).toBeInTheDocument()
  })

  it('keeps the text and says "Couldn\'t save" when saving fails, and tries again on the next edit', async () => {
    const user = setup()
    const onSave = vi
      .fn<(note: string) => Promise<void>>()
      .mockRejectedValueOnce(new Error('database is locked'))
      .mockResolvedValue(undefined)
    renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'Menu{Control>}{Enter}{/Control}')

    expect(await screen.findByText("Couldn't save")).toBeInTheDocument()
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
    expect(field()).toHaveValue('Menu')

    await user.type(field(), '!')
    await advance(AUTOSAVE_MS)
    expect(onSave).toHaveBeenCalledTimes(2)
    expect(onSave).toHaveBeenLastCalledWith('Menu!')
    expect(await screen.findByText('Saved')).toBeInTheDocument()
  })

  it('keeps one save in flight and sends the newest text after it, never an older one last', async () => {
    const user = setup()
    const first = deferred()
    const second = deferred()
    const onSave = vi
      .fn<(note: string) => Promise<void>>()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockResolvedValue(undefined)
    renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'a{Control>}{Enter}{/Control}')
    expect(onSave).toHaveBeenCalledTimes(1)

    // Typed while the first save is out: neither the pause nor Ctrl+Enter starts a second save.
    await user.type(field(), 'bc{Control>}{Enter}{/Control}')
    await advance(AUTOSAVE_MS * 2)
    expect(onSave).toHaveBeenCalledTimes(1)

    await act(async () => first.resolve())
    expect(onSave).toHaveBeenCalledTimes(2)
    expect(onSave).toHaveBeenLastCalledWith('abc')
    // The first answer does not make it "Saved": the newer text is still on its way.
    expect(screen.getByRole('status')).toHaveTextContent('Saving…')

    await act(async () => second.resolve())
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
    expect(onSave.mock.calls.map(([value]) => value)).toEqual(['a', 'abc'])
  })

  it('does not loop after a failed save: the pending pause tries once more, and the text stays', async () => {
    const user = setup()
    const first = deferred()
    const onSave = vi
      .fn<(note: string) => Promise<void>>()
      .mockReturnValueOnce(first.promise)
      .mockRejectedValue(new Error('down'))
    renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'a{Control>}{Enter}{/Control}')
    await user.type(field(), 'b')

    await act(async () => first.resolve())
    expect(await screen.findByText("Couldn't save")).toBeInTheDocument()
    expect(onSave).toHaveBeenCalledTimes(2)
    await advance(AUTOSAVE_MS * 3)
    expect(onSave).toHaveBeenCalledTimes(3)
    await advance(AUTOSAVE_MS * 3)
    expect(onSave).toHaveBeenCalledTimes(3)
    expect(screen.getByText("Couldn't save")).toBeInTheDocument()
    expect(field()).toHaveValue('ab')
  })

  it('saves what is waiting for the pause when the editor goes away', async () => {
    const user = setup()
    const onSave = ok()
    const { unmount } = renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'last words')
    expect(onSave).not.toHaveBeenCalled()
    unmount()
    expect(onSave).toHaveBeenCalledExactlyOnceWith('last words')
  })

  it('does not save on unmount when everything is saved', async () => {
    const user = setup()
    const onSave = ok()
    const { unmount } = renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'x{Control>}{Enter}{/Control}')
    unmount()
    expect(onSave).toHaveBeenCalledTimes(1)
  })
})

describe('NoteEditor: timestamps', () => {
  const insert = () => screen.getByRole('button', { name: 'Insert current time' })

  it('has "Insert current time" disabled until this track is the one playing', async () => {
    const user = setup()
    renderWithProviders(<Harness onSave={ok()} />)
    expect(insert()).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'start other' }))
    expect(insert()).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'start this' }))
    expect(insert()).toBeEnabled()
  })

  it('inserts the position at the caret, keeps the focus there, and autosaves', async () => {
    const user = setup()
    const onSave = ok()
    renderWithProviders(<Harness onSave={onSave} />)
    await user.click(screen.getByRole('button', { name: 'start this' }))
    setPosition(83.7)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.type(field(), 'ab{ArrowLeft}')

    await user.click(insert())
    expect(field()).toHaveValue('a1:23b')
    expect(field()).toHaveFocus()
    expect(field().selectionStart).toBe(5)
    expect(onSave).not.toHaveBeenCalled()
    await advance(AUTOSAVE_MS)
    expect(onSave).toHaveBeenCalledExactlyOnceWith('a1:23b')
  })

  it('writes h:mm:ss from one hour', async () => {
    const user = setup()
    renderWithProviders(<Harness onSave={ok()} />)
    await user.click(screen.getByRole('button', { name: 'start this' }))
    setPosition(3723)
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await user.click(insert())
    expect(field()).toHaveValue('1:02:03')
  })

  it('opens the field when the note is collapsed, and adds to the end of a note being read', async () => {
    const user = setup()
    renderWithProviders(<Harness note="Intro" onSave={ok()} />)
    await user.click(screen.getByRole('button', { name: 'start this' }))
    setPosition(18)

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    await user.click(insert())
    expect(field()).toHaveValue('Intro 0:18')
    expect(field()).toHaveFocus()
    expect(field().selectionStart).toBe('Intro 0:18'.length)
  })

  it('makes timestamps in the text buttons that play this track from there', async () => {
    const user = setup()
    renderWithProviders(<Harness note={'Intro 0:18, drop at 1:02:03.\nLoop 2:30'} onSave={ok()} />)
    expect(screen.getByRole('button', { name: 'Play from 0:18' })).toHaveTextContent('0:18')
    expect(screen.getByRole('button', { name: 'Play from 1:02:03' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Play from 2:30' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Play from/ })).toHaveLength(3)

    await user.click(screen.getByRole('button', { name: 'Play from 0:18' }))
    expect(audio().getAttribute('src')).toBe('/api/tracks/10/stream')
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    // The seek waits for the audio to know its length.
    act(() => {
      audio().dispatchEvent(new Event('loadedmetadata'))
    })
    expect(audio().currentTime).toBe(18)
    // A timestamp is not a request to edit.
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('seeks at once when this track is already playing', async () => {
    const user = setup()
    renderWithProviders(<Harness note="Drop 1:05" onSave={ok()} />)
    await user.click(screen.getByRole('button', { name: 'start this' }))
    act(() => {
      audio().dispatchEvent(new Event('loadedmetadata'))
    })
    await user.click(screen.getByRole('button', { name: 'Play from 1:05' }))
    expect(audio().currentTime).toBe(65)
    expect(HTMLMediaElement.prototype.pause).not.toHaveBeenCalled()
  })

  it('does not link anything in the field itself', async () => {
    const user = setup()
    renderWithProviders(<Harness note="Intro 0:18" onSave={ok()} />)
    await user.click(screen.getByText(/Intro/))
    expect(screen.queryByRole('button', { name: /^Play from/ })).not.toBeInTheDocument()
  })
})
