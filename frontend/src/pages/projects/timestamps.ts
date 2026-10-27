import { formatTime } from '../../lib/format'

/** A piece of a note: plain text, or a time such as "1:23" that can be played from. */
export interface NotePart {
  text: string
  /** Set for a timestamp. */
  seconds?: number
}

/**
 * `m:ss`, `mm:ss` or `h:mm:ss` (seconds and, with hours, minutes are 00 to 59). It must not touch
 * a letter or digit, and must not be part of a longer run such as "12:75:30", so a trailing
 * colon ("0:18: nice intro") or full stop still counts.
 */
const TIMESTAMP = /(?<!\w)(?<!\d:)(\d{1,2}):([0-5]\d)(?::([0-5]\d))?(?!\w|:\d)/g

/** The position as the note writes it: "0:18", "12:05" or "1:02:03". */
export function formatTimestamp(seconds: number): string {
  return formatTime(Number.isFinite(seconds) && seconds > 0 ? seconds : 0)
}

/** The seconds a timestamp token stands for, or `null` when the text is not exactly one. */
export function parseTimestamp(token: string): number | null {
  const match = new RegExp(`^${TIMESTAMP.source}$`).exec(token)
  return match ? secondsOf(match) : null
}

function secondsOf(match: RegExpExecArray): number {
  const [, first = '0', second = '0', third] = match
  return third === undefined
    ? Number(first) * 60 + Number(second)
    : Number(first) * 3600 + Number(second) * 60 + Number(third)
}

/** Cuts a note into plain text and timestamps, in order. The parts join back to the note. */
export function splitTimestamps(note: string): NotePart[] {
  const parts: NotePart[] = []
  let last = 0
  for (const match of note.matchAll(TIMESTAMP)) {
    if (match.index > last) parts.push({ text: note.slice(last, match.index) })
    parts.push({ text: match[0], seconds: secondsOf(match) })
    last = match.index + match[0].length
  }
  if (last < note.length) parts.push({ text: note.slice(last) })
  return parts
}
