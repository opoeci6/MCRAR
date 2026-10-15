import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { cx } from '../lib/cx'
import { Button } from './Button'
import type { ButtonSize, ButtonVariant } from './Button'
import { ChevronDownIcon } from './icons'
import { Popover } from './Popover'
import type { PopoverPlacement, PopoverTriggerProps } from './Popover'
import styles from './Menu.module.css'

const CloseContext = createContext<() => void>(() => {})

export interface MenuProps {
  /** Names the menu for screen readers and is the default trigger text. */
  label: string
  children: ReactNode
  /** Replaces the default text button. Spread `props` onto a `<button>`. */
  trigger?: (props: PopoverTriggerProps) => ReactNode
  triggerVariant?: ButtonVariant
  triggerSize?: ButtonSize
  placement?: PopoverPlacement
}

/**
 * A button that opens a list of actions. Arrow keys, Home and End move between items, Enter or
 * Space activates one, Escape closes and returns focus to the button.
 * Items are `MenuItem`s (and `MenuSeparator`s).
 */
export function Menu({
  label,
  children,
  trigger,
  triggerVariant = 'secondary',
  triggerSize = 'md',
  placement,
}: MenuProps) {
  return (
    <Popover
      label={label}
      role="menu"
      placement={placement}
      trigger={
        trigger ??
        ((props) => (
          <Button variant={triggerVariant} size={triggerSize} {...props}>
            {label}
            <ChevronDownIcon />
          </Button>
        ))
      }
    >
      {({ close }) => <CloseContext.Provider value={close}>{children}</CloseContext.Provider>}
    </Popover>
  )
}

export interface MenuItemProps {
  children: ReactNode
  onSelect?: () => void
  /** Makes the item a link (for example a credits download). */
  href?: string
  download?: boolean | string
  disabled?: boolean
  className?: string
}

export function MenuItem({ children, onSelect, href, download, disabled, className }: MenuItemProps) {
  const close = useContext(CloseContext)
  if (href !== undefined) {
    return (
      <a
        role="menuitem"
        href={href}
        download={download}
        className={cx(styles.item, className)}
        onClick={() => {
          onSelect?.()
          close()
        }}
      >
        {children}
      </a>
    )
  }
  return (
    <button
      type="button"
      role="menuitem"
      className={cx(styles.item, className)}
      disabled={disabled}
      onClick={() => {
        onSelect?.()
        close()
      }}
    >
      {children}
    </button>
  )
}

export function MenuSeparator() {
  return <hr className={styles.separator} />
}
