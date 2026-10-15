/*
 * User-facing text shared by more than one place: the app shell, the design-system components,
 * the player and the API client.
 *
 * Where strings go (so parallel work never conflicts):
 *   - shared and `ui/` strings: this file;
 *   - a page owns `src/pages/<name>/strings.ts`;
 *   - a feature owns `src/features/<name>/strings.ts`.
 * Never hard-code visible text in a component. English only for now; to translate later, replace
 * these modules (each exports a plain object, with functions where a value is interpolated).
 */

/** Locale for dates and numbers: the UI text is English, so the browser's language would mix in. */
export const UI_LOCALE = 'en'

export const strings = {
  app: {
    name: 'MCRAR',
    tagline: 'Find music you can actually use',
    skipToContent: 'Skip to content',
    mainNav: 'Main',
  },
  nav: {
    search: 'Search',
    projects: 'Projects',
    library: 'Library',
    settings: 'Settings',
  },
  common: {
    loading: 'Loading',
    close: 'Close',
    cancel: 'Cancel',
    save: 'Save',
    delete: 'Delete',
    retry: 'Try again',
    dismiss: 'Dismiss',
    unknown: 'Unknown',
    opensInNewTab: '(opens in a new tab)',
  },
  errors: {
    network: "Couldn't reach the MCRAR backend",
    generic: (status: number) => `The request failed (HTTP ${status})`,
    unexpectedResponse: 'The backend sent a response the app could not read',
  },
  backend: {
    checking: 'Checking backend',
    online: 'Backend online',
    offline: 'Backend offline',
    onlineTitle: (version: string, tracks: number) =>
      `MCRAR ${version}, ${tracks} ${tracks === 1 ? 'track' : 'tracks'} in the catalog`,
    offlineTitle: "Can't reach the backend",
    offlineBody: 'Start it in a terminal with the command below. This page reconnects by itself.',
    offlineCommand: 'mcrar serve',
  },
  toast: {
    region: 'Notifications',
    dismiss: 'Dismiss notification',
  },
  license: {
    risk: {
      green: 'Safe',
      amber: 'Check terms',
      red: 'Restricted',
      unknown: 'Unknown',
    },
    riskLong: {
      green: 'Generally safe to use, including commercially, with the credit below',
      amber: 'Copyleft or share-alike: check what it requires of your project',
      red: 'Not usable in a commercial project as is',
      unknown: 'The licence is not known: treat it as not cleared',
    },
    noCode: 'No licence',
    details: 'Licence details',
    label: 'Licence',
    attribution: 'Credit line',
    copyCredit: 'Copy credit',
    copied: 'Copied',
    copyFailed: "Couldn't copy",
    licenseLink: 'Read the licence',
    commercialLink: 'Buy a commercial licence',
  },
  rating: {
    group: 'How well does this track fit?',
    notAFit: 'Not a fit',
    ok: 'OK',
    goodFit: 'Good fit',
  },
  breakdown: {
    title: 'Why this score',
    terms: {
      semantic: 'Matches the description',
      tags: 'Genre and mood',
      bpm: 'Tempo',
      energy: 'Energy',
    } as Record<string, string>,
    inactive: 'not used',
    describe: (label: string, raw: string, weight: string, contribution: string) =>
      `${label}: score ${raw}, weight ${weight}, adds ${contribution}`,
    describeInactive: (label: string) => `${label}: not used in this search`,
  },
  player: {
    bar: 'Audio player',
    play: 'Play',
    pause: 'Pause',
    loading: 'Loading audio',
    seek: 'Seek',
    seekValue: (current: string, total: string) => `${current} of ${total}`,
    volume: 'Volume',
    error: "Couldn't play this track",
    unknownTitle: 'Untitled',
    unknownArtist: 'Unknown artist',
  },
  empty: {
    comingSoon: 'This page is being built.',
  },
}
