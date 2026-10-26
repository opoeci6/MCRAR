import { useEffect, useRef, useState } from 'react'
import type { Intensity, VocabLabel } from '../../api/types'
import { usePlayer } from '../../player/playerContext'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { handleShortcut, INTENSITY_KEYS, NONE_KEY, releaseFocus, SCENE_KEYS } from './shortcuts'
import type { ShortcutActions } from './shortcuts'
import { labelStrings as t } from './strings'
import { TrackPlayback } from './TrackPlayback'
import type { LabelValues, Slot } from './useLabelQueue'
import styles from './LabelCard.module.css'

const KEY_FOR_INTENSITY = Object.fromEntries(Object.entries(INTENSITY_KEYS).map(([key, value]) => [value, key]))

export interface LabelCardProps {
  slot: Slot
  /** The scenes to choose from, in the order of the vocabulary. */
  scenes: VocabLabel[]
  /** "Track 12 of 150"; `null` until the pool list is loaded. */
  index: { current: number; total: number } | null
  busy: boolean
  /** Why the last move failed; the form stays as it was. */
  error: string | null
  /** Whether there is an earlier track in the list to go back to. */
  canGoBack: boolean
  onSave: (values: LabelValues) => void
  onSkip: () => void
  onBack: () => void
  onDelete: () => void
}

/**
 * The form for one track: scenes (any number, or "None of these"), the intensity, and the moves.
 * Shows nothing about why the track is in the pool. The parent keys it by track, so the form
 * starts from the stored label each time a track is shown.
 */
export function LabelCard({ slot, scenes, index, busy, error, canGoBack, onSave, onSkip, onBack, onDelete }: LabelCardProps) {
  const player = usePlayer()
  const { label } = slot
  const labelled = label?.status === 'labelled' ? label : null
  const [selected, setSelected] = useState<string[]>(labelled?.scenes ?? [])
  const [none, setNone] = useState(labelled !== null && labelled.scenes.length === 0)
  const [intensity, setIntensity] = useState<Intensity | null>(labelled?.intensity ?? null)

  const canSave = (selected.length > 0 || none) && !busy

  const toggleScene = (id: string) => {
    setNone(false)
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))
  }
  const toggleNone = () => {
    setSelected([])
    setNone(!none)
  }
  const toggleIntensity = (value: Intensity) => setIntensity((current) => (current === value ? null : value))

  const save = () => {
    if (!canSave) return
    // In vocabulary order, whatever order they were ticked in.
    onSave({ scenes: scenes.filter((scene) => selected.includes(scene.id)).map((scene) => scene.id), intensity })
  }
  const skip = () => {
    if (!busy) onSkip()
  }
  const back = () => {
    if (!busy && canGoBack) onBack()
  }

  const actions: ShortcutActions = {
    toggleScene: (position) => {
      const scene = scenes[position]
      if (scene && !busy) toggleScene(scene.id)
    },
    toggleNone: () => !busy && toggleNone(),
    toggleIntensity: (value) => !busy && toggleIntensity(value),
    save,
    skip,
    back,
    playPause: () => player.play(slot.track),
  }
  // The listener is added once and reads the latest actions, so it never acts on old state.
  const latest = useRef(actions)
  useEffect(() => {
    latest.current = actions
  })
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => handleShortcut(event, latest.current)
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    // The click handler only lets go of the focus; every control has its own onClick.
    <div className={styles.card} onClick={releaseFocus}>
      <div className={styles.head}>
        {index ? <span className={styles.position}>{t.card.position(index.current, index.total)}</span> : <span />}
        {label ? (
          <span className={styles.saved}>{label.status === 'skipped' ? t.card.savedSkipped : t.card.saved}</span>
        ) : null}
      </div>

      <TrackPlayback track={slot.track} />

      <fieldset className={styles.group} disabled={busy}>
        <legend className={styles.legend}>{t.form.scenes}</legend>
        <div className={styles.chips}>
          {scenes.map((scene, position) => (
            <Chip
              key={scene.id}
              selected={selected.includes(scene.id)}
              title={t.sceneHelp[scene.id]}
              onChange={() => toggleScene(scene.id)}
            >
              <KeyHint>{SCENE_KEYS[position]}</KeyHint>
              {scene.display}
            </Chip>
          ))}
          <Chip selected={none} title={t.form.noneTitle} onChange={toggleNone}>
            <KeyHint>{NONE_KEY}</KeyHint>
            {t.form.none}
          </Chip>
        </div>
      </fieldset>

      <fieldset className={styles.group} disabled={busy}>
        <legend className={styles.legend}>
          {t.form.intensity} <span className={styles.optional}>{t.form.intensityHint}</span>
        </legend>
        <div className={styles.chips}>
          {t.form.intensityOptions.map((option) => (
            <Chip
              key={option.value}
              selected={intensity === option.value}
              title={option.title}
              onChange={() => toggleIntensity(option.value)}
            >
              <KeyHint>{KEY_FOR_INTENSITY[option.value]}</KeyHint>
              {option.label}
            </Chip>
          ))}
        </div>
      </fieldset>

      {error ? <Notice kind="error">{error}</Notice> : null}

      <div className={styles.actions}>
        <Button disabled={busy || !canGoBack} title={t.form.backTitle} onClick={back}>
          {t.form.back}
        </Button>
        <Button disabled={busy} title={t.form.skipTitle} onClick={skip}>
          {t.form.skip}
        </Button>
        {label ? (
          <Button variant="ghost" disabled={busy} onClick={onDelete}>
            {t.card.deleteLabel}
          </Button>
        ) : null}
        <Button className={styles.save} variant="primary" disabled={!canSave} onClick={save}>
          {busy ? t.form.saving : t.form.saveAndNext}
        </Button>
      </div>
    </div>
  )
}

/** The key of a shortcut, as a small hint on its chip (the shortcut list says the same). */
function KeyHint({ children }: { children?: string }) {
  return children ? (
    <kbd className={styles.key} aria-hidden="true">
      {children.toUpperCase()}
    </kbd>
  ) : null
}
