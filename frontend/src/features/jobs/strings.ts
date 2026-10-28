/** Text shared by every page that starts or follows a background job. */
export const jobStrings = {
  start: {
    busyTitle: 'Another job is running',
    busyBody: 'Wait for it to finish or cancel it, then try again.',
    showRunning: 'Show the running job',
    openLibrary: 'Open Library',
    failed: "Couldn't start the job",
    /** A 503 that says which key is missing: the notice names it and leads to Settings. */
    missingKey: {
      jamendo: {
        title: 'Jamendo client id is not set',
        body: 'Jamendo needs a client id before it can be searched.',
      },
      freesound: {
        title: 'Freesound API key is not set',
        body: 'Freesound needs an API key before it can be searched. Add it in Settings, under API keys.',
      },
    } as Record<string, { title: string; body: string }>,
    /** A 503 that names more than one source: none of them is set up. */
    missingKeyAll: {
      title: 'No Jamendo client id or Freesound API key is set',
      body: 'Searching for more music needs a Jamendo client id or a Freesound API key. Add one in Settings, under API keys.',
    },
    openSettings: 'Open Settings',
  },
  progress: {
    panel: 'Job progress',
    label: 'Progress',
    text: (index: number, total: number | null) =>
      total == null ? `${index} so far` : `${index} of ${total}`,
    currentTrack: 'Now',
    cancel: 'Cancel',
    cancelling: 'Cancelling',
    cancelFailed: "Couldn't cancel the job",
    streamLost: 'Lost the connection to the job. Its last known state is shown.',
  },
}
