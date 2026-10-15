import { cx } from '../lib/cx'
import { PlayerBar } from '../player/PlayerBar'
import { usePlayer } from '../player/playerContext'
import { strings } from '../strings'
import { Notice } from '../ui/Notice'
import { useBackendStatus } from './backendStatus'
import { PAGES } from './pages'
import { hrefFor, useHashRoute } from './route'
import styles from './Shell.module.css'

function BackendIndicator() {
  const { state, health } = useBackendStatus()
  const text =
    state === 'online'
      ? strings.backend.online
      : state === 'offline'
        ? strings.backend.offline
        : strings.backend.checking
  const title = health ? strings.backend.onlineTitle(health.version, health.catalog.tracks) : undefined
  return (
    <div role="status" className={styles.status} title={title}>
      <span className={cx(styles.dot, styles[state])} aria-hidden="true" />
      <span>{text}</span>
    </div>
  )
}

function OfflineBanner() {
  const { state } = useBackendStatus()
  if (state !== 'offline') return null
  return (
    <Notice kind="error" title={strings.backend.offlineTitle} className={styles.banner}>
      {strings.backend.offlineBody} <code>{strings.backend.offlineCommand}</code>
    </Notice>
  )
}

/** Header with the tabs, the offline banner, the active page and the player bar. */
export function Shell() {
  const { page, subpath, params } = useHashRoute()
  const { current } = usePlayer()
  const active = PAGES.find((p) => p.id === page) ?? PAGES[0]
  const Page = active?.component

  return (
    <div className={styles.shell}>
      <a href="#main" className={styles.skip} onClick={(e) => {
        e.preventDefault()
        document.getElementById('main')?.focus()
      }}>
        {strings.app.skipToContent}
      </a>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <a href={hrefFor('search')} className={styles.brand}>
            {strings.app.name}
          </a>
          <nav aria-label={strings.app.mainNav} className={styles.nav}>
            {PAGES.map((p) => (
              <a
                key={p.id}
                href={hrefFor(p.id)}
                className={cx(styles.tab, p.id === page && styles.activeTab)}
                aria-current={p.id === page ? 'page' : undefined}
              >
                {p.label}
              </a>
            ))}
          </nav>
          <BackendIndicator />
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className={cx(styles.main, current && styles.withPlayer)}
      >
        <OfflineBanner />
        {Page ? <Page subpath={subpath} params={params} /> : null}
      </main>
      <PlayerBar />
    </div>
  )
}
