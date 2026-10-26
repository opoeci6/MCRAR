/** Text of the Labelling page. Add this page's strings here, not in src/strings.ts. */
export const labelStrings = {
  title: 'Labelling',
  description:
    'Listen to each track for a minute or so, then tick every game scene it could plausibly be the music for and say how intense it feels. Judge the sound, not the title.',

  who: {
    name: 'Your name',
    nameHint: 'Tells your labels apart from other people’s. Use the same name every time.',
    nameInvalid: 'Enter a name of 1 to 40 characters.',
    part: 'Part',
    partOptions: { all: 'All tracks', A: 'Part A', B: 'Part B' } as Record<string, string>,
  },

  progress: {
    label: 'Labelling progress',
    summary: (done: number, total: number, skipped: number) =>
      `${done} of ${total} done · ${skipped} skipped`,
    labellers: (names: string) => `Labellers so far: ${names}`,
    loadFailed: "Couldn't load your progress",
  },

  exportLabels: 'Export my labels',

  noPool: {
    title: 'No labelling pool yet',
    description:
      'The tracks to label are chosen on the command line. Run mcrar scenes pool (or import the pack the owner sent with mcrar scenes import-pack), then reload this page.',
  },

  done: {
    title: 'All done for this part',
    description: 'Every track of this part is labelled or skipped. Thank you! Send the labels file to the owner.',
    pickAnother: 'You can pick another part above, or open the pool list to revisit a track.',
  },

  scenesFailed: "Couldn't load the list of game scenes",
  noScenes: 'This backend has no game scenes yet. Update MCRAR, then reload this page.',

  loading: 'Loading the next track',
  loadFailed: "Couldn't load the next track",
  retry: 'Try again',

  card: {
    position: (index: number, total: number) => `Track ${index} of ${total}`,
    untitled: 'Untitled',
    unknownArtist: 'Unknown artist',
    byArtist: (artist: string) => `by ${artist}`,
    play: (title: string) => `Play ${title}`,
    pause: (title: string) => `Pause ${title}`,
    jump: (percent: number) => `Jump to ${percent}%`,
    saved: 'Saved',
    savedSkipped: 'Skipped',
    deleteLabel: 'Delete label',
  },

  form: {
    scenes: 'Which game scenes could this music play in?',
    none: 'None of these',
    noneTitle: 'No scene fits this music',
    intensity: 'Intensity',
    intensityHint: 'Optional.',
    intensityOptions: [
      { value: 'low', label: 'Low', title: 'Calm, background' },
      { value: 'mid', label: 'Mid', title: 'In between' },
      { value: 'high', label: 'High', title: 'Loud, driving' },
    ] as const,
    saveAndNext: 'Save and next',
    saving: 'Saving',
    skip: 'Skip',
    skipTitle: 'You cannot judge this track (broken audio, no time). It is not asked again.',
    back: 'Back',
    backTitle: 'Go to the previous track of the list',
    saveFailed: "Couldn't save the label",
    deleteFailed: "Couldn't delete the label",
    openFailed: "Couldn't open that track",
  },

  /** What the music could play during, by scene id (docs/labelling.md). */
  sceneHelp: {
    combat: 'Fighting ordinary enemies, action sequences',
    boss: 'A boss fight, a final battle',
    exploration: 'Travelling through an open world or an adventure',
    menu: 'The main menu or title screen',
    town: 'A peaceful town, a village, a shop',
    puzzle: 'Solving puzzles, calm thinking levels',
    stealth: 'Sneaking, tense infiltration',
    horror: 'Scary or haunted places',
    victory: 'A win, a level-complete fanfare',
    defeat: 'Game over, losing',
    credits: 'The end credits',
    cutscene: 'An emotional story moment or farewell',
    chase: 'Fleeing or being chased, frantic escapes',
    ambient: 'Quiet background atmosphere, building, farming',
  } as Record<string, string>,

  shortcuts: {
    summary: 'Keyboard shortcuts',
    note: 'They work while the cursor is not in a text field.',
    rows: [
      { keys: '1–9, 0, Q, W, E, R', action: 'Tick or untick the scenes, in the order shown' },
      { keys: 'N', action: 'None of these' },
      { keys: 'A / S / D', action: 'Intensity low / mid / high' },
      { keys: 'Enter', action: 'Save and next' },
      { keys: 'K', action: 'Skip' },
      { keys: 'B', action: 'Back' },
      { keys: 'Space', action: 'Play or pause' },
    ],
  },

  pool: {
    toggle: (count: number) => `Pool list (${count})`,
    list: 'Tracks of this part',
    statusLabels: { labelled: 'Labelled', skipped: 'Skipped', todo: 'To do' },
    loadFailed: "Couldn't load the pool list",
  },
}
