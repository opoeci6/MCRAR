import type { ReactNode } from 'react'
import { LicenseInput } from '../../features/track/LicenseInput'
import { Checkbox } from '../../ui/Toggle'
import { libraryStrings as t } from './strings'

export interface LicenseEmbedFieldsProps {
  license: string
  onLicense: (value: string) => void
  embed: boolean
  onEmbed: (value: boolean) => void
  licenseHint: ReactNode
}

/** The licence and "also embed" choices that both ways of adding your own files have. */
export function LicenseEmbedFields({
  license,
  onLicense,
  embed,
  onEmbed,
  licenseHint,
}: LicenseEmbedFieldsProps) {
  return (
    <>
      <LicenseInput label={t.local.license} hint={licenseHint} value={license} onChange={onLicense} />
      <Checkbox label={t.local.embed} hint={t.local.embedHint} checked={embed} onChange={onEmbed} />
    </>
  )
}
