import { useId } from 'react'
import type { ReactNode, Ref, TextareaHTMLAttributes } from 'react'
import { cx } from '../lib/cx'
import styles from './Field.module.css'

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** The visible label (always required for a name). */
  label: string
  hint?: ReactNode
  /** An error message. Marks the field invalid. */
  error?: string
  ref?: Ref<HTMLTextAreaElement>
}

/** A multi-line text field with the label, hint and error of `TextInput`. */
export function TextArea({ label, hint, error, id: givenId, className, rows = 4, ...rest }: TextAreaProps) {
  const generated = useId()
  const id = givenId ?? generated
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <div className={cx(styles.field, className)}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <textarea
        id={id}
        rows={rows}
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
