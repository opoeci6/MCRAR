import { CopyFilesCard } from './CopyFilesCard'
import { FolderCard } from './FolderCard'
import type { StartProps } from './startJob'
import { libraryStrings as t } from './strings'
import styles from './Forms.module.css'

/** The "Your files" tab: two ways to add music that is on this computer. */
export function LocalForm(props: StartProps) {
  return (
    <div className={styles.form}>
      <p className={styles.intro}>{t.local.intro}</p>
      <CopyFilesCard {...props} />
      <FolderCard {...props} />
    </div>
  )
}
