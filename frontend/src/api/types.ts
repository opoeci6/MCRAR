/*
 * Shapes of the backend JSON (see docs/api.md and backend/src/mcrar/api/routes/*).
 * Keep these in step with the routes; they are the only place the UI learns the contract.
 */

export type Risk = 'green' | 'amber' | 'red' | 'unknown'
export type Source = 'jamendo' | 'local'
export type Vocal = 'vocal' | 'instrumental'
export type CreditsFormat = 'txt' | 'md' | 'json'
/** 0 = not a fit, 1 = OK, 2 = good fit. */
export type RatingValue = 0 | 1 | 2

// -- meta ----------------------------------------------------------------------------------

export interface Health {
  status: string
  version: string
  catalog: { tracks: number }
  models_loaded: string[]
}

export interface VocabLabel {
  id: string
  display: string
  synonyms: string[]
}

/** Label sets by name (`genre`, `moodtheme`). */
export type Vocab = Record<string, VocabLabel[]>

export interface Stats {
  tracks: number
  tracks_by_source: Record<string, number>
  tracks_by_risk: Record<string, number>
  features: { tracks_with_features: number; coverage: number }
  embeddings_by_model: Record<string, number>
  ingest_failures_by_stage: Record<string, number>
}

// -- search --------------------------------------------------------------------------------

/** The filters of a search request. Everything is optional. */
export interface SearchFilters {
  max_risk?: Risk | null
  vocal?: Vocal | null
  bpm_min?: number | null
  bpm_max?: number | null
  duration_min_s?: number | null
  duration_max_s?: number | null
  sources?: string[] | null
  genres?: string[]
  moods?: string[]
}

export interface SearchRequest {
  text?: string | null
  filters?: SearchFilters
  limit?: number
  offset?: number
  explain?: boolean
}

export interface TagScore {
  label_set: string
  label: string
  display: string
  /** Standardised over the catalog: 0.5 is an average track for this label. */
  score: number
}

export interface BreakdownTerm {
  /** `null` when the term is inactive (weight 0). */
  raw: number | null
  weight: number
  contribution: number
}

/** Score terms by name (`semantic`, `tags`, `bpm`, `energy`). */
export type Breakdown = Record<string, BreakdownTerm>

export interface SearchItem {
  track_id: number
  title: string | null
  artist: string | null
  source: string
  source_url: string | null
  /** Only set when the licence and source allow downloading. */
  download_url: string | null
  duration_s: number | null
  bpm: number | null
  key: string | null
  mode: string | null
  energy: number | null
  license_code: string | null
  risk: Risk
  license_url: string | null
  attribution_text: string | null
  commercial_license_url: string | null
  top_tags: TagScore[]
  score: number
  breakdown: Breakdown
  explanation: string | null
  /** The owner's rating of this track for this query, or `null` when not rated. */
  rating: RatingValue | null
}

/** The query as the backend understood it (before any relaxation). */
export interface ParsedQuery {
  semantic_text: string | null
  filters: {
    max_risk: Risk
    vocal: Vocal | null
    bpm_min: number | null
    bpm_max: number | null
    duration_min_s: number | null
    duration_max_s: number | null
    sources: string[] | null
    genres: string[]
    moods: string[]
  }
  preferences: {
    energy_target: number | null
    bpm_target: number | null
    genre_hints: string[]
    mood_hints: string[]
  }
  notes: string[]
}

export interface SearchResponse {
  items: SearchItem[]
  /** Ranked candidates that `offset` and `limit` page through. */
  total_candidates: number
  parsed: ParsedQuery
  /** What was relaxed to find results, in order. */
  relaxed: string[]
  unembedded_count: number
  model_id: string
  elapsed_ms: number
  /** Messages for the user (missing embeddings, an empty result and why). */
  notes: string[]
}

// -- tracks --------------------------------------------------------------------------------

export interface TrackSummary {
  id: number
  title: string | null
  artist: string | null
  source: string
  duration_s: number | null
  risk: Risk
  license_code: string | null
}

export interface TrackList {
  items: TrackSummary[]
  total: number
  limit: number
  offset: number
}

export interface TrackTag {
  label_set: string
  label: string
  /** The raw stored probability (search results show standardised scores instead). */
  prob: number
  method: string
  model_version: string
}

export interface TrackLicense {
  code: string | null
  url: string | null
  family: string | null
  risk: Risk
  commercial_ok: boolean | null
  derivatives_ok: boolean | null
  share_alike: boolean | null
  attribution_required: boolean | null
  attribution_text: string | null
  commercial_license_url: string | null
}

/** Audio features stored for a track (all may be missing for an unanalysed track). */
export interface TrackFeatures {
  bpm: number | null
  bpm_raw: number | null
  bpm_confidence: number | null
  key: string | null
  mode: string | null
  key_confidence: number | null
  loudness_lufs: number | null
  rms_db: number | null
  energy: number | null
  sample_rate: number | null
  channels: number | null
  analysis_version: string | null
  analyzed_at: string | null
}

export interface TrackDetail extends TrackSummary {
  source_id: string
  album: string | null
  release_date: string | null
  source_url: string | null
  image_url: string | null
  vocal_instrumental: string | null
  /** Only for local tracks. */
  local_path: string | null
  stream_url: string
  download_url: string | null
  features: TrackFeatures | null
  tags: TrackTag[]
  license: TrackLicense
}

export interface TrackListParams {
  source?: Source
  risk?: Risk
  limit?: number
  offset?: number
}

// -- projects ------------------------------------------------------------------------------

export interface Project {
  id: number
  name: string
  created_at: string
  item_count: number
}

export interface ShortlistEntry {
  track: TrackSummary
  note: string | null
  added_at: string
}

export interface ProjectDetail extends Project {
  items: ShortlistEntry[]
}

// -- ratings -------------------------------------------------------------------------------

/** Names the query a result came from, the same way a search request does. */
export interface RatingTarget {
  text?: string | null
  filters?: SearchFilters
  track_id: number
}

export interface RatingRequest extends RatingTarget {
  rating: RatingValue
}

export interface StoredRating {
  query_key: string
  track_id: number
  rating: RatingValue
}

export interface RatingListEntry {
  query_key: string
  query_text: string | null
  filters: SearchFilters
  track: { id: number; title: string | null; artist: string | null }
  rating: RatingValue
  updated_at: string
}

export interface RatingList {
  items: RatingListEntry[]
  total: number
}

// -- settings and secrets ------------------------------------------------------------------

export interface SearchWeights {
  semantic: number
  tags: number
  bpm: number
  energy: number
}

export interface EditableSettings {
  commercial_mode: boolean
  default_embedder: string
  search: {
    pool_size: number
    max_per_artist: number
    min_results: number
    weights: SearchWeights
  }
}

export interface EmbedderInfo {
  key: string
  model_id: string
  commercial_ok: boolean
  /** Whether the current licence mode lets it be used. */
  allowed: boolean
}

export interface SettingsView {
  editable: EditableSettings
  read_only: Record<string, string | number>
  /** Dotted names (`commercial_mode`, `search.pool_size`) pinned by an MCRAR_* variable. */
  overridden_by_env: string[]
  embedders: EmbedderInfo[]
}

/** A partial update: send only what changed. */
export interface SettingsUpdate {
  commercial_mode?: boolean
  default_embedder?: string
  search?: {
    pool_size?: number
    max_per_artist?: number
    min_results?: number
    weights?: Partial<SearchWeights>
  }
}

export interface SecretItem {
  name: string
  /** `env` or the backend label. Never the value. */
  source: string | null
}

export interface KnownSecret {
  name: string
  description: string
}

export interface SecretsList {
  backend: string
  items: SecretItem[]
  known: KnownSecret[]
}

// -- ingest jobs ---------------------------------------------------------------------------

export type JobStatus = 'running' | 'done' | 'failed' | 'cancelled'

export interface Job {
  id: string
  kind: string
  params: Record<string, unknown>
  status: JobStatus
  created_at: string
  finished_at: string | null
  cancel_requested: boolean
  error: string | null
  progress: { index: number | null; total: number | null } | null
}

export interface IngestFailure {
  source_id: string
  title: string
  stage: string
  message: string
}

export interface JobReport {
  seen: number
  new: number
  updated: number
  processed: number
  skipped: number
  failed: number
  failures: IngestFailure[]
  failures_total: number
  elapsed_s: number
  aborted?: string | null
}

export interface JobDetail extends Job {
  event_count: number
  report: JobReport | null
}

export interface JamendoIngestRequest {
  tags?: string[] | null
  fuzzytags?: string[] | null
  search?: string | null
  vocalinstrumental?: Vocal | null
  commercial_only?: boolean
  order?: string | null
  limit?: number
  embed?: boolean
  force?: boolean
}

export interface LocalIngestRequest {
  /** An absolute folder path on the machine running the backend. */
  path: string
  license?: string | null
  force?: boolean
  embed?: boolean
}

export interface ReprocessRequest {
  what: 'embed' | 'tag'
  force?: boolean
  source?: Source | null
}

export type JobProgressKind =
  | 'started'
  | 'track_done'
  | 'track_skipped'
  | 'track_failed'
  | 'finished'

/** Data of the Server-Sent events of a job. */
export interface JobEventData {
  started: { kind: string; params: Record<string, unknown> }
  progress: {
    kind: JobProgressKind
    index: number
    total: number | null
    title: string
    message: string | null
  }
  warning: { message: string }
  done: { report: JobReport | null }
  failed: { report: JobReport | null; error: string }
  cancelled: { report: JobReport | null }
}

export type JobEventType = keyof JobEventData

// -- analyze -------------------------------------------------------------------------------

export interface AudioFeatures {
  bpm: number | null
  bpm_raw: number | null
  bpm_confidence: number
  key: string | null
  mode: string | null
  key_confidence: number
  loudness_lufs: number | null
  rms_db: number
  energy: number
  duration_s: number
  sample_rate: number
  channels: number
  analysis_version: string
}

export interface AnalyzeResponse {
  filename: string
  features: AudioFeatures
}
