import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { setTrackLicense } from '../../api/endpoints'
import type { TrackDetail } from '../../api/types'
import { errorMessage } from '../../api/useAsync'
import { useToast } from '../../app/toastContext'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { LicenseInput } from './LicenseInput'
import { trackFeatureStrings as t } from './strings'
import styles from './TrackDrawer.module.css'

const e = t.licence.edit

/** What the box starts with: the current code, or nothing while the licence is unknown. */
function startingValue(track: TrackDetail): string {
  const { license } = track
  if (license.family === 'unknown' || license.risk === 'unknown') return ''
  return license.code ?? ''
}

export interface EditLicenseProps {
  track: TrackDetail
  /** Called with the track as the backend now has it, after the licence was saved. */
  onSaved: (track: TrackDetail) => void
}

/** "Edit licence" for a local track: a button that opens a small inline form. */
export function EditLicense({ track, onSaved }: EditLicenseProps) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const wasEditing = useRef(false)

  // Back on the button after the form closes, so a keyboard user does not lose their place.
  useEffect(() => {
    if (wasEditing.current && !editing) button.current?.focus()
    wasEditing.current = editing
  }, [editing])

  const open = () => {
    setValue(startingValue(track))
    setProblem(null)
    setEditing(true)
  }

  const close = () => {
    setEditing(false)
    setProblem(null)
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    const wanted = value.trim()
    if (!wanted || saving) return
    setSaving(true)
    setProblem(null)
    try {
      const updated = await setTrackLicense(track.id, wanted)
      toast.info(e.saved(updated.license.code ?? updated.license_code ?? strings.common.unknown))
      setEditing(false)
      onSaved(updated)
    } catch (caught) {
      setProblem(errorMessage(caught))
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <Button ref={button} size="sm" variant="ghost" onClick={open}>
        {e.action}
      </Button>
    )
  }
  return (
    <form
      className={styles.editLicense}
      aria-label={e.group}
      onSubmit={(event) => void save(event)}
      onKeyDown={(event) => {
        // Escape leaves the form, not the drawer.
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          close()
        }
      }}
    >
      <LicenseInput
        label={e.label}
        hint={e.hint}
        value={value}
        onChange={setValue}
        maxLength={200}
        autoFocus
      />
      {problem ? (
        <Notice kind="error" title={e.failed}>
          {problem}
        </Notice>
      ) : null}
      <div className={styles.editLicenseActions}>
        <Button type="submit" size="sm" variant="primary" disabled={saving || !value.trim()}>
          {t.licence.edit.save}
        </Button>
        <Button size="sm" variant="ghost" disabled={saving} onClick={close}>
          {t.licence.edit.cancel}
        </Button>
      </div>
    </form>
  )
}
