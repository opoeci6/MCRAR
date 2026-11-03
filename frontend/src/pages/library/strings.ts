import { trackFeatureStrings } from '../../features/track/strings'
import { UI_LOCALE } from '../../strings'

/** Text of the Library page. Add this page's strings here, not in src/strings.ts. */
export const libraryStrings = {
  title: 'Library',
  description: 'Everything in your catalog, and the tools to add more music.',

  stats: {
    heading: 'Catalog overview',
    loadFailed: "Couldn't load the catalog overview",
    tracks: 'Tracks',
    bySource: 'By source',
    byRisk: 'By licence risk',
    coverage: 'Analysed and embedded',
    analysed: (count: number, percent: string) => `${count} analysed (${percent})`,
    embedded: (model: string, count: number) => `${count} embedded with ${model}`,
    noEmbeddings: 'No tracks are embedded yet. Use "Re-embed missing tracks" to enable text search.',
    none: 'none',
    sourceNames: { ...trackFeatureStrings.sourceNames, local: 'Local folders' } as Record<string, string>,
  },

  tracks: {
    heading: 'Tracks',
    loadFailed: "Couldn't load the tracks",
    filterSource: 'Source',
    filterRisk: 'Licence risk',
    filterSearch: 'Search title or artist',
    searchPlaceholder: 'Title, artist or album',
    any: 'Any',
    sourceOptions: Object.entries({ ...trackFeatureStrings.sourceNames, local: 'Local folder' }).map(
      ([value, label]) => ({ value, label }),
    ),
    riskOptions: [
      { value: 'green', label: 'Safe' },
      { value: 'amber', label: 'Check terms' },
      { value: 'red', label: 'Restricted' },
      { value: 'unknown', label: 'Unknown' },
    ],
    tableLabel: 'Tracks in the catalog',
    play: (title: string) => `Play ${title}`,
    pause: (title: string) => `Pause ${title}`,
    columns: {
      play: 'Play',
      title: 'Title',
      artist: 'Artist',
      source: 'Source',
      duration: 'Length',
      license: 'Licence',
      actions: 'Actions',
    },
    /** The line under a title that stands in for the Source and Length columns in a narrow window. */
    meta: (source: string, length: string) => `${source} · ${length}`,
    untitled: 'Untitled',
    unknownArtist: 'Unknown artist',
    openDetails: (title: string) => `Show details of ${title}`,
    emptyTitle: 'No tracks here',
    emptyFiltered: 'No tracks match these filters.',
    emptyCatalog: 'The catalog is empty. Add music with the tools above.',
    range: (from: number, to: number, total: number) => `${from} to ${to} of ${total}`,
    previous: 'Previous',
    next: 'Next',
    pagination: 'Pages',
  },

  add: {
    heading: 'Add music',
    tabs: 'Ways to add music',
    jamendo: 'Jamendo',
    freesound: 'Freesound',
    links: 'By link',
    local: 'Your files',
    maintenance: 'Maintenance',
  },

  jamendo: {
    intro: 'Download the details of tracks from Jamendo, analyse them, and add them to your catalog.',
    tags: 'Tags',
    tagsHint: 'Comma separated, for example "ambient, calm". Leave empty to use only the search text.',
    search: 'Search text (optional)',
    vocals: 'Vocals',
    vocalsAny: 'Any',
    vocalsInstrumental: 'Instrumental only',
    vocalsVocal: 'With vocals only',
    commercialOnly: 'Only commercially usable licences',
    commercialOnlyHint: 'Skips tracks whose licence forbids commercial use.',
    limit: 'Number of tracks',
    limitHint: 'From 1 to 1000.',
    limitInvalid: 'Enter a whole number from 1 to 1000.',
    embed: 'Also embed the tracks for text search',
    embedHint: 'Takes longer. You can do it later with "Re-embed missing tracks".',
    submit: 'Add from Jamendo',
    starting: 'Starting',
  },

  freesound: {
    intro:
      "Music, loops and ambience from Freesound. Short sound effects aren't supported yet. The licence of each sound is kept with it.",
    search: 'Search words',
    searchHint: 'What to look for, for example "ambient pad". Optional if you give tags.',
    tags: 'Freesound tags',
    tagsHint:
      'Comma separated, for example "loop, ambient". Use letters a to z, digits, "-" and "_". Optional if you give search words.',
    tagInvalid: 'Tags can only use lowercase letters, digits, "-" and "_".',
    tagTooMany: 'Use at most 10 tags.',
    searchTooLong: 'Use at most 200 characters.',
    needQueryOrTag: 'Enter search words or at least one tag.',
    licenses: 'Licences',
    licenseNames: {
      cc0: 'CC0 (public domain)',
      by: 'CC BY (credit the author)',
      'by-nc': 'CC BY-NC (no commercial use)',
      'sampling+': 'Sampling+ (only transformed use)',
    } as Record<string, string>,
    licensesRequired: 'Choose at least one licence.',
    durationMin: 'Shortest sound (seconds)',
    durationMax: 'Longest sound (seconds)',
    durationInvalid: 'Enter a number of seconds, 0 or more.',
    durationMaxTooBig: 'Enter at most 3600 seconds.',
    durationOrder: 'The longest sound must not be shorter than the shortest.',
    sort: 'Order by',
    sortOptions: [
      { value: 'score', label: 'Best match' },
      { value: 'downloads_desc', label: 'Most downloaded' },
      { value: 'rating_desc', label: 'Highest rated' },
      { value: 'created_desc', label: 'Newest' },
      { value: 'duration_desc', label: 'Longest' },
      { value: 'duration_asc', label: 'Shortest' },
    ],
    limit: 'Number of sounds',
    limitHint: 'From 1 to 500.',
    limitInvalid: 'Enter a whole number from 1 to 500.',
    embed: 'Also embed the sounds for text search',
    embedHint: 'Takes longer. You can do it later with "Re-embed missing tracks".',
    submit: 'Add from Freesound',
    starting: 'Starting',
  },

  links: {
    intro: 'Add the tracks you found yourself. Their licences are kept with them.',
    label: 'Jamendo or Freesound links',
    hint: "One per line. Paste the track's page address from jamendo.com or freesound.org.",
    placeholder: 'https://www.jamendo.com/track/1234567/song-name',
    embed: 'Analyse and embed',
    embedHint: 'Takes longer. You can do it later with "Re-embed missing tracks".',
    submit: 'Add tracks',
    starting: 'Starting',
  },

  local: {
    intro:
      'Add music that is on your computer in one of two ways. Copying files gives MCRAR its own copies, so you can move or delete the originals. Using a folder where it is adds the files without copying them.',
    license: 'Licence (optional)',
    embed: 'Also embed the tracks for text search',
    embedHint: 'Takes longer. You can do it later with "Re-embed missing tracks".',
    copy: {
      title: 'Copy files into MCRAR',
      body: "MCRAR keeps a copy of each file in its own folder, so the copies use disk space. You can then move or delete the originals.",
      licenseHint: 'Applies to every file you add here.',
      dropTitle: 'Drop audio files or folders here',
      dropActive: 'Drop to add them',
      dropOr: 'or',
      choose: 'Choose files…',
      inputLabel: 'Audio files to copy',
      skipped: (count: number) =>
        count === 1 ? "Skipped 1 file that isn't audio." : `Skipped ${count} files that aren't audio.`,
      selected: (count: number, size: string) =>
        `${count === 1 ? '1 file' : `${count} files`} selected (${size})`,
      more: (count: number) => `and ${count} more`,
      clear: 'Clear the list',
      submit: (count: number) => (count === 0 ? 'Add files' : count === 1 ? 'Add 1 file' : `Add ${count} files`),
      progress: 'Copying files',
      copying: (index: number, total: number, name: string) => `Copying ${index} of ${total}: ${name}`,
      cancel: 'Cancel',
      cancelled: 'Cancelled. The files copied so far stay in MCRAR; adding them again is quick.',
      failedTitle: "A file couldn't be copied",
      failed: (name: string, message: string) => `${name}: ${message}`,
    },
    folder: {
      title: 'Use a folder where it is',
      body: 'The files stay where they are and nothing is copied. If you move or rename them later, playback stops working until you add the new folder again; MCRAR finds the files again by their content.',
      path: 'Folder path',
      pathHint: 'An absolute path, e.g. D:\\Music\\MyAssetPack',
      pathPlaceholder: 'D:\\Music\\MyAssetPack',
      browse: 'Browse…',
      licenseHint:
        'Applies to every file in the folder. Instead, you can put a mcrar-license.toml file in the folder to set licences per folder or file.',
      submit: 'Add from folder',
    },
  },

  folderBrowser: {
    title: 'Choose a folder',
    places: 'Places',
    drives: 'Drives',
    current: 'Current folder',
    up: 'Up',
    folders: 'Folders',
    noFolders: 'No folders in here.',
    audioFiles: (count: number) =>
      count === 1 ? '1 audio file directly in this folder' : `${count} audio files directly in this folder`,
    truncated: 'This folder has too many entries; only some of the folders are listed.',
    loading: 'Loading the folder',
    loadFailed: "Couldn't open that folder",
    rootsFailed: "Couldn't list the drives",
    use: 'Use this folder',
    cancel: 'Cancel',
  },

  maintenance: {
    intro: 'Run a step again for tracks already in the catalog.',
    embedTitle: 'Re-embed missing tracks',
    embedBody:
      'Computes the search embedding for tracks that do not have one yet. Needed for text search to find them.',
    embedAction: 'Re-embed missing tracks',
    tagTitle: 'Re-tag catalog',
    tagBody:
      'Recomputes genre and mood tags for every track with the selected tagging models.',
    tagAction: 'Re-tag catalog',
    missingTitle: 'Moved or deleted files',
    missingBody:
      'Finds tracks from your own files whose file is gone. If you only moved the files, add the new folder again instead: MCRAR finds them again by their content and the tracks work again.',
    missingCheck: 'Check',
    missingNone: 'Nothing missing.',
    missingFound: (count: number) =>
      count === 1 ? '1 track has no file:' : `${count} tracks have no file:`,
    missingItem: (title: string | null, path: string) => `${title || 'Untitled'} (${path})`,
    missingMore: (count: number) => `and ${count} more`,
    missingRemove: (count: number) => (count === 1 ? 'Remove 1 track' : `Remove ${count} tracks`),
    missingConfirmGroup: 'Remove the tracks without a file',
    missingConfirm: (count: number) =>
      count === 1
        ? 'Remove 1 track and its ratings, labels and project entries?'
        : `Remove ${count} tracks and their ratings, labels and project entries?`,
    confirm: 'Remove',
    cancel: 'Cancel',
    missingRemoved: (count: number) => (count === 1 ? 'Removed 1 track.' : `Removed ${count} tracks.`),
    missingFailed: "Couldn't check or remove the tracks",
  },

  start: {
    busyTitle: 'Another job is running',
    busyBody: 'Wait for it to finish or cancel it, then try again.',
  },

  jobs: {
    heading: 'Current job',
    panel: 'Job progress',
    kindNames: {
      'ingest-jamendo': 'Add from Jamendo',
      'ingest-freesound': 'Freesound import',
      'ingest-links': 'Add by link',
      'ingest-local': 'Add from folder',
      'ingest-files': 'Add files',
      'reprocess-embed': 'Re-embed missing tracks',
      'reprocess-tag': 'Re-tag catalog',
      'ingest-query': 'Add for a search',
    } as Record<string, string>,
    statusNames: {
      connecting: 'Connecting',
      running: 'Running',
      done: 'Finished',
      failed: 'Failed',
      cancelled: 'Cancelled',
    } as Record<string, string>,
    progressLabel: 'Progress',
    progressText: (index: number, total: number | null) =>
      total == null ? `${index} so far` : `${index} of ${total}`,
    currentTrack: 'Now',
    counters: { done: 'Done', skipped: 'Skipped', failed: 'Failed' },
    warnings: 'Warnings',
    cancel: 'Cancel job',
    cancelling: 'Cancelling',
    cancelRequested: 'Cancelling: the job stops after the current track.',
    cancelFailed: "Couldn't cancel the job",
    streamLost: 'Lost the connection to the job. Its last known state is shown.',
    errorTitle: 'The job failed',
    report: {
      heading: 'Report',
      seen: 'Seen',
      new: 'New',
      updated: 'Updated',
      processed: 'Processed',
      skipped: 'Skipped',
      failed: 'Failed',
      elapsed: 'Time',
      seconds: (value: number) => `${value.toFixed(1)} s`,
      aborted: (reason: string) => `Stopped early: ${reason}`,
      failures: (shown: number, total: number) =>
        total > shown ? `Failures (showing ${shown} of ${total})` : `Failures (${total})`,
      failure: (title: string, stage: string, message: string) =>
        `${title || 'Untitled'} (${stage}): ${message}`,
      already: (count: number) => `Already in your library: ${count}`,
      notFound: (list: string) => `Not found (or no preview): ${list}`,
      invalid: (list: string) => `Not understood: ${list}`,
      /** The first few of a long list, then how many more there are. */
      shortList: (items: string[], shown = 5) =>
        items.length > shown
          ? `${items.slice(0, shown).join(', ')} and ${items.length - shown} more`
          : items.join(', '),
    },
    viewNew: 'View new tracks',
    dismiss: 'Close',
    loadFailed: "Couldn't load the job list",
  },

  history: {
    heading: 'Job history',
    empty: 'No jobs have run since the backend started.',
    started: 'Started',
    kind: 'Job',
    status: 'Status',
    parameters: 'Details',
    show: 'Show',
    showJob: (kind: string) => `Show the ${kind} job`,
    table: 'Recent jobs',
    time: (iso: string) => {
      const date = new Date(iso)
      return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(UI_LOCALE)
    },
    paramsSummary: (params: Record<string, unknown>): string => {
      const parts: string[] = []
      const list = (value: unknown) => (Array.isArray(value) ? value.join(', ') : String(value))
      if (params.path) parts.push(String(params.path))
      if (Array.isArray(params.files)) {
        parts.push(params.files.length === 1 ? '1 file' : `${params.files.length} files`)
      }
      if (params.tags) parts.push(`tags: ${list(params.tags)}`)
      if (params.search) parts.push(`search: ${String(params.search)}`)
      if (params.query) parts.push(`search: ${String(params.query)}`)
      if (params.text) parts.push(`search: ${String(params.text)}`)
      if (params.license) parts.push(String(params.license))
      if (params.what) parts.push(String(params.what))
      if (params.limit) parts.push(`limit ${String(params.limit)}`)
      return parts.join(' / ')
    },
  },
}
