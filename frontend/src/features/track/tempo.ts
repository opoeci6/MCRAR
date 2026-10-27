/**
 * Mirrors `BPM_LOW_CONFIDENCE` in `backend/src/mcrar/catalog/repository.py` (the ranking and the
 * BPM filter use it too): below this confidence the tempo may be off by an octave, half or double.
 */
export const BPM_LOW_CONFIDENCE = 0.5

/** The analysed tempo is folded into 70 to 180 BPM, so only the other reading inside it is shown. */
const SHOW_HALF_FROM = 140
const SHOW_DOUBLE_BELOW = 90

export interface Tempo {
  /** The number part: "113" or "88 / 175" (no unit). */
  value: string
  /** Two readings are shown, because the tempo may be half or double. */
  uncertain: boolean
}

/**
 * How to show a tempo. A confident (or unknown-confidence) tempo is one number. An uncertain one
 * also shows the other reading when that falls inside 70 to 180: "88 / 175" for a fast tempo
 * (half first), "75 / 150" for a slow one.
 */
export function formatTempo(bpm: number, confidence: number | null | undefined): Tempo {
  const single: Tempo = { value: String(Math.round(bpm)), uncertain: false }
  if (confidence == null || confidence >= BPM_LOW_CONFIDENCE) return single
  if (bpm >= SHOW_HALF_FROM) {
    return { value: `${Math.round(bpm / 2)} / ${Math.round(bpm)}`, uncertain: true }
  }
  if (bpm < SHOW_DOUBLE_BELOW) {
    return { value: `${Math.round(bpm)} / ${Math.round(bpm * 2)}`, uncertain: true }
  }
  return single
}
