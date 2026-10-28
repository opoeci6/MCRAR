/*
 * Shapes of the backend JSON (see docs/api.md and backend/src/mcrar/api/routes/*).
 * Keep these in step with the routes; they are the only place the UI learns the contract.
 */

export type Risk = 'green' | 'amber' | 'red' | 'unknown'
export type Source = 'jamendo' | 'freesound' | 'local'
export type Vocal = 'vocal' | 'instrumental'
export type CreditsFormat = 'txt' | 'md' | 'json'
/** 0 = not a fit, 1 = OK, 2 = good fit. */
export type RatingValue = 0 | 1 | 2

// -- meta ----------------------------------------------------------------------------------

export interface HealthModel {
  key: string
  state: 'loading' | 'ready' | 'error'
  device: string | null
  dtype: string | null
  error?: string
}

export interface Health {
  status: string
  version: string
  catalog: { tracks: number }
  models_loaded: string[]
  /** The models that are loaded, loading or failed (a default that was never used is absent). */
  models: HealthModel[]
  /** Null without a CUDA GPU. */
  gpu: { vram_allocated_mb: number; vram_reserved_mb: number } | null
}

export interface VocabLabel {
  id: string
  display: string
  synonyms: string[]
}

/** Label sets by name (`genre`, `moodtheme`, `scene`; `scene` is absent from an older backend). */
export type Vocab = Record<string, VocabLabel[]>

/** How intense a track feels, for the search filter and for a hand label. */
export type Intensity = 'low' | 'mid' | 'high'

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
  /** Game scene ids from the vocabulary (a soft preference, like moods). */
  scenes?: string[]
  /** Sets the energy target; wins over energy words in the text. */
  intensity?: Intensity | null
}

/** The reference song of a search: a catalog track, or an upload from POST /api/reference. */
export type ReferenceRef = { track_id: number } | { upload_id: string }

export interface SearchRequest {
  text?: string | null
  filters?: SearchFilters
  reference?: ReferenceRef
  /** The reference's share of the semantic score, 0 to 1 (the backend defaults to 0.5). */
  reference_weight?: number
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

/** Score terms by name (`semantic`, `reference`, `tags`, `bpm`, `energy`). */
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
  /** 0 to 1, or `null` when unknown. Below 0.5 the tempo may be half or double. */
  bpm_confidence: number | null
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
  /** Position (1..N) the LLM gave this track in a rerank; absent or null in a normal search. */
  llm_rank?: number | null
  /** The LLM's reason for this track (a rerank only). */
  llm_explanation?: string | null
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
  /** Who read the query. Absent from an older backend: read it as "rules". */
  source?: ParseSource
  /** Jamendo search terms the LLM produced (empty for rules). */
  search_terms?: string[]
}

export type ParseSource = 'rules' | 'llm'

/** How well the best result matched a text search. */
export interface MatchQuality {
  /** Cosine similarity of the best result, or `null` without text or without results. */
  top_cosine: number | null
  /** The best match is weak, so importing more tracks may help. Only ever true with text. */
  weak: boolean
}

/** What the LLM did while reading a query. "used" is false when it fell back to the rules. */
export interface LlmUse {
  used: boolean
  model: string
  cached: boolean
  /** A short, safe reason when "used" is false. */
  error: string | null
}

export type RerankVerdict = 'good' | 'partial' | 'poor'

/** The LLM's verdict on a reranked result list. */
export interface RerankInfo {
  model: string
  verdict: RerankVerdict
  summary: string
  search_terms: string[]
  elapsed_ms: number
}

/** The reference song as the search used it (never its vector). */
export interface SearchReference {
  kind: 'track' | 'upload'
  track_id: number | null
  label: string
  weight: number
}

/** POST /api/reference: the uploaded song, kept in memory by the backend as a vector only. */
export interface ReferenceUpload {
  upload_id: string
  filename: string
  duration_s: number
  model_id: string
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
  /** Absent from an older backend: read it as `{ top_cosine: null, weak: false }`. */
  match?: MatchQuality
  /** Null when the LLM is off or not ready, or the search has no text. Absent from an older backend. */
  llm?: LlmUse | null
  /** Only set by POST /api/search/rerank. */
  rerank?: RerankInfo | null
  /** The reference song of the request; null without one. Absent from an older backend. */
  reference?: SearchReference | null
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

/** A track on a shortlist: the summary plus what a row needs for links, download and credit. */
export interface ShortlistTrack extends TrackSummary {
  source_id: string
  source_url: string | null
  /** Null unless the source allows downloading. */
  download_url: string | null
  license_url: string | null
  commercial_license_url: string | null
  attribution_text: string | null
}

export interface ShortlistEntry {
  track: ShortlistTrack
  note: string | null
  added_at: string
}

export interface ProjectDetail extends Project {
  items: ShortlistEntry[]
}

// -- scene labels --------------------------------------------------------------------------

export type LabelStatus = 'labelled' | 'skipped'
/** Which tracks of the labelling pool a labeller works on (`A` and `B` include the shared ones). */
export type LabelPart = 'all' | 'A' | 'B'
/** The part a pool track belongs to. */
export type PoolPart = 'A' | 'B' | 'both'

/** One labeller's label of one track. `labelled` with no scenes means "none of these". */
export interface SceneLabel {
  track_id: number
  labeller: string
  scenes: string[]
  intensity: Intensity | null
  status: LabelStatus
  created_at: string
  updated_at: string
}

/** The body of PUT /api/labels/{track_id}. */
export interface SceneLabelRequest {
  labeller: string
  scenes: string[]
  intensity: Intensity | null
  status: LabelStatus
}

/** A pool track with what the player needs (a `PlayableTrack` fits it as is). */
export interface LabelTrack {
  id: number
  title: string | null
  artist: string | null
  duration_s: number | null
  source: string
  risk: Risk
  license_code: string | null
  license_url: string | null
  commercial_license_url: string | null
  attribution: string | null
  stream_url: string
}

/** GET /api/labels/next: the next track to label, or `{ track: null }` when the part is done. */
export type NextLabel =
  | { track: null }
  | { track: LabelTrack; position: number; part: PoolPart; label: SceneLabel | null }

export interface PoolEntry {
  position: number
  part: PoolPart
  track_id: number
  title: string | null
  artist: string | null
  /** The labeller's status for this track; `null` while it has not been labelled or skipped. */
  status: LabelStatus | null
}

export interface LabelPool {
  items: PoolEntry[]
  total: number
}

export interface PartProgress {
  total: number
  labelled: number
  skipped: number
}

export interface LabelProgress {
  pool_size: number
  parts: Record<PoolPart, PartProgress>
  labelled: number
  skipped: number
  /** Every name that has labels in this catalog. */
  labellers: string[]
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

export type LlmKind = 'openai' | 'anthropic'

export interface LlmSettings {
  enabled: boolean
  preset: string
  /** Empty means the preset's default model. */
  model: string
  /** Empty means the preset's default address. */
  base_url: string
  parse_timeout_s: number
  rerank_timeout_s: number
  rerank_top_n: number
}

export interface LlmPreset {
  id: string
  label: string
  kind: LlmKind
  base_url: string
  default_model: string
  /** The secret name of this preset's API key. */
  key_secret: string
  key_required: boolean
  docs_url: string
}

export interface EditableSettings {
  default_embedder: string
  llm: LlmSettings
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
}

export interface SettingsView {
  editable: EditableSettings
  read_only: Record<string, string | number>
  /** Dotted names (`default_embedder`, `search.pool_size`) pinned by an MCRAR_* variable. */
  overridden_by_env: string[]
  embedders: EmbedderInfo[]
  llm_presets: LlmPreset[]
}

/** A partial update: send only what changed. */
export interface SettingsUpdate {
  default_embedder?: string
  llm?: Partial<LlmSettings>
  search?: {
    pool_size?: number
    max_per_artist?: number
    min_results?: number
    weights?: Partial<SearchWeights>
  }
}

export type LlmNotReadyReason = 'disabled' | 'missing_key' | 'missing_model'

/** GET /api/llm: whether the LLM can be used right now. */
export interface LlmStatus {
  enabled: boolean
  ready: boolean
  preset: string
  label: string
  kind: LlmKind
  /** The model actually used (the preset's default when the setting is empty). */
  model: string
  reason: LlmNotReadyReason | null
  /** How many results a rerank reorders. Absent from an older backend. */
  rerank_top_n?: number
}

/** The body of POST /api/llm/test: values to try instead of the saved ones. */
export interface LlmTestRequest {
  preset?: string
  model?: string
  base_url?: string
}

export type LlmTestResult =
  | { ok: true; model: string; elapsed_ms: number }
  | { ok: false; error: string }

export interface LlmModel {
  id: string
  /** A friendlier name, when the provider gives one. */
  label: string | null
}

export type LlmModelList =
  | { ok: true; preset: string; models: LlmModel[]; default_model: string }
  | { ok: false; error: string }

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
  /** Tracks this job added to the catalog (import-for-search jobs). */
  new_track_ids?: number[]
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

export type FreesoundLicense = 'cc0' | 'by' | 'by-nc' | 'sampling+'

export type FreesoundSort =
  | 'score'
  | 'duration_desc'
  | 'duration_asc'
  | 'created_desc'
  | 'created_asc'
  | 'downloads_desc'
  | 'downloads_asc'
  | 'rating_desc'
  | 'rating_asc'

/** Imports music-like sounds from Freesound; needs a query or at least one tag. */
export interface FreesoundIngestRequest {
  /** Up to 200 characters. */
  query?: string
  /** Up to 10, each of a-z, 0-9, `_` and `-`. */
  tags?: string[]
  /** At least one; the backend defaults to cc0 and by. */
  licenses?: FreesoundLicense[]
  /** The backend defaults to 10. */
  duration_min_s?: number
  /** Up to 3600; the backend defaults to 600. */
  duration_max_s?: number
  sort?: FreesoundSort
  /** 1 to 500; the backend defaults to 50. */
  limit?: number
  embed?: boolean
  force?: boolean
}

/** A remote source a search import can add tracks from. */
export type ImportSource = 'jamendo' | 'freesound'

/** Searches Jamendo and/or Freesound for the text of a search and imports the candidates found. */
export interface SearchImportRequest {
  text: string
  /** The filters of the search, the same object that `SearchRequest` takes. */
  filters?: SearchFilters
  /** 1 to 100 new tracks in all, split between the sources; the backend defaults to 50. */
  limit?: number
  /** Omitted: every source whose secret is set. A list uses exactly those (503 when one is missing). */
  sources?: ImportSource[]
}

/** GET /api/search/import/sources: the sources whose secret is set, never a value. */
export interface SearchImportSources {
  sources: ImportSource[]
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
