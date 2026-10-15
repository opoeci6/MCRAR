import { useRef } from 'react'
import type { KeyboardEvent } from 'react'
import type { RatingValue } from '../api/types'
import { cx } from '../lib/cx'
import { strings } from '../strings'
import { CheckIcon, CloseIcon } from './icons'
import styles from './RatingControl.module.css'

export interface RatingControlProps {
  /** The current rating, or `null` when the track is not rated. */
  value: RatingValue | null
  /** Called with the new rating; clicking the selected one again gives `null` (clear). */
  onChange: (value: RatingValue | null) => void
  disabled?: boolean
  className?: string
}

const OPTIONS: { value: RatingValue; label: string; tone: string }[] = [
  { value: 0, label: strings.rating.notAFit, tone: styles.bad },
  { value: 1, label: strings.rating.ok, tone: styles.mid },
  { value: 2, label: strings.rating.goodFit, tone: styles.good },
]

/**
 * Three toggle buttons: "Not a fit", "OK", "Good fit". Each is a real button with `aria-pressed`
 * (Tab, then Enter or Space). Left and Right arrows move between them.
 */
export function RatingControl({ value, onChange, disabled, className }: RatingControlProps) {
  const groupRef = useRef<HTMLDivElement>(null)

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    const buttons = Array.from(groupRef.current?.querySelectorAll('button') ?? [])
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (index < 0) return
    event.preventDefault()
    const step = event.key === 'ArrowRight' ? 1 : -1
    buttons[(index + step + buttons.length) % buttons.length]?.focus()
  }

  return (
    <div
      ref={groupRef}
      role="group"
      aria-label={strings.rating.group}
      className={cx(styles.group, className)}
      onKeyDown={onKeyDown}
    >
      {OPTIONS.map((option) => {
        const selected = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            disabled={disabled}
            className={cx(styles.option, option.tone, selected && styles.selected)}
            onClick={() => onChange(selected ? null : option.value)}
          >
            {selected && option.value === 2 ? <CheckIcon width={12} height={12} /> : null}
            {selected && option.value === 0 ? <CloseIcon width={12} height={12} /> : null}
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
