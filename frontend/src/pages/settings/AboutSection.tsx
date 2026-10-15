import type { SettingsView } from '../../api'
import { useBackendStatus } from '../../app/backendStatus'
import { settingsStrings as t } from './strings'
import styles from './Section.module.css'

/** Read-only facts about this installation. */
export function AboutSection({ view }: { view: SettingsView }) {
  const { health } = useBackendStatus()
  const fixed = view.read_only
  const text = (name: string) => (fixed[name] === undefined ? t.about.unknown : String(fixed[name]))
  const rows: [string, string][] = [
    [t.about.version, health?.version ?? t.about.unknown],
    [t.about.api, `${text('api_host')}:${text('api_port')}`],
    [t.about.home, text('home')],
    [t.about.dataDir, text('data_dir')],
    [t.about.modelsDir, text('models_dir')],
    [t.about.cacheDir, text('cache_dir')],
    [t.about.secretsDir, text('secrets_dir')],
    [t.about.secretsBackend, text('secrets_backend')],
  ]
  return (
    <section className={styles.section} aria-labelledby="settings-about-heading">
      <h2 id="settings-about-heading">{t.about.heading}</h2>
      <dl className={styles.facts}>
        {rows.map(([label, value]) => (
          <div key={label} className={styles.fact}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
