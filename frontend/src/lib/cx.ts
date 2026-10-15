/** Joins class names, skipping falsy entries. */
export function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(' ')
}
