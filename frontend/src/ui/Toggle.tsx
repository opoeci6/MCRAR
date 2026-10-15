import { useId } from 'react'
import type { InputHTMLAttributes, ReactNode } from 'react'
import { cx } from '../lib/cx'
import styles from './Toggle.module.css'

export interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange' | 'checked'> {
  label: ReactNode
  hint?: ReactNode
  checked: boolean
  onChange: (checked: boolean) => void
}

/** A labelled native checkbox. */
export function Checkbox({ label, hint, checked, onChange, className, disabled, ...rest }: CheckboxProps) {
  const hintId = useId()
  return (
    <label className={cx(styles.row, disabled && styles.disabled, className)}>
      <input
        type="checkbox"
        className={styles.checkbox}
        checked={checked}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(event) => onChange(event.target.checked)}
        {...rest}
      />
      <span className={styles.text}>
        <span>{label}</span>
        {hint ? (
          <span id={hintId} className={styles.hint}>
            {hint}
          </span>
        ) : null}
      </span>
    </label>
  )
}

export interface ToggleProps {
  label: ReactNode
  hint?: ReactNode
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
}

/** An on/off switch (`role="switch"`): Space or Enter flips it. For settings that apply at once. */
export function Toggle({ label, hint, checked, onChange, disabled, className }: ToggleProps) {
  const id = useId()
  const hintId = `${id}-hint`
  return (
    <div className={cx(styles.row, disabled && styles.disabled, className)}>
      <button
        type="button"
        id={id}
        role="switch"
        className={styles.switch}
        aria-checked={checked}
        aria-describedby={hint ? hintId : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      />
      <span className={styles.text}>
        <label htmlFor={id}>{label}</label>
        {hint ? (
          <span id={hintId} className={styles.hint}>
            {hint}
          </span>
        ) : null}
      </span>
    </div>
  )
}
