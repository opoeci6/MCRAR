import type { ReactNode } from 'react'
import { cx } from '../lib/cx'
import { AlertIcon, InfoIcon } from './icons'
import styles from './Notice.module.css'

export type NoticeKind = 'info' | 'warning' | 'error'

export interface NoticeProps {
  kind?: NoticeKind
  title?: string
  children?: ReactNode
  /** Usually a Button, shown at the end. */
  action?: ReactNode
  className?: string
}

/** An inline message. Errors are announced at once (`role="alert"`); the rest politely. */
export function Notice({ kind = 'info', title, children, action, className }: NoticeProps) {
  return (
    <div
      className={cx(styles.notice, styles[kind], className)}
      role={kind === 'error' ? 'alert' : 'status'}
    >
      <span className={styles.icon}>
        {kind === 'info' ? <InfoIcon width={14} height={14} /> : <AlertIcon width={14} height={14} />}
      </span>
      <div className={styles.body}>
        {title ? <strong className={styles.title}>{title}</strong> : null}
        {children ? <div className={styles.text}>{children}</div> : null}
      </div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  )
}
