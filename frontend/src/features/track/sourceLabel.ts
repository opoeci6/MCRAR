import { trackFeatureStrings } from './strings'

const names = trackFeatureStrings.sourceNames

/** The display name of a track source (`jamendo` is "Jamendo"); an unknown source shows as it is. */
export function sourceLabel(source: string): string {
  return Object.hasOwn(names, source) ? names[source]! : source
}
