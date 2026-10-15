/** `search.pool_size` is set by `MCRAR_SEARCH__POOL_SIZE`. */
export function envVarName(dotted: string): string {
  return `MCRAR_${dotted.toUpperCase().split('.').join('__')}`
}
