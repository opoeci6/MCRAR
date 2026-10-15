/*
 * One typed function per API route (docs/api.md). Each takes an optional `signal` last, so a
 * caller can cancel a request when its component unmounts (`useAsync` does this for you).
 *
 * Audio and downloads are not fetched in JS: use `trackStreamUrl` as an <audio> src and the
 * `*CreditsUrl` helpers as the href of an <a download>.
 */
import { request } from './client'
import type {
  AnalyzeResponse,
  CreditsFormat,
  Health,
  JamendoIngestRequest,
  Job,
  JobDetail,
  LocalIngestRequest,
  Project,
  ProjectDetail,
  RatingList,
  RatingRequest,
  RatingTarget,
  ReprocessRequest,
  SearchImportRequest,
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

/** Starts a job that imports Jamendo candidates for a search. Re-run the search when it is done. */
export const importForSearch = (body: SearchImportRequest, o?: CallOptions) =>
  request<{ job: Job }>('POST', '/api/search/import', { ...o, body })

// -- tracks --------------------------------------------------------------------------------

export const listTracks = (params: TrackListParams = {}, o?: CallOptions) =>
  request<TrackList>('GET', '/api/tracks', { ...o, query: { ...params } })

export const getTrack = (trackId: number, o?: CallOptions) =>
  request<TrackDetail>('GET', `/api/tracks/${id(trackId)}`, o)

/** The `src` of an <audio> element. The backend redirects Jamendo to its CDN or serves the file. */
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

export const ingestLocal = (body: LocalIngestRequest, o?: CallOptions) =>
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
