import { downloadTrack } from './download'
import { strings } from '../../strings'
import { Button } from '../../ui/Button'
import { trackFeatureStrings as t } from './strings'

export interface TrackActionsProps {
  trackId: number
  /** The title to name the buttons after (already with its fallback). */
  title: string
  /** Null unless the source allows downloading: without it there is no Download button. */
  downloadUrl: string | null
  onFindSimilar: () => void
}

/**
 * The Download and Find similar buttons of a track row. Renders two buttons without a wrapper,
 * so they sit in the action group of the row that uses them.
 */
export function TrackActions({ trackId, title, downloadUrl, onFindSimilar }: TrackActionsProps) {
  return (
    <>
      {downloadUrl ? (
        <Button size="sm" title={t.downloadHint} onClick={() => downloadTrack(trackId, downloadUrl)}>
          {t.download}
          <span className="sr-only"> {strings.common.opensInNewTab}</span>
        </Button>
      ) : null}
      <Button size="sm" aria-label={t.findSimilarTo(title)} onClick={onFindSimilar}>
        {t.findSimilar}
      </Button>
    </>
  )
}
