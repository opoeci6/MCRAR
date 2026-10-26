import type { MouseEvent } from 'react'
import type { Intensity } from '../../api/types'

/** The keys of the scenes, in the order of the vocabulary: 1-9, 0, then q w e r. */
export const SCENE_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'q', 'w', 'e', 'r']

export const NONE_KEY = 'n'

export const INTENSITY_KEYS: Record<string, Intensity> = { a: 'low', s: 'mid', d: 'high' }

/** What a key press can do. The labelling card fills it in with its current state. */
export interface ShortcutActions {
  toggleScene: (index: number) => void
  toggleNone: () => void
  toggleIntensity: (intensity: Intensity) => void
  save: () => void
  skip: () => void
  back: () => void
  playPause: () => void
}

const NON_TEXT_INPUTS = ['button', 'checkbox', 'color', 'file', 'image', 'radio', 'range', 'reset', 'submit']

/** Typing in a field must never trigger a shortcut. */
function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  if (target instanceof HTMLInputElement) return !NON_TEXT_INPUTS.includes(target.type)
  return target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement
}

/** Enter and Space already press a focused button or link: leave them to it. */
function activatesOnKey(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest('button, a[href], summary, [role="button"]') !== null
}

/**
 * For a container's `onClick`: a mouse click leaves the focus on its button, where Enter and
 * Space would press it again instead of saving or playing. A key press (`detail` 0) keeps it.
 */
export function releaseFocus(event: MouseEvent<HTMLElement>): void {
  const button = event.target instanceof HTMLElement ? event.target.closest('button') : null
  if (event.detail > 0 && button) button.blur()
}

/**
 * Runs the shortcut of a `keydown`, if it is one. Letters and digits work wherever the focus is
 * (outside a text field); Enter and Space only when the focus is not on a control that they would
 * press anyway, so a key never does two things.
 */
export function handleShortcut(event: KeyboardEvent, actions: ShortcutActions): void {
  if (event.defaultPrevented || event.repeat) return
  if (event.ctrlKey || event.metaKey || event.altKey) return
  if (isTextEntry(event.target)) return

  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key
  const run = (action: () => void) => {
    event.preventDefault()
    action()
  }

  const scene = SCENE_KEYS.indexOf(key)
  if (scene >= 0) return run(() => actions.toggleScene(scene))
  const intensity = INTENSITY_KEYS[key]
  if (intensity) return run(() => actions.toggleIntensity(intensity))
  if (key === NONE_KEY) return run(actions.toggleNone)
  if (key === 'k') return run(actions.skip)
  if (key === 'b') return run(actions.back)
  if (activatesOnKey(event.target)) return
  if (key === 'Enter') return run(actions.save)
  if (key === ' ') return run(actions.playPause)
}
