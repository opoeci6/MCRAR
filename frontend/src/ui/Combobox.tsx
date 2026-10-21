import { useEffect, useId, useRef, useState } from 'react'
import type { CSSProperties, InputHTMLAttributes, KeyboardEvent, ReactNode } from 'react'
import { cx } from '../lib/cx'
import fieldStyles from './Field.module.css'
import styles from './Combobox.module.css'
import { ChevronDownIcon } from './icons'

export interface ComboboxOption {
  value: string
  /** Shown after the value in muted text. */
  label?: string | null
}

export interface ComboboxProps
  extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    'size' | 'value' | 'onChange' | 'list' | 'role' | 'type'
  > {
  /** The visible label (always required for a name). */
  label: string
  /** Hide the label visually; it stays the accessible name. */
  hideLabel?: boolean
  hint?: ReactNode
  /** An error message. Marks the input invalid. */
  error?: string
  value: string
  /** Suggestions. With none, this is a plain text input. */
  options: ComboboxOption[]
  /** Called with the typed text, or with the chosen option's value. */
  onValueChange: (value: string) => void
  /** Accessible name of the list. */
  listLabel: string
  /** Accessible name of the button that opens the list. */
  toggleLabel: string
  /** Shown in the list when the typed text matches no option. */
  emptyText: string
  /** The option an empty field stands for (for example a default), marked and scrolled to. */
  emptyValue?: string
}

const LIST_MAX_HEIGHT = 280
const LIST_MIN_HEIGHT = 120
/** Room below the input that the list should not use (the player bar sits at the window bottom). */
const BOTTOM_MARGIN = 120
/** Open upward when there is less than this below and more above. */
const MIN_SPACE_BELOW = 200
const EDGE_GAP = 12

interface Placement {
  up: boolean
  maxHeight: number
}

/**
 * A text input with suggestions in an in-page list (a native datalist popup cannot be styled and
 * is misplaced in some embedded browsers). Any text can be typed; choosing an option sets it.
 * Typing filters the list by substring, while opening it by button, click or arrow key shows all
 * options. ARIA 1.2 combobox pattern with a listbox popup.
 */
export function Combobox({
  label,
  hideLabel,
  hint,
  error,
  id: givenId,
  className,
  value,
  options,
  onValueChange,
  listLabel,
  toggleLabel,
  emptyText,
  emptyValue = '',
  disabled,
  ...rest
}: ComboboxProps) {
  const generated = useId()
  const id = givenId ?? generated
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const listId = `${id}-list`
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ')

  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  // Set only by typing, so a value that was not typed since the list opened never hides options.
  const [filterText, setFilterText] = useState<string | null>(null)
  const [placement, setPlacement] = useState<Placement>({ up: false, maxHeight: LIST_MAX_HEIGHT })

  const hasOptions = options.length > 0
  const current = value || emptyValue
  const needle = (filterText ?? '').trim().toLowerCase()
  const shown = needle
    ? options.filter((o) => o.value.toLowerCase().includes(needle) || (o.label ?? '').toLowerCase().includes(needle))
    : options
  const isOpen = open && hasOptions && !disabled
  const activeIndex = isOpen && active >= 0 && active < shown.length ? active : -1
  const optionId = (index: number) => `${id}-option-${index}`

  // Keeps the active option in view; with none, a list that just opened shows the current value.
  const selectedIndex = shown.findIndex((o) => o.value === current)
  const scrollTo = activeIndex >= 0 ? activeIndex : selectedIndex
  useEffect(() => {
    if (!isOpen || scrollTo < 0) return
    const element = listRef.current?.children[scrollTo] as HTMLElement | undefined
    element?.scrollIntoView?.({ block: 'nearest' })
    // The current value is scrolled to only when the list opens, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, isOpen])

  const measure = () => {
    const input = inputRef.current
    if (!input) return
    const rect = input.getBoundingClientRect()
    const below = window.innerHeight - rect.bottom - BOTTOM_MARGIN
    // The sticky page header covers the top of the window.
    const header = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h'))
    const above = rect.top - (Number.isFinite(header) ? header : 0) - EDGE_GAP
    const up = below < MIN_SPACE_BELOW && above > below
    const space = up ? above : below
    setPlacement({ up, maxHeight: Math.min(LIST_MAX_HEIGHT, Math.max(LIST_MIN_HEIGHT, space)) })
  }

  /** Opens with every option shown; `index` is the option to make active (-1 for none). */
  const openAll = (index: number) => {
    if (!hasOptions || disabled) return
    if (!open) measure()
    setFilterText(null)
    setActive(index)
    setOpen(true)
  }

  const close = () => {
    setOpen(false)
    setActive(-1)
    setFilterText(null)
  }

  const choose = (option: ComboboxOption) => {
    onValueChange(option.value)
    close()
  }

  const currentIndex = () => Math.max(0, options.findIndex((o) => o.value === current))

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!hasOptions || disabled) return
    const last = shown.length - 1
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        event.preventDefault()
        if (!isOpen) {
          openAll(event.altKey ? -1 : event.key === 'ArrowDown' ? currentIndex() : options.length - 1)
        } else if (last >= 0 && !event.altKey) {
          const step = event.key === 'ArrowDown' ? 1 : -1
          setActive(activeIndex < 0 ? (step === 1 ? 0 : last) : (activeIndex + step + shown.length) % shown.length)
        }
        break
      }
      case 'Home':
      case 'End':
        if (isOpen && last >= 0) {
          event.preventDefault()
          setActive(event.key === 'Home' ? 0 : last)
        }
        break
      case 'Enter': {
        const option = shown[activeIndex]
        if (isOpen && option) {
          event.preventDefault()
          choose(option)
        }
        break
      }
      case 'Escape':
        if (isOpen) {
          event.preventDefault()
          event.stopPropagation()
          close()
        }
        break
      case 'Tab':
        if (isOpen) close()
        break
    }
  }

  const style: CSSProperties = { maxHeight: placement.maxHeight }

  return (
    <div className={cx(fieldStyles.field, className)}>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : fieldStyles.label}>
        {label}
      </label>
      <div className={styles.anchor}>
        <input
          autoComplete="off"
          spellCheck={false}
          {...rest}
          ref={inputRef}
          id={id}
          type="text"
          className={cx(fieldStyles.control, hasOptions && styles.withToggle)}
          value={value}
          disabled={disabled}
          role={hasOptions ? 'combobox' : undefined}
          aria-expanded={hasOptions ? isOpen : undefined}
          aria-controls={hasOptions ? listId : undefined}
          aria-autocomplete={hasOptions ? 'list' : undefined}
          aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          onChange={(event) => {
            const typed = event.target.value
            onValueChange(typed)
            if (!hasOptions) return
            if (!open) measure()
            setFilterText(typed)
            setActive(-1)
            setOpen(true)
          }}
          onClick={() => {
            if (!isOpen) openAll(-1)
          }}
          onKeyDown={onKeyDown}
          onBlur={close}
        />
        {hasOptions ? (
          <button
            type="button"
            tabIndex={-1}
            className={styles.toggle}
            aria-label={toggleLabel}
            aria-expanded={isOpen}
            aria-controls={listId}
            disabled={disabled}
            // Keeps the focus in the input, so the blur does not close the list first.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              if (isOpen) close()
              else openAll(-1)
              inputRef.current?.focus()
            }}
          >
            <ChevronDownIcon />
          </button>
        ) : null}
        {isOpen ? (
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            aria-label={listLabel}
            className={cx(styles.list, placement.up && styles.up)}
            style={style}
            onMouseDown={(event) => event.preventDefault()}
          >
            {shown.length === 0 ? (
              <li role="option" aria-selected={false} aria-disabled="true" className={styles.empty}>
                {emptyText}
              </li>
            ) : (
              shown.map((option, index) => (
                <li
                  key={option.value}
                  id={optionId(index)}
                  role="option"
                  aria-selected={option.value === current}
                  className={cx(styles.option, index === activeIndex && styles.active)}
                  onClick={() => choose(option)}
                >
                  <span className={styles.optionValue}>{option.value}</span>
                  {option.label ? (
                    <>
                      {' '}
                      <span className={styles.optionLabel}>{option.label}</span>
                    </>
                  ) : null}
                </li>
              ))
            )}
          </ul>
        ) : null}
      </div>
      {hint ? (
        <div id={hintId} className={fieldStyles.hint}>
          {hint}
        </div>
      ) : null}
      {error ? (
        <div id={errorId} className={fieldStyles.error}>
          {error}
        </div>
      ) : null}
    </div>
  )
}
