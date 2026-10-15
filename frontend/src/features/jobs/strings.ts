/** Text shared by every page that starts or follows a background job. */
export const jobStrings = {
  start: {
    busyTitle: 'Another job is running',
    busyBody: 'Wait for it to finish or cancel it, then try again.',
    showRunning: 'Show the running job',
    openLibrary: 'Open Library',
    failed: "Couldn't start the job",
    missingKeyTitle: 'Jamendo client id is not set',
    missingKeyBody: 'Jamendo needs a client id before it can be searched.',
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
