import type { ReactNode } from 'react'
import { cx } from '../lib/cx'
import styles from './EmptyState.module.css'

export interface EmptyStateProps {
  title: string
  description?: ReactNode
  /** Usually a Button. */
  action?: ReactNode
  icon?: ReactNode
  className?: string
}

/** A calm placeholder for "nothing here yet", "no results" and "not built yet". */
export function EmptyState({ title, description, action, icon, className }: EmptyStateProps) {
  return (
    <div className={cx(styles.empty, className)}>
      {icon ? (
        <div className={styles.icon} aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <h2 className={styles.title}>{title}</h2>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  )
}
