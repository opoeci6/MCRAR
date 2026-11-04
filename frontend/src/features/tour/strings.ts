/** Text of the first-run tour. Add this feature's strings here, not in src/strings.ts. */
export const tourStrings = {
  skip: 'Skip',
  back: 'Back',
  next: 'Next',
  done: 'Done',
  start: 'Take the tour',
  progress: (step: number, total: number) => `Step ${step} of ${total}`,

  welcome: {
    title: 'Welcome to MCRAR',
    body: 'MCRAR finds music from a description and keeps everything on your PC. On the first start the search model (about 0.8 GB) downloads in the background, so you can take the tour while you wait.',
  },
  nav: {
    title: 'Five tabs',
    body: 'Search, Projects, Library, Labelling and Settings. Click a tab to switch.',
  },
  keys: {
    title: 'Free sources need a key',
    body: 'Paste a free Jamendo client id or Freesound API key here. Your own files need none.',
  },
  addMusic: {
    title: 'Add music',
    body: 'Import from Jamendo or Freesound, paste track links, or add your own files.',
  },
  searchBox: {
    title: 'Describe what you need',
    body: 'Type something like "calm piano for a rainy city level", or drop a song here to find similar ones.',
  },
  filters: {
    title: 'Filters',
    body: 'Keep only licences that are safe to use, limit the length, or pick a game scene.',
  },
  projects: {
    title: 'Projects',
    body: 'Shortlist tracks for each game or video, and export the credits you owe.',
  },
  finish: {
    title: "That's it",
    body: 'You can take this tour again here, in Settings.',
  },
}
