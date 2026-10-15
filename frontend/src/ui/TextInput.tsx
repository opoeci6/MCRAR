import { useId } from 'react'
import type { InputHTMLAttributes, ReactNode, Ref } from 'react'
import { cx } from '../lib/cx'
import styles from './Field.module.css'

export interface TextInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  /** The visible label (always required for a name). */
  label: string
  /** Hide the label visually; it stays the accessible name. */
  hideLabel?: boolean
  hint?: ReactNode
  /** An error message. Marks the input invalid. */
  error?: string
  ref?: Ref<HTMLInputElement>
}

export function TextInput({
  label,
  hideLabel,
  hint,
  error,
  id: givenId,
  className,
  type = 'text',
  ...rest
}: TextInputProps) {
  const generated = useId()
  const id = givenId ?? generated
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <div className={cx(styles.field, className)}>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : styles.label}>
        {label}
      </label>
      <input
        id={id}
        type={type}
        className={styles.control}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...rest}
      />
      {hint ? (
        <div id={hintId} className={styles.hint}>
          {hint}
        </div>
      ) : null}
      {error ? (
        <div id={errorId} className={styles.error}>
          {error}
        </div>
      ) : null}
    </div>
  )
}
