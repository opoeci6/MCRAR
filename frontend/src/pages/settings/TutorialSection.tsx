import { useTour } from '../../features/tour/tourContext'
import { Button } from '../../ui/Button'
import { settingsStrings as t } from './strings'
import styles from './Section.module.css'

/** Starts the first-run tour again. */
export function TutorialSection() {
  const { start } = useTour()
  return (
    <section className={styles.section} aria-labelledby="settings-tutorial-heading" data-tour="settings-tutorial">
      <h2 id="settings-tutorial-heading">{t.tutorial.heading}</h2>
      <p className={styles.explain}>{t.tutorial.hint}</p>
      <div className={styles.actions}>
        {/* The id lets the tour put focus back here: the page is rebuilt while the tour visits other tabs. */}
        <Button id="settings-tutorial-start" onClick={start}>
          {t.tutorial.start}
        </Button>
      </div>
    </section>
  )
}
