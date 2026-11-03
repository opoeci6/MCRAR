import type { ReactNode } from 'react'
import { Combobox } from '../../ui/Combobox'
import { trackFeatureStrings as t } from './strings'

export interface LicenseInputProps {
  value: string
  onChange: (value: string) => void
  label: string
  hint?: ReactNode
  autoFocus?: boolean
  maxLength?: number
}

/**
 * A licence text box that suggests the usual codes while you type (any text can still be typed).
 * The list is drawn in the page: a native datalist popup is misplaced in embedded browsers.
 */
export function LicenseInput({ value, onChange, label, hint, autoFocus, maxLength }: LicenseInputProps) {
  return (
    <Combobox
      label={label}
      hint={hint}
      value={value}
      options={t.licenceSuggestions}
      onValueChange={onChange}
      listLabel={t.licenceList.list}
      toggleLabel={t.licenceList.toggle}
      emptyText={t.licenceList.empty}
      maxLength={maxLength}
      autoFocus={autoFocus}
    />
  )
}
