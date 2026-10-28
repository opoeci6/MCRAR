import type { ReferenceRef } from '../../api/types'

/** The reference song of a search: a catalog track or an uploaded file, with the name to show. */
export type Reference =
  | { kind: 'track'; trackId: number; label: string }
  | { kind: 'upload'; uploadId: string; label: string }

/** The `reference` of a search request. */
export function toApiReference(reference: Reference): ReferenceRef {
  return reference.kind === 'track' ? { track_id: reference.trackId } : { upload_id: reference.uploadId }
}

/** "Title — Artist", or the title alone without an artist. */
export function trackLabel(title: string, artist: string | null): string {
  return artist ? `${title} — ${artist}` : title
}

/**
 * The `accept` of the file picker: the audio types the backend reads (AUDIO_EXTENSIONS in
 * backend/src/mcrar/sources/local_folder.py). The backend still checks the file.
 */
export const AUDIO_ACCEPT = '.wav,.wave,.flac,.ogg,.oga,.opus,.mp3,.aif,.aiff'

/** Whether a file name ends in one of the audio extensions of `AUDIO_ACCEPT`. */
export function isAudioFile(name: string): boolean {
  const dot = name.lastIndexOf('.')
  return dot >= 0 && AUDIO_ACCEPT.split(',').includes(name.slice(dot).toLowerCase())
}

/** The weight a reference has next to a text when the user has not moved the slider. */
export const DEFAULT_REFERENCE_WEIGHT = 0.5
