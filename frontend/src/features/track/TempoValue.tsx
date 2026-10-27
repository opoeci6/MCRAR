import { useId, type ReactNode } from 'react'
import { trackFeatureStrings } from './strings'
import { formatTempo } from './tempo'

export interface TempoValueProps {
  bpm: number
  confidence: number | null | undefined
  /** Text after the tempo, inside the same element (the drawer's "(40% confidence)"). */
  suffix?: ReactNode
}

/** "113 BPM", or "88 / 175 BPM" with a tooltip and description when the tempo is uncertain. */
export function TempoValue({ bpm, confidence, suffix }: TempoValueProps) {
  const hintId = useId()
  const tempo = formatTempo(bpm, confidence)
  const hint = trackFeatureStrings.features.tempoUncertain
  const text = trackFeatureStrings.features.bpmValue(tempo.value)
  if (!tempo.uncertain) {
    return (
      <span>
        {text}
        {suffix}
      </span>
    )
  }
  return (
    <span title={hint} aria-describedby={hintId}>
      {text}
      {suffix}
      <span id={hintId} hidden>
        {hint}
      </span>
    </span>
  )
}
