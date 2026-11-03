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
  FileRoots,
  FilesIngestRequest,
  FolderListing,
  FreesoundIngestRequest,
  Health,
  JamendoIngestRequest,
  LinksIngestRequest,
  Job,
  JobDetail,
  LabelPart,
  LabelPool,
  LabelProgress,
  LibraryFileUpload,
  LlmModelList,
  LlmStatus,
  LlmTestRequest,
  LlmTestResult,
  LocalIngestRequest,
  MissingTracks,
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
  TrackRemovalImpact,
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

/**
 * Sets the licence of a local track by hand: a code ("CC BY 4.0"), a licence URL, or "unknown"
 * (which hands it back to the folder). Answers with the track as `getTrack` does. 422 for a track
 * from Jamendo or Freesound or an unrecognised value; 409 while a job runs.
 */
export const setTrackLicense = (trackId: number, license: string, o?: CallOptions) =>
  request<TrackDetail>('PUT', `/api/tracks/${id(trackId)}/license`, { ...o, body: { license } })

/** What removing the track would take with it, to say so before asking. */
export const trackRemoval = (trackId: number, o?: CallOptions) =>
  request<TrackRemovalImpact>('GET', `/api/tracks/${id(trackId)}/removal`, o)

/** Removes the track with its ratings, scene labels and project entries. 409 while a job runs. */
export const removeTrack = (trackId: number, o?: CallOptions) =>
  request<void>('DELETE', `/api/tracks/${id(trackId)}`, o)

/** Local tracks whose file is gone (the list holds at most 200; `count` is all of them). */
export const missingTracks = (o?: CallOptions) =>
  request<MissingTracks>('GET', '/api/tracks/missing', o)

/** Removes every local track whose file is gone. 409 while a job runs. */
export const removeMissingTracks = (o?: CallOptions) =>
  request<{ removed: number }>('POST', '/api/tracks/remove-missing', o)

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

export const ingestLinks = (body: LinksIngestRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/ingest/links', { ...o, body })

export const ingestLocal = (body: LocalIngestRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/ingest/local', { ...o, body })

/** Starts a job that adds files copied into the library folder with `uploadLibraryFile`. */
export const ingestFiles = (body: FilesIngestRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/ingest/files', { ...o, body })

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

// -- files on this computer ----------------------------------------------------------------

/** The drives and starting places for the folder browser. 403 unless the backend is local. */
export const fileRoots = (o?: CallOptions) => request<FileRoots>('GET', '/api/files/roots', o)

/** The sub-folders of an absolute folder path, and how many audio files it holds. 422 for a bad path. */
export const listFolder = (path: string, o?: CallOptions) =>
  request<FolderListing>('GET', '/api/files/list', { ...o, query: { path } })

/**
 * Copies one file into MCRAR's own library folder (the raw bytes are the body; at most 2 GB).
 * Sending the same file again is quick and answers `already: true`. Add the copies to the
 * catalog with `ingestFiles`.
 */
export const uploadLibraryFile = (file: File, o?: CallOptions) =>
  request<LibraryFileUpload>('POST', '/api/library/files', {
    ...o,
    blob: file,
    query: { name: file.name },
  })
