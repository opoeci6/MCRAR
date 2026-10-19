import { SecretField } from './SecretField'
import { settingsStrings as t } from './strings'
import styles from './Section.module.css'

const JAMENDO = 'jamendo_client_id'

/** The API keys that are not tied to a setting (today: the Jamendo client id). */
export function SecretsSection() {
  return (
    <section className={styles.section} aria-labelledby="settings-secrets-heading">
      <h2 id="settings-secrets-heading">{t.secrets.heading}</h2>
      <SecretField
        name={JAMENDO}
        title={t.secrets.jamendoTitle}
        body={t.secrets.jamendoBody}
        link={{ href: 'https://devportal.jamendo.com', label: t.secrets.jamendoLink }}
        inputLabel={t.secrets.jamendoInput}
        removeWarning={t.secrets.jamendoRemoveWarning}
      />
    </section>
  )
}
