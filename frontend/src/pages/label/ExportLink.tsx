import { labelsExportUrl } from '../../api/endpoints'
import { labelStrings as t } from './strings'
import styles from './LabelPage.module.css'

/** Downloads the labeller's labels file, the one `mcrar scenes import-labels` reads. */
export function ExportLink({ labeller }: { labeller: string }) {
  return (
    <a className={styles.export} href={labelsExportUrl(labeller)} download>
      {t.exportLabels}
    </a>
  )
}
