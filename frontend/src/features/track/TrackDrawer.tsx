import { getTrack } from '../../api/endpoints'
import { errorMessage, useAsync } from '../../api/useAsync'
import { AddToProjectMenu } from '../projects/AddToProjectMenu'
import { Drawer } from '../../ui/Drawer'
import { LicenseBadge } from '../../ui/LicenseBadge'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { trackFeatureStrings as t } from './strings'
import styles from './TrackDrawer.module.css'

export interface TrackDrawerProps {
  /** The track to show, or `null` to keep the drawer closed. */
  trackId: number | null
  onClose: () => void
}

/**
 * The side panel with a track's details. Placeholder: the track slice replaces the body (keep the
 * props). It shows the title, artist and licence so the contract can be used already.
 */
export function TrackDrawer({ trackId, onClose }: TrackDrawerProps) {
  return (
    <Drawer open={trackId !== null} onClose={onClose} title={t.drawerFallbackTitle}>
      {trackId !== null ? <TrackDrawerBody key={trackId} trackId={trackId} /> : null}
    </Drawer>
  )
}

function TrackDrawerBody({ trackId }: { trackId: number }) {
  const track = useAsync((signal) => getTrack(trackId, { signal }), [trackId])
  if (track.error) return <Notice kind="error">{t.loadFailed}: {errorMessage(track.error)}</Notice>
  if (!track.data) return <Spinner />
  const { data } = track
  return (
    <div className={styles.body}>
      <div>
        <h3>{data.title || t.untitled}</h3>
        <p className={styles.artist}>{data.artist || t.unknownArtist}</p>
      </div>
      <LicenseBadge
        risk={data.license.risk}
        code={data.license.code}
        attribution={data.license.attribution_text}
        licenseUrl={data.license.url}
        commercialLicenseUrl={data.license.commercial_license_url}
      />
      <AddToProjectMenu trackId={data.id} trackTitle={data.title ?? ''} />
    </div>
  )
}
