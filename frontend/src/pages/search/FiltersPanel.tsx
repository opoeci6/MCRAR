import { useId, useState } from 'react'
import type { Vocab, VocabLabel } from '../../api/types'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Select } from '../../ui/Select'
import type { SelectOption } from '../../ui/Select'
import { TextInput } from '../../ui/TextInput'
import { Toggle } from '../../ui/Toggle'
import { DEFAULT_FILTERS, filterProblem } from './filters'
import type { DurationPreset, FilterState } from './filters'
import { searchStrings } from './strings'
import styles from './FiltersPanel.module.css'

const f = searchStrings.filters

/** Moods are a long list: this many show before "Show all". */
const MOODS_SHOWN = 12

export interface FiltersPanelProps {
  value: FilterState
  onChange: (next: FilterState) => void
  /** `undefined` while it loads or after it failed. */
  vocab: Vocab | undefined
  vocabFailed: boolean
}

function optionList(options: Record<string, string>): SelectOption[] {
  return Object.entries(options).map(([value, label]) => ({ value, label }))
}

function toggled(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id]
}

/** All the search filters. Edits are applied at once to the form; they take effect on Search. */
export function FiltersPanel({ value, onChange, vocab, vocabFailed }: FiltersPanelProps) {
  const set = (patch: Partial<FilterState>) => onChange({ ...value, ...patch })
  const problem = filterProblem(value)
  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <h2 className={styles.heading}>{f.heading}</h2>
        <Button size="sm" variant="ghost" onClick={() => onChange(DEFAULT_FILTERS)}>
          {f.clear}
        </Button>
      </div>

      <Toggle
        label={f.safeLabel}
        hint={f.safeHint}
        checked={value.safeOnly}
        onChange={(safeOnly) => set({ safeOnly })}
      />
      {value.safeOnly ? null : (
        <Select
          label={f.maxRisk}
          value={value.maxRisk}
          options={optionList(f.risk)}
          onValueChange={(next) => set({ maxRisk: next as FilterState['maxRisk'] })}
        />
      )}

      {vocabFailed ? <Notice kind="warning">{f.vocabFailed}</Notice> : null}
      <ChipGroup
        label={f.genres}
        labels={vocab?.genre ?? []}
        selected={value.genres}
        onToggle={(id) => set({ genres: toggled(value.genres, id) })}
      />
      <ChipGroup
        label={f.moods}
        labels={vocab?.moodtheme ?? []}
        selected={value.moods}
        limit={MOODS_SHOWN}
        onToggle={(id) => set({ moods: toggled(value.moods, id) })}
      />
      <ChipGroup
        label={f.scenes}
        labels={vocab?.scene ?? []}
        selected={value.scenes}
        onToggle={(id) => set({ scenes: toggled(value.scenes, id) })}
      />
      <Select
        label={f.intensity}
        hint={f.intensityHint}
        value={value.intensity}
        options={optionList(f.intensityOptions)}
        onValueChange={(next) => set({ intensity: next as FilterState['intensity'] })}
      />

      <fieldset className={styles.group}>
        <legend className={styles.legend}>{f.bpm}</legend>
        <div className={styles.pair}>
          <TextInput
            label={f.bpmMin}
            type="number"
            inputMode="numeric"
            min={0}
            value={value.bpmMin}
            onChange={(event) => set({ bpmMin: event.target.value })}
          />
          <TextInput
            label={f.bpmMax}
            type="number"
            inputMode="numeric"
            min={0}
            value={value.bpmMax}
            onChange={(event) => set({ bpmMax: event.target.value })}
          />
        </div>
      </fieldset>

      <Select
        label={f.vocals}
        value={value.vocal}
        options={optionList(f.vocalOptions)}
        onValueChange={(next) => set({ vocal: next as FilterState['vocal'] })}
      />

      <Select
        label={f.duration}
        value={value.duration}
        options={optionList(f.durationOptions)}
        onValueChange={(next) => set({ duration: next as DurationPreset })}
      />
      {value.duration === 'custom' ? (
        <div className={styles.pair}>
          <TextInput
            label={f.durationMin}
            type="number"
            inputMode="numeric"
            min={0}
            value={value.durationMin}
            onChange={(event) => set({ durationMin: event.target.value })}
          />
          <TextInput
            label={f.durationMax}
            type="number"
            inputMode="numeric"
            min={0}
            value={value.durationMax}
            onChange={(event) => set({ durationMax: event.target.value })}
          />
        </div>
      ) : null}

      <Select
        label={f.source}
        value={value.source}
        options={optionList(f.sourceOptions)}
        onValueChange={(next) => set({ source: next as FilterState['source'] })}
      />

      {problem ? <Notice kind="error">{problem}</Notice> : null}
    </div>
  )
}

interface ChipGroupProps {
  label: string
  labels: VocabLabel[]
  selected: string[]
  /** Show only this many (plus any selected) until "Show all". */
  limit?: number
  onToggle: (id: string) => void
}

function ChipGroup({ label, labels, selected, limit, onToggle }: ChipGroupProps) {
  const [all, setAll] = useState(false)
  const headingId = useId()
  if (labels.length === 0) return null
  const collapsible = limit !== undefined && labels.length > limit
  const shown =
    collapsible && !all
      ? labels.filter((item, index) => index < limit || selected.includes(item.id))
      : labels
  return (
    <div className={styles.group}>
      <div id={headingId} className={styles.legend}>
        {label}
      </div>
      <div role="group" aria-labelledby={headingId} className={styles.chips}>
        {shown.map((item) => (
          <Chip key={item.id} selected={selected.includes(item.id)} onChange={() => onToggle(item.id)}>
            {item.display}
          </Chip>
        ))}
      </div>
      {collapsible ? (
        <div>
          <Button size="sm" variant="ghost" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? f.showFewer : f.showAll(labels.length)}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
