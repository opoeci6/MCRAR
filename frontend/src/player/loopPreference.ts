/*
 * Whether the player repeats the track, kept in localStorage so it survives a reload.
 * Any storage failure just means the default (off) and a choice that is not remembered.
 */
const KEY = 'mcrar.player.loop'

export function readLoop(): boolean {
  try {
    return window.localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function writeLoop(loop: boolean): void {
  try {
    window.localStorage.setItem(KEY, loop ? '1' : '0')
  } catch {
    // Storage is unavailable (private mode, quota): the choice just is not remembered.
  }
}
