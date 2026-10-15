import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react'
import { cx } from '../lib/cx'
import styles from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** An icon shown before the label. */
  icon?: ReactNode
  ref?: Ref<HTMLButtonElement>
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(styles.button, styles[variant], size !== 'md' && styles[size], className)}
      {...rest}
    >
      {icon}
      {children}
    </button>
  )
}

export interface IconButtonProps
  extends Omit<ButtonProps, 'icon' | 'aria-label' | 'children'> {
  /** What the button does. Required: an icon alone is not a name. */
  label: string
  children: ReactNode
}

/** A square button with only an icon. `label` becomes its accessible name and its tooltip. */
export function IconButton({
  label,
  variant = 'ghost',
  size = 'md',
  className,
  children,
  ...rest
}: IconButtonProps) {
  return (
    <Button
      variant={variant}
      size={size}
      aria-label={label}
      title={label}
      className={cx(styles.icon, className)}
      {...rest}
    >
      {children}
    </Button>
  )
}
