import { ApiError, errorDetail, isAbort } from '../../api/client'
import { projectCreditsUrl } from '../../api/endpoints'
import type { CreditsFormat } from '../../api/types'
import { strings } from '../../strings'

/** The text of a project's credits, for the preview (a download is a plain link instead). */
export async function fetchCreditsText(
  projectId: number,
  format: CreditsFormat,
  signal: AbortSignal,
): Promise<string> {
  let response: Response
  try {
    response = await fetch(projectCreditsUrl(projectId, format), { signal })
  } catch (error) {
    if (isAbort(error)) throw error
    throw new ApiError(0, strings.errors.network)
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => undefined)
    throw new ApiError(response.status, errorDetail(response.status, body))
  }
  return response.text()
}
