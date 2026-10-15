import type { ReactNode } from 'react'
import { cx } from '../lib/cx'
import styles from './PageHeader.module.css'

export interface PageHeaderProps {
  title: string
  description?: ReactNode
  /** Buttons shown at the right. */
  actions?: ReactNode
  className?: string
}

/** The `<h1>` of a page, with an optional line of help and actions. One per page. */
export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  return (
    <header className={cx(styles.header, className)}>
      <div className={styles.text}>
        <h1>{title}</h1>
        {description ? <p className={styles.description}>{description}</p> : null}
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </header>
  )
}
