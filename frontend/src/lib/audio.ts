/**
 * The `accept` of a file picker: the audio types the backend reads (AUDIO_EXTENSIONS in
 * backend/src/mcrar/sources/local_folder.py). The backend still checks the file.
 */
export const AUDIO_ACCEPT = '.wav,.wave,.flac,.ogg,.oga,.opus,.mp3,.aif,.aiff'

/** Whether a file name ends in one of the audio extensions of `AUDIO_ACCEPT`. */
export function isAudioFile(name: string): boolean {
  const dot = name.lastIndexOf('.')
  return dot >= 0 && AUDIO_ACCEPT.split(',').includes(name.slice(dot).toLowerCase())
}
