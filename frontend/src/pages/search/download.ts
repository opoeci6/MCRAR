import { trackCreditsUrl } from '../../api/endpoints'

/**
 * One click for a downloadable track: the download page opens in a new tab (the audio is never
 * fetched by the app) and the licence file (credit line) is saved next to it.
 */
export function downloadTrack(trackId: number, downloadUrl: string): void {
  window.open(downloadUrl, '_blank', 'noopener')
  const link = document.createElement('a')
  link.href = trackCreditsUrl(trackId, 'txt')
  link.download = ''
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
}
