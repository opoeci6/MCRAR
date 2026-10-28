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
    local: 'Local folder',
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

  local: {
    intro:
      'Scan a folder of audio files on the computer that runs MCRAR, and add them to your catalog.',
    path: 'Folder path',
    pathHint: 'An absolute path, e.g. D:\\Music\\MyAssetPack',
    pathPlaceholder: 'D:\\Music\\MyAssetPack',
    license: 'Licence (optional)',
    licenseHint:
      'Applies to every file in the folder. Instead, you can put a mcrar-license.toml file in the folder to set licences per folder or file.',
    licenseSuggestions: ['CC0', 'CC BY 4.0', 'CC BY-SA 4.0', 'CC BY-NC 4.0', 'CC BY-ND 4.0'],
    embed: 'Also embed the tracks for text search',
    embedHint: 'Takes longer. You can do it later with "Re-embed missing tracks".',
    submit: 'Add from folder',
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
      'ingest-local': 'Add from folder',
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
