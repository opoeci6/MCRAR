import { labelStrings as t } from './strings'
import styles from './LabelPage.module.css'

/** The keyboard shortcuts of the labelling card, in a collapsible list. */
export function ShortcutsHelp() {
  return (
    <details className={styles.help}>
      <summary>{t.shortcuts.summary}</summary>
      <p className={styles.helpNote}>{t.shortcuts.note}</p>
      <dl className={styles.shortcuts}>
        {t.shortcuts.rows.map((row) => (
          <div key={row.keys} className={styles.shortcut}>
            <dt>
              <kbd className={styles.keys}>{row.keys}</kbd>
            </dt>
            <dd>{row.action}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}
