import { getVocab } from '../../api/endpoints'
import type { LabelPart } from '../../api/types'
import { useAsync } from '../../api/useAsync'
import { usePersistentState } from '../../app/usePersistentState'
import { PageHeader } from '../../ui/PageHeader'
import { Select } from '../../ui/Select'
import { TextInput } from '../../ui/TextInput'
import { ExportLink } from './ExportLink'
import { labelStrings as t } from './strings'
import { Workspace } from './Workspace'
import styles from './LabelPage.module.css'

const DEFAULT_NAME = 'owner'
const MAX_NAME_LENGTH = 40
const PARTS: readonly LabelPart[] = ['all', 'A', 'B']

export default function LabelPage() {
  const [name, setName] = usePersistentState('label.name', DEFAULT_NAME)
  const [storedPart, setPart] = usePersistentState<LabelPart>('label.part', 'all')
  const part = PARTS.includes(storedPart) ? storedPart : 'all'
  // Nothing is requested while the name is not valid.
  const trimmed = name.trim()
  const labeller = trimmed.length >= 1 && trimmed.length <= MAX_NAME_LENGTH ? trimmed : null
  const vocab = useAsync((signal) => getVocab({ signal }), [])

  return (
    <div className={styles.page}>
      <PageHeader
        title={t.title}
        description={t.description}
        actions={labeller === null ? null : <ExportLink labeller={labeller} />}
      />

      <div className={styles.who}>
        <TextInput
          className={styles.name}
          label={t.who.name}
          hint={t.who.nameHint}
          error={labeller === null ? t.who.nameInvalid : undefined}
          value={name}
          autoComplete="off"
          onChange={(event) => setName(event.target.value)}
        />
        <Select
          className={styles.part}
          label={t.who.part}
          value={part}
          onChange={(event) => setPart(event.target.value as LabelPart)}
        >
          {PARTS.map((value) => (
            <option key={value} value={value}>
              {t.who.partOptions[value]}
            </option>
          ))}
        </Select>
      </div>

      {labeller === null ? null : <Workspace key={`${labeller}\n${part}`} labeller={labeller} part={part} vocab={vocab} />}
    </div>
  )
}
