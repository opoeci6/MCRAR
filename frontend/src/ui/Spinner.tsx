import { cx } from '../lib/cx'
import { strings } from '../strings'
import styles from './Spinner.module.css'

export interface SpinnerProps {
  /** Accessible text. Defaults to "Loading". */
  label?: string
  size?: number
  className?: string
}

export function Spinner({ label = strings.common.loading, size = 20, className }: SpinnerProps) {
  return (
    <span role="status" className={cx(styles.wrap, className)}>
      <span className={styles.spinner} style={{ width: size, height: size }} aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  )
}
