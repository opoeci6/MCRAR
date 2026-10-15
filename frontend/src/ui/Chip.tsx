import type { ButtonHTMLAttributes } from 'react'
import { cx } from '../lib/cx'
import { CheckIcon } from './icons'
import styles from './Chip.module.css'

export interface ChipProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
  selected: boolean
  onChange?: (selected: boolean) => void
}

/** A toggle chip for filters and tags: a button with `aria-pressed`, plus a check when on. */
export function Chip({ selected, onChange, onClick, className, children, ...rest }: ChipProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cx(styles.chip, selected && styles.selected, className)}
      onClick={(event) => {
        onClick?.(event)
        onChange?.(!selected)
      }}
      {...rest}
    >
      {selected ? <CheckIcon width={12} height={12} /> : null}
      {children}
    </button>
  )
}
