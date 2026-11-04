import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Health } from '../../api/types'
import { BackendStatusContext } from '../../app/backendStatus'
import { clearPersistentState } from '../../app/usePersistentState'
import { FakeEventSource } from '../../test/eventSource'
import { HEALTH, jsonResponse, stubApi } from '../../test/fetch'
import type { Routes } from '../../test/fetch'
import { renderWithProviders } from '../../test/render'
import LibraryPage from './index'

const STATS = {
  tracks: 120,
  tracks_by_source: { local: 20 },
  tracks_by_risk: { green: 80 },
  features: { tracks_with_features: 90, coverage: 0.75 },
  embeddings_by_model: {},
  ingest_failures_by_stage: {},
}

const job = (overrides: Record<string, unknown> = {}) => ({
  id: 'j1',
  kind: 'ingest-files',
  params: {},
  status: 'running',
  created_at: '2026-10-15T10:00:00Z',
  finished_at: null,
  cancel_requested: false,
  error: null,
  progress: null,
  ...overrides,
})

const tracksPage = { items: [], total: 0, limit: 50, offset: 0 }

function baseRoutes(extra: Routes = {}): Routes {
  return {
    'GET /api/stats': STATS,
    'GET /api/tracks': tracksPage,
    'GET /api/jobs': { jobs: [] },
    ...extra,
  }
}

/** The library page with the backend reporting whether it is local (`null`: health unknown). */
function renderPage(localFiles: boolean | null = true) {
  const health = localFiles === null ? null : ({ ...HEALTH, local_files: localFiles } as unknown as Health)
  return renderWithProviders(
    <BackendStatusContext.Provider value={{ state: health ? 'online' : 'checking', health }}>
      <LibraryPage />
    </BackendStatusContext.Provider>,
  )
}

const callsTo = (mock: ReturnType<typeof stubApi>, method: string, path: string) =>
  mock.mock.calls.filter(([input, init]) => String(input).split('?')[0] === path && (init?.method ?? 'GET') === method)

const nameOf = (call: [RequestInfo | URL, RequestInit?]) => new URL(String(call[0]), 'http://x').searchParams.get('name')

const song = (name: string, size = 4) => new File(['x'.repeat(size)], name, { type: 'audio/wav' })

/** An upload answer that names the stored file after the sent name. */
const stored = (url: URL) =>
  jsonResponse({ file: `h-${url.searchParams.get('name')}`, name: url.searchParams.get('name'), size: 4, already: false }, 201)

beforeEach(() => {
  clearPersistentState()
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function openYourFiles(user = userEvent.setup({ applyAccept: false })) {
  await user.click(await screen.findByRole('tab', { name: 'Your files' }))
  return {
    user,
    copy: within(screen.getByRole('region', { name: 'Copy files into MCRAR' })),
    folder: within(screen.getByRole('region', { name: 'Use a folder where it is' })),
  }
}

describe('Your files: the two ways', () => {
  it('explains both ways', async () => {
    stubApi(baseRoutes())
    renderPage()
    const { copy, folder } = await openYourFiles()
    expect(screen.getByText(/Add music that is on your computer in one of two ways/)).toBeInTheDocument()
    expect(copy.getByText(/The copies use disk space|so the copies use disk space/)).toBeInTheDocument()
    expect(copy.getByText(/move or delete the originals/)).toBeInTheDocument()
    expect(copy.getByRole('button', { name: 'Choose files…' })).toBeInTheDocument()
    expect(folder.getByText(/nothing is copied/)).toBeInTheDocument()
    expect(folder.getByText(/playback stops working until you add the new folder again/)).toBeInTheDocument()
  })
})

describe('Your files: job history', () => {
  it('names an ingest-files job and counts its files', async () => {
    stubApi(
      baseRoutes({
        'GET /api/jobs': {
          jobs: [
            job({
              status: 'done',
              finished_at: '2026-10-15T10:05:00Z',
              params: { files: [{ file: 'a.wav', title: 'a' }, { file: 'b.wav', title: 'b' }], license: 'CC0', embed: true },
            }),
          ],
        },
      }),
    )
    renderPage()
    const history = await screen.findByRole('table', { name: 'Recent jobs' })
    expect(within(history).getByText('Add files')).toBeInTheDocument()
    expect(within(history).getByText('2 files / CC0')).toBeInTheDocument()
  })
})

describe('Your files: copy files into MCRAR', () => {
  const INGEST = 'POST /api/ingest/files'

  async function setup(extra: Routes = {}) {
    const api = stubApi(
      baseRoutes({
        'POST /api/library/files': (url: URL) => stored(url),
        [INGEST]: jsonResponse({ job: job() }, 202),
        ...extra,
      }),
    )
    renderPage()
    const opened = await openYourFiles()
    const input = () => screen.getByLabelText('Audio files to copy')
    return { api, input, ...opened }
  }

  it('starts with nothing chosen and cannot be submitted', async () => {
    const { copy } = await setup()
    expect(copy.getByRole('button', { name: 'Add files' })).toBeDisabled()
  })

  it('skips what is not audio and says how many', async () => {
    const { user, input, copy } = await setup()
    await user.upload(input(), [song('a.wav'), new File(['t'], 'notes.txt'), new File(['t'], 'cover.jpg')])
    expect(copy.getByText("Skipped 2 files that aren't audio.")).toBeInTheDocument()
    expect(copy.getByText('1 file selected (1 KB)')).toBeInTheDocument()
    expect(copy.getByRole('button', { name: 'Add 1 file' })).toBeEnabled()
  })

  it('copies the files one by one in order, then adds them in one job that the page shows', async () => {
    const { api, user, input, copy } = await setup()
    await user.upload(input(), [song('a.wav'), song('b.MP3'), song('c.flac')])
    expect(copy.getByText('3 files selected (1 KB)')).toBeInTheDocument()
    await user.type(copy.getByLabelText('Licence (optional)'), 'CC0')
    await user.click(copy.getByLabelText(/Also embed/)) // on by default: off
    await user.click(copy.getByRole('button', { name: 'Add 3 files' }))

    const panel = await screen.findByRole('region', { name: 'Job progress' })
    expect(within(panel).getByRole('heading', { name: 'Add files' })).toBeInTheDocument()

    const uploads = callsTo(api, 'POST', '/api/library/files')
    expect(uploads.map(nameOf)).toEqual(['a.wav', 'b.MP3', 'c.flac'])
    // The raw file is the body.
    expect((uploads[0]![1]!.body as File).name).toBe('a.wav')
    expect(uploads[0]![1]!.headers).toMatchObject({ 'Content-Type': 'application/octet-stream' })

    const ingests = callsTo(api, 'POST', '/api/ingest/files')
    expect(ingests).toHaveLength(1)
    expect(JSON.parse(String(ingests[0]![1]!.body))).toEqual({
      files: [
        { file: 'h-a.wav', title: 'a' },
        { file: 'h-b.MP3', title: 'b' },
        { file: 'h-c.flac', title: 'c' },
      ],
      license: 'CC0',
      embed: false,
    })
    // The selection is cleared once the job runs.
    await waitFor(() => expect(copy.getByRole('button', { name: 'Add files' })).toBeDisabled())
  })

  it('shows which file is being copied, with a progress bar', async () => {
    let release: (() => void) | undefined
    const { user, input, copy } = await setup({
      'POST /api/library/files': (url: URL) =>
        url.searchParams.get('name') === 'b.wav'
          ? new Promise((resolve) => {
              release = () => resolve(stored(url))
            })
          : stored(url),
    })
    await user.upload(input(), [song('a.wav'), song('b.wav')])
    await user.click(copy.getByRole('button', { name: 'Add 2 files' }))
    expect(await copy.findByText('Copying 2 of 2: b.wav')).toBeInTheDocument()
    const bar = copy.getByRole('progressbar', { name: 'Copying files' })
    expect(bar).toHaveAttribute('max', '2')
    expect(bar).toHaveAttribute('value', '1')
    expect(copy.getByRole('button', { name: 'Add 2 files' })).toBeDisabled()
    release?.()
    await screen.findByRole('region', { name: 'Job progress' })
  })

  it('does not add the same file twice when it is chosen again', async () => {
    const { user, input, copy } = await setup()
    const a = song('a.wav')
    await user.upload(input(), [a])
    await user.upload(input(), [a, song('b.wav')])
    expect(copy.getByText('2 files selected (1 KB)')).toBeInTheDocument()
  })

  it('stops at Cancel: no further file is sent and no job is started', async () => {
    const { api, user, input, copy } = await setup({
      'POST /api/library/files': (url: URL, init?: RequestInit) =>
        url.searchParams.get('name') === 'b.wav'
          ? new Promise((_resolve, reject) => {
              init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
            })
          : stored(url),
    })
    await user.upload(input(), [song('a.wav'), song('b.wav'), song('c.wav')])
    await user.click(copy.getByRole('button', { name: 'Add 3 files' }))
    await copy.findByText('Copying 2 of 3: b.wav')
    await user.click(copy.getByRole('button', { name: 'Cancel' }))

    expect(await copy.findByText(/^Cancelled\./)).toBeInTheDocument()
    expect(callsTo(api, 'POST', '/api/library/files').map(nameOf)).toEqual(['a.wav', 'b.wav'])
    expect(callsTo(api, 'POST', '/api/ingest/files')).toHaveLength(0)
    expect(screen.queryByRole('region', { name: 'Job progress' })).not.toBeInTheDocument()
    // The list is kept, so the user can try again.
    expect(copy.getByRole('button', { name: 'Add 3 files' })).toBeEnabled()
  })

  it('stops on an upload error, names the file, and starts no job', async () => {
    const { api, user, input, copy } = await setup({
      'POST /api/library/files': (url: URL) =>
        url.searchParams.get('name') === 'b.wav'
          ? jsonResponse({ detail: 'the file is empty' }, 422)
          : stored(url),
    })
    await user.upload(input(), [song('a.wav'), song('b.wav'), song('c.wav')])
    await user.click(copy.getByRole('button', { name: 'Add 3 files' }))
    const alert = await copy.findByRole('alert')
    expect(alert).toHaveTextContent("A file couldn't be copied")
    expect(alert).toHaveTextContent('b.wav: the file is empty')
    expect(callsTo(api, 'POST', '/api/library/files').map(nameOf)).toEqual(['a.wav', 'b.wav'])
    expect(callsTo(api, 'POST', '/api/ingest/files')).toHaveLength(0)
    expect(copy.getByRole('button', { name: 'Add 3 files' })).toBeEnabled()
  })

  it('shows why the job could not start (the files stay chosen)', async () => {
    const { user, input, copy } = await setup({
      [INGEST]: jsonResponse({ detail: 'not in the library: a.wav' }, 422),
    })
    await user.upload(input(), [song('a.wav')])
    await user.click(copy.getByRole('button', { name: 'Add 1 file' }))
    expect(await copy.findByRole('alert')).toHaveTextContent('not in the library: a.wav')
    expect(copy.getByRole('button', { name: 'Add 1 file' })).toBeEnabled()
  })

  it('cannot be submitted while another job runs, but still takes files', async () => {
    stubApi(baseRoutes({ 'GET /api/jobs': { jobs: [job({ kind: 'ingest-jamendo' })] } }))
    renderPage()
    const { user, copy } = await openYourFiles()
    await screen.findByRole('region', { name: 'Job progress' })
    await user.upload(screen.getByLabelText('Audio files to copy'), [song('a.wav')])
    expect(copy.getByText('1 file selected (1 KB)')).toBeInTheDocument()
    expect(copy.getByRole('button', { name: 'Add 1 file' })).toBeDisabled()
  })

  describe('dropping', () => {
    const zone = () => screen.getByText('Drop audio files or folders here').parentElement as HTMLElement
    const types = ['Files']

    it('lights up while a drag is over it and takes the dropped files', async () => {
      const { copy } = await setup()
      const box = zone()
      const files = [song('a.wav'), new File(['t'], 'readme.txt')]
      fireEvent.dragEnter(box, { dataTransfer: { files, types } })
      expect(copy.getByText('Drop to add them')).toBeInTheDocument()
      fireEvent.dragOver(box, { dataTransfer: { files, types } })
      fireEvent.drop(box, { dataTransfer: { files, types } })
      expect(await copy.findByText('1 file selected (1 KB)')).toBeInTheDocument()
      expect(copy.getByText("Skipped 1 file that isn't audio.")).toBeInTheDocument()
      expect(copy.queryByText('Drop to add them')).not.toBeInTheDocument()
    })

    it('stays lit while the drag moves over its children and goes out when it leaves', async () => {
      const { copy } = await setup()
      const box = zone()
      const child = box.firstElementChild!
      const data = { dataTransfer: { files: [], types } }
      fireEvent.dragEnter(box, data)
      fireEvent.dragEnter(child, data)
      fireEvent.dragLeave(box, data)
      expect(copy.getByText('Drop to add them')).toBeInTheDocument()
      fireEvent.dragLeave(child, data)
      expect(copy.queryByText('Drop to add them')).not.toBeInTheDocument()
    })

    it('refuses files dropped elsewhere on the page, so the browser does not open them', async () => {
      const { copy } = await setup()
      const outside = { dataTransfer: { files: [song('a.wav')], types, dropEffect: 'copy' } }
      expect(fireEvent.dragOver(document.body, outside)).toBe(false)
      expect(outside.dataTransfer.dropEffect).toBe('none')
      expect(fireEvent.drop(document.body, outside)).toBe(false)
      expect(copy.queryByText('1 file selected (1 KB)')).not.toBeInTheDocument()
      // The drop zone itself still offers a copy.
      const inside = { dataTransfer: { files: [], types, dropEffect: 'none' } }
      fireEvent.dragOver(zone(), inside)
      expect(inside.dataTransfer.dropEffect).toBe('copy')
    })

    it('ignores a drag that carries no files', async () => {
      const { copy } = await setup()
      fireEvent.dragEnter(zone(), { dataTransfer: { files: [], types: ['text/plain'] } })
      expect(copy.queryByText('Drop to add them')).not.toBeInTheDocument()
    })

    it('opens dropped folders, all levels and all batches', async () => {
      const { copy } = await setup()
      const fileEntry = (file: File) => ({
        isFile: true,
        isDirectory: false,
        name: file.name,
        file: (ok: (f: File) => void) => ok(file),
      })
      // The reader hands out its entries in batches, then an empty one.
      const dirEntry = (name: string, batches: unknown[][]) => ({
        isFile: false,
        isDirectory: true,
        name,
        createReader: () => {
          const queue = [...batches, []]
          return { readEntries: (ok: (entries: unknown[]) => void) => ok(queue.shift() ?? []) }
        },
      })
      const tree = dirEntry('Pack', [
        [fileEntry(song('one.wav')), dirEntry('Sub', [[fileEntry(song('two.ogg'))]])],
        [fileEntry(song('three.mp3')), fileEntry(new File(['t'], 'cover.png'))],
      ])
      const items = [
        { kind: 'file', webkitGetAsEntry: () => tree },
        { kind: 'file', webkitGetAsEntry: () => fileEntry(song('loose.flac')) },
        { kind: 'string', webkitGetAsEntry: () => null },
      ]
      fireEvent.drop(zone(), { dataTransfer: { files: [], items, types } })
      expect(await copy.findByText('4 files selected (1 KB)')).toBeInTheDocument()
      expect(copy.getByText("Skipped 1 file that isn't audio.")).toBeInTheDocument()
      for (const name of ['one.wav', 'two.ogg', 'three.mp3', 'loose.flac']) {
        expect(copy.getByText(name)).toBeInTheDocument()
      }
    })

    it('takes nothing while a copy is running', async () => {
      const { user, input, copy } = await setup({
        'POST /api/library/files': () => new Promise(() => {}),
      })
      await user.upload(input(), [song('a.wav')])
      await user.click(copy.getByRole('button', { name: 'Add 1 file' }))
      await copy.findByText('Copying 1 of 1: a.wav')
      fireEvent.drop(zone(), { dataTransfer: { files: [song('late.wav')], types } })
      await Promise.resolve()
      expect(copy.getByText('1 file selected (1 KB)')).toBeInTheDocument()
      expect(copy.queryByText('late.wav')).not.toBeInTheDocument()
    })
  })
})

describe('Your files: use a folder where it is', () => {
  const HOME = 'C:\\Users\\me'
  const MUSIC = `${HOME}\\Music`
  const listing = (path: string, parent: string | null, folders: string[], audio = 0, truncated = false) => ({
    path,
    parent,
    folders: folders.map((name) => ({ name, path: `${path}\\${name}` })),
    audio_files: audio,
    truncated,
  })
  const TREE: Record<string, unknown> = {
    [HOME]: listing(HOME, 'C:\\Users', ['Music', 'Broken']),
    [MUSIC]: listing(MUSIC, HOME, ['Pack'], 12),
    'D:\\': listing('D:\\', null, ['Sounds'], 1, true),
    'D:\\Typed': listing('D:\\Typed', 'D:\\', [], 0),
  }
  const ROOTS = {
    roots: [
      { name: 'C:\\', path: 'C:\\' },
      { name: 'D:\\', path: 'D:\\' },
    ],
    places: [{ name: 'Home', path: HOME }],
  }
  const listRoute = (url: URL) => {
    const path = url.searchParams.get('path') ?? ''
    return path in TREE
      ? jsonResponse(TREE[path])
      : jsonResponse({ detail: `folder not found: ${path}` }, 422)
  }
  const listed = (api: ReturnType<typeof stubApi>) =>
    callsTo(api, 'GET', '/api/files/list').map(([input]) => new URL(String(input), 'http://x').searchParams.get('path'))

  async function setup(localFiles: boolean | null = true, extra: Routes = {}) {
    const api = stubApi(
      baseRoutes({
        'GET /api/files/roots': ROOTS,
        'GET /api/files/list': listRoute,
        'POST /api/ingest/local': jsonResponse({ job: job({ kind: 'ingest-local' }) }, 202),
        ...extra,
      }),
    )
    renderPage(localFiles)
    const opened = await openYourFiles()
    return { api, ...opened }
  }

  it.each([
    { health: 'local', localFiles: true, shown: true },
    { health: 'not local', localFiles: false, shown: false },
    { health: 'unknown', localFiles: null, shown: false },
  ])('shows Browse only when the backend runs on this computer ($health)', async ({ localFiles, shown }) => {
    await setup(localFiles)
    expect(screen.queryByRole('button', { name: 'Browse…' }) !== null).toBe(shown)
  })

  it('opens at home, goes into a folder, up again, and fills the path with the folder chosen', async () => {
    const { api, user, folder } = await setup()
    await user.click(folder.getByRole('button', { name: 'Browse…' }))
    const drawer = within(await screen.findByRole('dialog', { name: 'Choose a folder' }))
    expect(await drawer.findByRole('button', { name: 'Music' })).toBeInTheDocument()
    expect(listed(api)).toEqual([HOME])
    expect(drawer.getByText(HOME)).toBeInTheDocument()
    expect(drawer.getByRole('button', { name: 'Home' })).toBeInTheDocument()
    expect(drawer.getByRole('button', { name: 'D:\\' })).toBeInTheDocument()

    await user.click(drawer.getByRole('button', { name: 'Music' }))
    expect(await drawer.findByText('12 audio files directly in this folder')).toBeInTheDocument()
    expect(listed(api)).toEqual([HOME, MUSIC])

    await user.click(drawer.getByRole('button', { name: 'Up' }))
    expect(await drawer.findByRole('button', { name: 'Broken' })).toBeInTheDocument()
    expect(listed(api)).toEqual([HOME, MUSIC, HOME])

    await user.click(drawer.getByRole('button', { name: 'Music' }))
    await drawer.findByText('12 audio files directly in this folder')
    await user.click(drawer.getByRole('button', { name: 'Use this folder' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(folder.getByLabelText('Folder path')).toHaveValue(MUSIC)

    await user.click(folder.getByRole('button', { name: 'Add from folder' }))
    await screen.findByRole('region', { name: 'Job progress' })
    expect(JSON.parse(String(callsTo(api, 'POST', '/api/ingest/local')[0]![1]!.body))).toEqual({
      path: MUSIC,
      embed: true,
    })
  })

  it('cannot go up from the top of a drive, and says when the list is cut short', async () => {
    const { user, folder } = await setup()
    await user.click(folder.getByRole('button', { name: 'Browse…' }))
    const drawer = within(await screen.findByRole('dialog', { name: 'Choose a folder' }))
    await drawer.findByRole('button', { name: 'Music' })
    await user.click(drawer.getByRole('button', { name: 'D:\\' }))
    expect(await drawer.findByRole('button', { name: 'Sounds' })).toBeInTheDocument()
    expect(drawer.getByRole('button', { name: 'Up' })).toBeDisabled()
    expect(drawer.getByText(/only some of the folders are listed/)).toBeInTheDocument()
    expect(drawer.getByText('1 audio file directly in this folder')).toBeInTheDocument()
  })

  it('starts at the typed path when it is an absolute path', async () => {
    const { api, user, folder } = await setup()
    await user.type(folder.getByLabelText('Folder path'), 'D:\\Typed')
    await user.click(folder.getByRole('button', { name: 'Browse…' }))
    const drawer = within(await screen.findByRole('dialog', { name: 'Choose a folder' }))
    expect(await drawer.findByText('D:\\Typed')).toBeInTheDocument()
    expect(listed(api)).toEqual(['D:\\Typed'])
    expect(drawer.getByText('No folders in here.')).toBeInTheDocument()
  })

  it('falls back to home, with the reason, when the typed path cannot be opened', async () => {
    const { api, user, folder } = await setup()
    await user.type(folder.getByLabelText('Folder path'), 'D:\\Nope')
    await user.click(folder.getByRole('button', { name: 'Browse…' }))
    const drawer = within(await screen.findByRole('dialog', { name: 'Choose a folder' }))
    expect(await drawer.findByRole('button', { name: 'Music' })).toBeInTheDocument()
    expect(listed(api)).toEqual(['D:\\Nope', HOME])
    expect(drawer.getByRole('alert')).toHaveTextContent('folder not found: D:\\Nope')
  })

  it('stays on the last good folder when a folder cannot be opened', async () => {
    const { user, folder } = await setup()
    await user.click(folder.getByRole('button', { name: 'Browse…' }))
    const drawer = within(await screen.findByRole('dialog', { name: 'Choose a folder' }))
    await user.click(await drawer.findByRole('button', { name: 'Broken' }))
    expect(await drawer.findByRole('alert')).toHaveTextContent(`folder not found: ${HOME}\\Broken`)
    expect(drawer.getByText(HOME)).toBeInTheDocument()
    expect(drawer.getByRole('button', { name: 'Music' })).toBeInTheDocument()
    expect(drawer.getByRole('button', { name: 'Use this folder' })).toBeEnabled()
  })

  it('leaves the path alone on Cancel', async () => {
    const { user, folder } = await setup()
    await user.type(folder.getByLabelText('Folder path'), 'E:\\Mine')
    await user.click(folder.getByRole('button', { name: 'Browse…' }))
    const drawer = within(await screen.findByRole('dialog', { name: 'Choose a folder' }))
    await drawer.findByRole('button', { name: 'Music' })
    await user.click(drawer.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(folder.getByLabelText('Folder path')).toHaveValue('E:\\Mine')
  })

  describe('in the desktop window', () => {
    afterEach(() => {
      delete window.pywebview
    })

    it('uses the native folder dialog, starting at the typed path, and opens no side panel', async () => {
      const pickFolder = vi.fn().mockResolvedValue('D:\\Picked')
      window.pywebview = { api: { pick_folder: pickFolder } }
      const { api, user, folder } = await setup()
      await user.type(folder.getByLabelText('Folder path'), 'E:\\Start')
      await user.click(folder.getByRole('button', { name: 'Browse…' }))
      await waitFor(() => expect(folder.getByLabelText('Folder path')).toHaveValue('D:\\Picked'))
      expect(pickFolder).toHaveBeenCalledWith('E:\\Start')
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(listed(api)).toEqual([])
    })

    it('keeps the path on cancel or when the dialog fails', async () => {
      const pickFolder = vi.fn().mockResolvedValueOnce(null).mockRejectedValueOnce(new Error('no dialog'))
      window.pywebview = { api: { pick_folder: pickFolder } }
      const { user, folder } = await setup()
      await user.click(folder.getByRole('button', { name: 'Browse…' }))
      await waitFor(() => expect(pickFolder).toHaveBeenCalledWith(null))
      expect(folder.getByLabelText('Folder path')).toHaveValue('')
      await user.type(folder.getByLabelText('Folder path'), 'E:\\Mine')
      await user.click(folder.getByRole('button', { name: 'Browse…' }))
      await waitFor(() => expect(pickFolder).toHaveBeenCalledTimes(2))
      expect(folder.getByLabelText('Folder path')).toHaveValue('E:\\Mine')
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('switches to the native dialog when pywebview arrives after the page', async () => {
      const pickFolder = vi.fn().mockResolvedValue('C:\\Late')
      const { user, folder } = await setup()
      window.pywebview = { api: { pick_folder: pickFolder } }
      fireEvent(window, new Event('pywebviewready'))
      await user.click(folder.getByRole('button', { name: 'Browse…' }))
      await waitFor(() => expect(folder.getByLabelText('Folder path')).toHaveValue('C:\\Late'))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})

describe('Maintenance: moved or deleted files', () => {
  const missing = (count: number) => ({
    count,
    tracks: Array.from({ length: Math.min(count, 200) }, (_, index) => ({
      id: index + 1,
      title: index === 0 ? null : `Song ${index + 1}`,
      local_path: `D:\\Gone\\song${index + 1}.wav`,
    })),
  })

  async function setup(routes: Routes) {
    const api = stubApi(baseRoutes(routes))
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('tab', { name: 'Maintenance' }))
    const card = within(screen.getByRole('region', { name: 'Moved or deleted files' }))
    return { api, user, card }
  }

  it('says nothing is missing', async () => {
    const { user, card } = await setup({ 'GET /api/tracks/missing': { count: 0, tracks: [] } })
    expect(card.getByText(/add the new folder again/)).toBeInTheDocument()
    await user.click(card.getByRole('button', { name: 'Check' }))
    expect(await card.findByText('Nothing missing.')).toBeInTheDocument()
    expect(card.queryByRole('button', { name: /^Remove/ })).not.toBeInTheDocument()
  })

  it('lists the first ten, asks before removing, removes, and reloads the track list', async () => {
    const { api, user, card } = await setup({
      'GET /api/tracks/missing': missing(12),
      'POST /api/tracks/remove-missing': { removed: 12 },
    })
    await user.click(card.getByRole('button', { name: 'Check' }))
    expect(await card.findByText('12 tracks have no file:')).toBeInTheDocument()
    expect(card.getByText('Untitled (D:\\Gone\\song1.wav)')).toBeInTheDocument()
    expect(card.getByText('Song 10 (D:\\Gone\\song10.wav)')).toBeInTheDocument()
    expect(card.queryByText(/Song 11/)).not.toBeInTheDocument()
    expect(card.getByText('and 2 more')).toBeInTheDocument()

    await user.click(card.getByRole('button', { name: 'Remove 12 tracks' }))
    const group = within(card.getByRole('group', { name: 'Remove the tracks without a file' }))
    expect(group.getByText('Remove 12 tracks and their ratings, labels and project entries?')).toBeInTheDocument()
    await user.click(group.getByRole('button', { name: 'Cancel' }))
    expect(callsTo(api, 'POST', '/api/tracks/remove-missing')).toHaveLength(0)

    const before = callsTo(api, 'GET', '/api/tracks').length
    await user.click(card.getByRole('button', { name: 'Remove 12 tracks' }))
    await user.click(within(card.getByRole('group')).getByRole('button', { name: 'Remove' }))
    expect(await card.findByText('Removed 12 tracks.')).toBeInTheDocument()
    expect(callsTo(api, 'POST', '/api/tracks/remove-missing')).toHaveLength(1)
    await waitFor(() => expect(callsTo(api, 'GET', '/api/tracks').length).toBeGreaterThan(before))
    expect(card.queryByText('12 tracks have no file:')).not.toBeInTheDocument()
  })

  it('counts all of them when the list is cut at 200', async () => {
    const { user, card } = await setup({ 'GET /api/tracks/missing': missing(500) })
    await user.click(card.getByRole('button', { name: 'Check' }))
    expect(await card.findByText('500 tracks have no file:')).toBeInTheDocument()
    expect(card.getByText('and 490 more')).toBeInTheDocument()
    expect(card.getByRole('button', { name: 'Remove 500 tracks' })).toBeInTheDocument()
  })

  it('shows the reason when a job is running (409)', async () => {
    const { user, card } = await setup({
      'GET /api/tracks/missing': missing(1),
      'POST /api/tracks/remove-missing': jsonResponse(
        { detail: 'A job is running; try again when it has finished.' },
        409,
      ),
    })
    await user.click(card.getByRole('button', { name: 'Check' }))
    await user.click(await card.findByRole('button', { name: 'Remove 1 track' }))
    await user.click(within(card.getByRole('group')).getByRole('button', { name: 'Remove' }))
    expect(await card.findByRole('alert')).toHaveTextContent('A job is running; try again when it has finished.')
    expect(card.queryByText(/^Removed/)).not.toBeInTheDocument()
  })
})
