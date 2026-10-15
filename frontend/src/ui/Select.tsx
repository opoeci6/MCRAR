import { useId } from 'react'
import type { ReactNode, Ref, SelectHTMLAttributes } from 'react'
import { cx } from '../lib/cx'
import styles from './Field.module.css'

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string
  hideLabel?: boolean
  hint?: ReactNode
  /** The `<option>` elements. */
  children: ReactNode
  ref?: Ref<HTMLSelectElement>
}

/** A native `<select>`, styled. Native keeps the keyboard and screen-reader behaviour for free. */
export function Select({ label, hideLabel, hint, id: givenId, className, children, ...rest }: SelectProps) {
  const generated = useId()
  const id = givenId ?? generated
  const hintId = `${id}-hint`
  return (
    <div className={cx(styles.field, className)}>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : styles.label}>
        {label}
      </label>
      <select
        id={id}
        className={styles.control}
        aria-describedby={hint ? hintId : undefined}
        {...rest}
      >
        {children}
      </select>
      {hint ? (
        <div id={hintId} className={styles.hint}>
          {hint}
        </div>
      ) : null}
    </div>
  )
}
