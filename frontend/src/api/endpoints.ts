/*
 * One typed function per API route (docs/api.md). Each takes an optional `signal` last, so a
 * caller can cancel a request when its component unmounts (`useAsync` does this for you).
 *
 * Audio and downloads are not fetched in JS: use `trackStreamUrl` as an <audio> src and the
 * `*CreditsUrl` and `labelsExportUrl` helpers as the href of an <a download>.
 */
import { request } from './client'
import type {
  AnalyzeResponse,
  CreditsFormat,
  FreesoundIngestRequest,
  Health,
  JamendoIngestRequest,
  Job,
  JobDetail,
  LabelPart,
  LabelPool,
  LabelProgress,
  LlmModelList,
  LlmStatus,
  LlmTestRequest,
  LlmTestResult,
  LocalIngestRequest,
  NextLabel,
  Project,
  ProjectDetail,
  RatingList,
  RatingRequest,
  RatingTarget,
  ReferenceUpload,
  ReprocessRequest,
  SceneLabel,
  SceneLabelRequest,
  SearchImportRequest,
  SearchImportSources,
  SearchRequest,
  SearchResponse,
  SecretsList,
  SettingsUpdate,
  SettingsView,
  ShortlistEntry,
  Stats,
  TrackDetail,
  TrackList,
  TrackListParams,
  Vocab,
  StoredRating,
} from './types'

export interface CallOptions {
  signal?: AbortSignal
}

const id = (value: number | string) => encodeURIComponent(String(value))

// -- meta ----------------------------------------------------------------------------------

export const getHealth = (o?: CallOptions) => request<Health>('GET', '/api/health', o)
export const getVocab = (o?: CallOptions) => request<Vocab>('GET', '/api/vocab', o)
export const getStats = (o?: CallOptions) => request<Stats>('GET', '/api/stats', o)

// -- search --------------------------------------------------------------------------------

export const search = (body: SearchRequest, o?: CallOptions) =>
  request<SearchResponse>('POST', '/api/search', { ...o, body })

/**
 * Asks the LLM to reorder the top results of this search (same body as "search"; limit and
 * offset are ignored). 503 when no LLM is configured, 502 when the LLM call fails.
 */
export const rerankSearch = (body: SearchRequest, o?: CallOptions) =>
  request<SearchResponse>('POST', '/api/search/rerank', { ...o, body })

/** Starts a job that imports Jamendo and/or Freesound candidates for a search. Re-run the search when it is done. */
export const importForSearch = (body: SearchImportRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/search/import', { ...o, body })

/** The sources a search import can use now (those with their key or client id set). */
export const getImportSources = (o?: CallOptions) =>
  request<SearchImportSources>('GET', '/api/search/import/sources', o)

// -- reference song -------------------------------------------------------------------------

/**
 * Uploads a song to search by (at most 50 MB). The backend keeps its embedding in memory, not
 * the audio; pass the returned `upload_id` as the `reference` of a search. 413, 422 and 503
 * carry a message for the user.
 */
export const uploadReference = (file: File, o?: CallOptions) => {
  const form = new FormData()
  form.append('file', file)
  return request<ReferenceUpload>('POST', '/api/reference', { ...o, form })
}

// -- llm ------------------------------------------------------------------------------------

/** Whether the optional LLM can be used right now, and why not. */
export const getLlmStatus = (o?: CallOptions) => request<LlmStatus>('GET', '/api/llm', o)

/** Tries the LLM with the given values (or the saved ones). A failure is a 200 with ok: false. */
export const testLlm = (body?: LlmTestRequest, o?: CallOptions) =>
  request<LlmTestResult>('POST', '/api/llm/test', { ...o, body: body ?? {} })

/** The provider's model names (for the draft provider and address). A failure is a 200 with ok: false. */
export const listLlmModels = (body: { preset?: string; base_url?: string }, o?: CallOptions) =>
  request<LlmModelList>('POST', '/api/llm/models', { ...o, body })

// -- tracks --------------------------------------------------------------------------------

export const listTracks = (params: TrackListParams = {}, o?: CallOptions) =>
  request<TrackList>('GET', '/api/tracks', { ...o, query: { ...params } })

export const getTrack = (trackId: number, o?: CallOptions) =>
  request<TrackDetail>('GET', `/api/tracks/${id(trackId)}`, o)

/** The `src` of an <audio> element. The backend redirects Jamendo to its CDN and Freesound to its preview, or serves the file. */
export const trackStreamUrl = (trackId: number) => `/api/tracks/${id(trackId)}/stream`

/** Download link for the credits of one track. */
export const trackCreditsUrl = (trackId: number, format: CreditsFormat = 'txt') =>
  `/api/tracks/${id(trackId)}/credits?format=${format}`

// -- projects ------------------------------------------------------------------------------

export const listProjects = (o?: CallOptions) => request<Project[]>('GET', '/api/projects', o)

export const createProject = (name: string, o?: CallOptions) =>
  request<Project>('POST', '/api/projects', { ...o, body: { name } })

export const getProject = (projectId: number, o?: CallOptions) =>
  request<ProjectDetail>('GET', `/api/projects/${id(projectId)}`, o)

export const renameProject = (projectId: number, name: string, o?: CallOptions) =>
  request<Project>('PATCH', `/api/projects/${id(projectId)}`, { ...o, body: { name } })

export const deleteProject = (projectId: number, o?: CallOptions) =>
  request<void>('DELETE', `/api/projects/${id(projectId)}`, o)

export const listProjectItems = (projectId: number, o?: CallOptions) =>
  request<ShortlistEntry[]>('GET', `/api/projects/${id(projectId)}/items`, o)

/** Adds the track, or replaces its note (leaving `note` out clears it). Safe to repeat. */
export const putProjectItem = (
  projectId: number,
  trackId: number,
  note?: string | null,
  o?: CallOptions,
) =>
  request<ShortlistEntry>('PUT', `/api/projects/${id(projectId)}/items/${id(trackId)}`, {
    ...o,
    body: note == null ? undefined : { note },
  })

export const deleteProjectItem = (projectId: number, trackId: number, o?: CallOptions) =>
  request<void>('DELETE', `/api/projects/${id(projectId)}/items/${id(trackId)}`, o)

/** Download link for a project's credits. */
export const projectCreditsUrl = (projectId: number, format: CreditsFormat = 'md') =>
  `/api/projects/${id(projectId)}/credits?format=${format}`

// -- ratings -------------------------------------------------------------------------------

export const putRating = (body: RatingRequest, o?: CallOptions) =>
  request<StoredRating>('PUT', '/api/ratings', { ...o, body })

export const deleteRating = (body: RatingTarget, o?: CallOptions) =>
  request<void>('DELETE', '/api/ratings', { ...o, body })

export const listRatings = (params: { limit?: number; offset?: number } = {}, o?: CallOptions) =>
  request<RatingList>('GET', '/api/ratings', { ...o, query: { ...params } })

// -- scene labels --------------------------------------------------------------------------

/**
 * The first pool track of the part that the labeller has not labelled or skipped yet, after the
 * position `after` when given. 409 when there is no labelling pool yet.
 */
export const getNextLabel = (
  labeller: string,
  part: LabelPart,
  after?: number,
  o?: CallOptions,
) => request<NextLabel>('GET', '/api/labels/next', { ...o, query: { labeller, part, after } })

/** The pool of the part in order, with the labeller's status per track. 409 without a pool. */
export const getLabelPool = (labeller: string, part: LabelPart, o?: CallOptions) =>
  request<LabelPool>('GET', '/api/labels/pool', { ...o, query: { labeller, part } })

/** How much of each part the labeller has done. 409 without a pool. */
export const getLabelProgress = (labeller: string, o?: CallOptions) =>
  request<LabelProgress>('GET', '/api/labels/progress', { ...o, query: { labeller } })

/** The labeller's label of a track; 404 when there is none. */
export const getLabel = (trackId: number, labeller: string, o?: CallOptions) =>
  request<SceneLabel>('GET', `/api/labels/${id(trackId)}`, { ...o, query: { labeller } })

/** Stores or replaces the label (`labelled` with no scenes means "none of these"). */
export const putLabel = (trackId: number, body: SceneLabelRequest, o?: CallOptions) =>
  request<SceneLabel>('PUT', `/api/labels/${id(trackId)}`, { ...o, body })

export const deleteLabel = (trackId: number, labeller: string, o?: CallOptions) =>
  request<void>('DELETE', `/api/labels/${id(trackId)}`, { ...o, query: { labeller } })

/** Download link for the labeller's labels file (the one `mcrar scenes import-labels` reads). */
export const labelsExportUrl = (labeller: string) =>
  `/api/labels/export?labeller=${id(labeller)}`

// -- settings and secrets ------------------------------------------------------------------

export const getSettings = (o?: CallOptions) => request<SettingsView>('GET', '/api/settings', o)

export const updateSettings = (body: SettingsUpdate, o?: CallOptions) =>
  request<SettingsView>('PUT', '/api/settings', { ...o, body })

/** Names and sources only: the backend never returns a secret value. */
export const listSecrets = (o?: CallOptions) => request<SecretsList>('GET', '/api/secrets', o)

/**
 * Stores a secret. The value goes in the request body and nowhere else: it is never put in a
 * URL, an error, a log line or component state beyond the input that holds it.
 */
export const setSecret = (name: string, value: string, o?: CallOptions) =>
  request<void>('PUT', `/api/secrets/${id(name)}`, { ...o, body: { value } })

export const deleteSecret = (name: string, o?: CallOptions) =>
  request<void>('DELETE', `/api/secrets/${id(name)}`, o)

// -- ingest jobs ---------------------------------------------------------------------------

export const ingestJamendo = (body: JamendoIngestRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/ingest/jamendo', { ...o, body })

export const ingestFreesound = (body: FreesoundIngestRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/ingest/freesound', { ...o, body })

export const ingestLocal =(body: LocalIngestRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/ingest/local', { ...o, body })

export const reprocess = (body: ReprocessRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/ingest/reprocess', { ...o, body })

export const listJobs = (o?: CallOptions) => request<{ jobs: Job[] }>('GET', '/api/jobs', o)

export const getJob = (jobId: string, o?: CallOptions) =>
  request<{ job: JobDetail }>('GET', `/api/jobs/${id(jobId)}`, o)

export const cancelJob = (jobId: string, o?: CallOptions) =>
  request<{ job: Job }>('POST', `/api/jobs/${id(jobId)}/cancel`, o)

// -- analyze -------------------------------------------------------------------------------

/** Analyses an audio file (at most 50 MB). Nothing is stored. */
export const analyzeFile = (file: File, o?: CallOptions) => {
  const form = new FormData()
  form.append('file', file)
  return request<AnalyzeResponse>('POST', '/api/analyze', { ...o, form })
}
