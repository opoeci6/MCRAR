import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { cx } from '../lib/cx'
import fieldStyles from './Field.module.css'
import listStyles from './Combobox.module.css'
import styles from './Select.module.css'
import { CheckIcon, ChevronDownIcon } from './icons'
import { DEFAULT_PLACEMENT, measurePlacement } from './popupPlacement'
import type { Placement } from './popupPlacement'

export interface SelectOption {
  value: string
  /** The text shown, in the closed control and in the list. */
  label: string
  disabled?: boolean
}

export interface SelectProps {
  /** The visible label (always required for a name). */
  label: string
  /** Hide the label visually; it stays the accessible name. */
  hideLabel?: boolean
  hint?: ReactNode
  options: SelectOption[]
  value: string
  onValueChange: (value: string) => void
  disabled?: boolean
  className?: string
  /** The id of the control that opens the list. */
  id?: string
}

/** How far PageUp and PageDown move. */
const PAGE_STEP = 10
/** Typed characters count as one prefix when they follow each other within this time. */
const TYPE_AHEAD_MS = 500

/**
 * A drop-in for a native `<select>` whose list is drawn in the page (a native list is a popup
 * widget that some embedded browsers place far from its control). ARIA 1.2 select-only combobox
 * with a listbox popup: the closed control is a focusable button showing the chosen label.
 */
export function Select({
  label,
  hideLabel,
  hint,
  options,
  value,
  onValueChange,
  disabled,
  className,
  id: givenId,
}: SelectProps) {
  const generated = useId()
  const id = givenId ?? generated
  const labelId = `${id}-label`
  const hintId = `${id}-hint`
  const listId = `${id}-list`
  const optionId = (index: number) => `${id}-option-${index}`

  const triggerRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const typed = useRef({ text: '', at: 0 })
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [placement, setPlacement] = useState<Placement>(DEFAULT_PLACEMENT)

  const isOpen = open && !disabled
  const selectedIndex = options.findIndex((o) => o.value === value)
  const activeIndex = isOpen && active >= 0 && active < options.length ? active : -1

  useEffect(() => {
    if (activeIndex < 0) return
    const element = listRef.current?.children[activeIndex] as HTMLElement | undefined
    element?.scrollIntoView?.({ block: 'nearest' })
  }, [activeIndex])

  /** The nearest enabled option from `from` (exclusive) in a direction, or -1; no wrapping. */
  const enabledFrom = (from: number, direction: 1 | -1): number => {
    for (let i = from + direction; i >= 0 && i < options.length; i += direction) {
      if (!options[i]!.disabled) return i
    }
    return -1
  }
  const firstEnabled = () => enabledFrom(-1, 1)
  const lastEnabled = () => enabledFrom(options.length, -1)

  /** Moves `steps` enabled options from `from`, stopping at the ends. */
  const move = (from: number, direction: 1 | -1, steps: number): number => {
    let index = from
    for (let n = 0; n < steps; n += 1) {
      const next = enabledFrom(index, direction)
      if (next < 0) break
      index = next
    }
    return index
  }

  /** The option a type-ahead character selects, or -1. */
  const typeAheadTarget = (char: string, from: number): number => {
    const now = Date.now()
    const previous = typed.current
    const text = (now - previous.at > TYPE_AHEAD_MS ? '' : previous.text) + char.toLowerCase()
    typed.current = { text, at: now }
    // One repeated letter cycles through the options starting with it.
    const cycling = [...text].every((c) => c === text[0])
    const needle = cycling ? text[0]! : text
    const begin = cycling ? from + 1 : Math.max(from, 0)
    for (let n = 0; n < options.length; n += 1) {
      const index = (((begin + n) % options.length) + options.length) % options.length
      const option = options[index]!
      if (!option.disabled && option.label.toLowerCase().startsWith(needle)) return index
    }
    return -1
  }

  const openList = (index: number) => {
    if (disabled || options.length === 0) return
    if (!open && triggerRef.current) setPlacement(measurePlacement(triggerRef.current))
    setActive(index >= 0 ? index : firstEnabled())
    setOpen(true)
  }

  const close = () => {
    setOpen(false)
    setActive(-1)
  }

  const choose = (index: number) => {
    const option = options[index]
    if (!option || option.disabled) return
    if (option.value !== value) onValueChange(option.value)
    close()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return
    const current = selectedIndex
    const isChar = event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey
    // A space continues a prefix being typed; on its own it opens or chooses.
    const typing = isChar && (event.key !== ' ' || (typed.current.text !== '' && Date.now() - typed.current.at <= TYPE_AHEAD_MS))

    if (typing) {
      event.preventDefault()
      const target = typeAheadTarget(event.key, isOpen ? activeIndex : current)
      if (target < 0) return
      if (isOpen) setActive(target)
      else if (options[target]!.value !== value) onValueChange(options[target]!.value)
      return
    }

    if (!isOpen) {
      switch (event.key) {
        case 'Enter':
        case ' ':
          event.preventDefault()
          openList(current)
          break
        case 'ArrowDown':
        case 'ArrowUp':
          event.preventDefault()
          openList(current)
          break
        case 'Home':
          event.preventDefault()
          openList(firstEnabled())
          break
        case 'End':
          event.preventDefault()
          openList(lastEnabled())
          break
      }
      return
    }

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        setActive(activeIndex < 0 ? firstEnabled() : move(activeIndex, 1, 1))
        break
      case 'ArrowUp':
        event.preventDefault()
        // Alt+ArrowUp chooses the active option and closes, as in the ARIA pattern.
        if (event.altKey) choose(activeIndex)
        else setActive(activeIndex < 0 ? lastEnabled() : move(activeIndex, -1, 1))
        break
      case 'PageDown':
        event.preventDefault()
        setActive(activeIndex < 0 ? firstEnabled() : move(activeIndex, 1, PAGE_STEP))
        break
      case 'PageUp':
        event.preventDefault()
        setActive(activeIndex < 0 ? lastEnabled() : move(activeIndex, -1, PAGE_STEP))
        break
      case 'Home':
        event.preventDefault()
        setActive(firstEnabled())
        break
      case 'End':
        event.preventDefault()
        setActive(lastEnabled())
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        if (activeIndex >= 0) choose(activeIndex)
        else close()
        break
      case 'Escape':
        // Closes the list only: a Drawer or dialog around the select must stay open.
        event.preventDefault()
        event.stopPropagation()
        close()
        break
      case 'Tab':
        // Chooses the active option and lets the focus move on.
        if (activeIndex >= 0) choose(activeIndex)
        else close()
        break
    }
  }

  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined

  return (
    <div className={cx(fieldStyles.field, className)}>
      <label
        id={labelId}
        className={hideLabel ? 'sr-only' : fieldStyles.label}
        // Not htmlFor: a button would open the list on a label click; this only moves the focus.
        onClick={() => triggerRef.current?.focus()}
      >
        {label}
      </label>
      <div className={listStyles.anchor}>
        <button
          ref={triggerRef}
          id={id}
          type="button"
          role="combobox"
          className={cx(fieldStyles.control, styles.trigger)}
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={isOpen}
          aria-controls={listId}
          aria-labelledby={labelId}
          aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
          aria-describedby={hint ? hintId : undefined}
          onClick={() => {
            triggerRef.current?.focus()
            if (isOpen) close()
            else openList(selectedIndex)
          }}
          onKeyDown={onKeyDown}
          // A space is a click on key-up in some browsers; the key-down already handled it.
          onKeyUp={(event) => {
            if (event.key === ' ') event.preventDefault()
          }}
          onBlur={close}
        >
          <span className={styles.value}>{selected?.label}</span>
          <ChevronDownIcon className={styles.chevron} />
        </button>
        {isOpen ? (
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            aria-labelledby={labelId}
            className={cx(listStyles.list, placement.up && listStyles.up)}
            style={{ maxHeight: placement.maxHeight }}
            // Keeps the focus on the trigger, so the blur does not close the list first.
            onMouseDown={(event) => event.preventDefault()}
          >
            {options.map((option, index) => (
              <li
                key={option.value}
                id={optionId(index)}
                role="option"
                aria-selected={index === selectedIndex}
                aria-disabled={option.disabled ? true : undefined}
                className={cx(listStyles.option, styles.item, index === activeIndex && listStyles.active)}
                onClick={() => choose(index)}
              >
                <span>{option.label}</span>
                {index === selectedIndex ? <CheckIcon className={styles.check} /> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {hint ? (
        <div id={hintId} className={fieldStyles.hint}>
          {hint}
        </div>
      ) : null}
    </div>
  )
}
