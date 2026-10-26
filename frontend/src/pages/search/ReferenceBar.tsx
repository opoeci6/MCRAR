import { useEffect, useId, useRef, useState } from 'react'
import type { ChangeEvent, Ref } from 'react'
import { Button, IconButton } from '../../ui/Button'
import { CloseIcon } from '../../ui/icons'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { AUDIO_ACCEPT } from './reference'
import type { Reference } from './reference'
import { searchStrings } from './strings'
import styles from './ReferenceBar.module.css'

const r = searchStrings.reference

/** How long the slider rests before the search runs again, so a drag is not a search per step. */
const SLIDER_DELAY_MS = 400

export interface ReferenceBarProps {
  reference: Reference | null
  uploading: boolean
  /** Why the last upload failed or the reference stopped working. */
  problem: { title: string; message: string } | null
  onUpload: (file: File) => void
  onRemove: () => void
  /** Where "Find similar" puts the focus: the chip. */
  chipRef: Ref<HTMLSpanElement>
  /** The query has both a text and a reference, so the slider that balances them is shown. */
  mixed: boolean
  /** The reference's share, 0 to 1. */
  weight: number
  onWeight: (weight: number) => void
}

/** The "Sounds like" row under the query box: upload a song, the chip of the one in use, the slider. */
export function ReferenceBar({
  reference,
  uploading,
  problem,
  onUpload,
  onRemove,
  chipRef,
  mixed,
  weight,
  onWeight,
}: ReferenceBarProps) {
  const fileInput = useRef<HTMLInputElement>(null)
  const sliderId = useId()
  // The value under the thumb while it moves; `null` when the shown weight is the committed one.
  const [pending, setPending] = useState<number | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const percent = pending ?? Math.round(weight * 100)

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    // So that choosing the same file again still counts as a change.
    event.target.value = ''
    if (file) onUpload(file)
  }

  const onSlide = (event: ChangeEvent<HTMLInputElement>) => {
    const next = Number(event.target.value)
    setPending(next)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      timer.current = null
      setPending(null)
      onWeight(next / 100)
    }, SLIDER_DELAY_MS)
  }

  return (
    <div className={styles.bar} role="group" aria-label={r.group}>
      <div className={styles.row}>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept={AUDIO_ACCEPT}
          onChange={onFile}
        />
        {reference ? (
          <span className={styles.chip}>
            <span ref={chipRef} tabIndex={-1} className={styles.chipLabel}>
              {r.chip(reference.label)}
            </span>
            <IconButton size="sm" label={r.remove} onClick={onRemove}>
              <CloseIcon width={12} height={12} />
            </IconButton>
          </span>
        ) : uploading ? (
          <Spinner label={r.uploading} />
        ) : (
          <>
            <Button size="sm" onClick={() => fileInput.current?.click()}>
              {r.upload}
            </Button>
            <span className={styles.hint}>{r.uploadHint}</span>
          </>
        )}
      </div>

      {mixed ? (
        <div className={styles.slider}>
          <label htmlFor={sliderId} className={styles.sliderLabel}>
            {r.weight}
          </label>
          <div className={styles.sliderRow}>
            <span className={styles.end} aria-hidden="true">
              {r.weightText}
            </span>
            <input
              id={sliderId}
              type="range"
              className={styles.range}
              min={0}
              max={100}
              step={5}
              value={percent}
              aria-valuetext={r.weightValue(percent)}
              onChange={onSlide}
            />
            <span className={styles.end} aria-hidden="true">
              {r.weightReference}
            </span>
          </div>
        </div>
      ) : null}

      {problem ? (
        <Notice kind="error" title={problem.title}>
          {problem.message}
        </Notice>
      ) : null}
    </div>
  )
}
