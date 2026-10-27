# HTTP API (M5)

A local FastAPI server for the UI (M6) and the desktop shell (M11). It keeps the embedding model
loaded between requests, so a text search takes about 0.1–0.2 s instead of the CLI's ~15 s
model load. The full schema is at `/docs` (Swagger UI) and `/openapi.json` while the server runs.

## Running it

```bash
scripts/with-env.sh uv run --directory backend mcrar serve --warm   # 127.0.0.1:8000
```

| Option | Effect |
|---|---|
| `--warm` | Load the default embedder (CLAP) in the background at startup. Without it, the first text search loads it. |
| `--host`, `--port` | Default: `api_host` and `api_port` from settings (`127.0.0.1:8000`). |
| `--allow-remote` | Required for a non-loopback host. The API has no login, so only use it on a trusted network. |
| `--reload` | Auto-reload for development. |

`scripts/dev.ps1` starts the API (`uvicorn --factory mcrar.api.app:create_app`) and the Vite dev
server, which proxies `/api`. When `frontend/dist` exists, the API also serves the built UI at `/`.

## Routes (all under `/api`)

| Area | Routes |
|---|---|
| Meta | `GET /health` (`{status, version, catalog: {tracks}, models_loaded: [keys of the ready models], models: [{key, state: "loading"\|"ready"\|"error", device, dtype, error?}], gpu: {vram_allocated_mb, vram_reserved_mb}\|null}`; `models` lists every model that is loaded, loading or failed to load, `device` and `dtype` are null until it is ready, `error` is the sanitised message of the last failed load; `gpu` is null unless torch is already loaded in the server and CUDA is available), `GET /vocab` (`{genre, moodtheme, scene}`: the labels for filters, each `{id, display, synonyms}`), `GET /stats` |
| Search | `POST /search` `{text?, filters{max_risk, vocal, bpm_min/max, duration_min_s/max_s, sources, genres, moods, scenes, intensity: low\|mid\|high}, reference?{track_id \| upload_id}, reference_weight = 0.5, limit, offset, explain}` → results with a score breakdown, explanation and the stored `rating` (0–2 or null) for this query, plus `match: {top_cosine, weak}` (the raw text–audio cosine of the best hit, and whether it is below `search.weak_cosine`, by default 0.40 for CLAP and MuQ-MuLan, none for GLAP; always null/false without text), and `reference: {kind: track\|upload, track_id, label, weight} \| null` (the reference song as used, never its vector). Each item carries `bpm` and `bpm_confidence` (0–1, or null when unknown); below 0.5 the tempo may be half or double, which ranking and the BPM filter already allow for and the UI shows as two readings; `POST /search/import` `{text, filters, limit 1–100 = 50}` → 202 with an `ingest-query` job that searches Jamendo for the query and imports up to `limit` tracks not yet in the catalog (embedded with the default model and CLAP, then tagged) |
| LLM (M7, optional; see `docs/llm.md`) | `GET /llm` → `{enabled, ready, preset, label, kind, model, reason, rerank_top_n}`, where `reason` is `disabled`, `missing_model`, `missing_key` or null. `POST /llm/test` `{preset?, model?, base_url?}` → always 200 with `{ok: true, model, elapsed_ms}` or `{ok: false, error}`; it tests unsaved values too. `POST /llm/models` `{preset?, base_url?}` → always 200 with `{ok: true, preset, models: [{id, label}], default_model}` (chat models only, sorted, needs the key but no model) or `{ok: false, error}`. `POST /search/rerank` takes the `/search` body (text required) → the same response shape, with the top `llm.rerank_top_n` results in the LLM's order, each item's `llm_rank` and `llm_explanation`, and `rerank: {model, verdict: good\|partial\|poor, summary, search_terms, elapsed_ms}`. It answers 503 when no LLM is ready and 502 when the LLM call fails, and 422 ("LLM rerank doesn't use a reference song yet.") when the body has a `reference`. Every `/search` response also has `parsed.source` (`rules`/`llm`), `parsed.search_terms` and `llm: {used, model, cached, error} \| null` |
| Ratings | `PUT /ratings` `{text?, filters?, track_id, rating: 0\|1\|2}`; `DELETE /ratings` (same body without `rating`); `GET /ratings?limit&offset`. A rating is keyed by the lowercased query text, or by canonical filters for a filter-only search. |
| Scene labels (M9; see `docs/labelling.md`) | The labelling page's endpoints. A *labeller* is a name of 1–40 characters (trimmed, no control characters), passed as `?labeller=` (a query parameter on every route but `PUT`, where it is in the body). `GET /labels/next?labeller&part=all\|A\|B&after=<position>` → `{track: {id, title, artist, duration_s, source, risk, license_code, license_url, commercial_license_url, attribution, stream_url}, position, part, label}` for the first pool track of that part (`A` and `B` each include the shared `both` tracks) that the labeller has neither labelled nor skipped, after `after` when given, or `{track: null}` when the part is done. `GET /labels/pool?labeller&part` → `{items: [{position, part, track_id, title, artist, status: null\|"labelled"\|"skipped"}], total}` in pool order. `GET /labels/progress?labeller` → `{pool_size, parts: {A, B, both: {total, labelled, skipped}}, labelled, skipped, labellers: [names]}`. `GET /labels/{track_id}?labeller` → `{track_id, labeller, scenes, intensity, status, created_at, updated_at}` or 404. `PUT /labels/{track_id}` `{labeller, scenes: [scene ids], intensity: "low"\|"mid"\|"high"\|null, status: "labelled"\|"skipped"}` stores or replaces that labeller's label and answers it. `labelled` with no scenes means "no scene fits"; a `skipped` label keeps no scenes or intensity. An unknown scene id is a 422 listing the valid ones; an unknown track a 404. `DELETE /labels/{track_id}?labeller` → 204 or 404. `GET /labels/export?labeller` → the labels file as a download (`Content-Disposition: attachment; filename="scene-labels-<labeller>.json"`, `scene-labels-all.json` without `labeller`), the format `mcrar scenes import-labels` reads. The responses never say why a track is in the pool, so the labeller is not primed. |
| Tracks | `GET /tracks?source&risk&limit&offset`; `GET /tracks/{id}`; `GET /tracks/{id}/stream`; `GET /tracks/{id}/credits?format=txt\|md\|json` |
| Projects | `GET/POST /projects`; `GET/PATCH/DELETE /projects/{id}`; `GET /projects/{id}/items`; `PUT/DELETE /projects/{id}/items/{track_id}` (with an optional note); `GET /projects/{id}/credits?format=`. A shortlist entry is `{track, note, added_at}`; `track` has `id, title, artist, source, duration_s, risk, license_code` plus the links and credit data a shortlist needs: `source_id, source_url, download_url` (null unless the source allows downloading), `license_url, commercial_license_url, attribution_text` (the same values as `GET /tracks/{id}`). |
| Settings | `GET/PUT /settings` (editable: `default_embedder`, `search.*`, `llm.*`; the view also lists `llm_presets`); `GET /secrets` (names only); `PUT/DELETE /secrets/{name}` |
| Ingest | `POST /ingest/jamendo`, `POST /ingest/local`, `POST /ingest/reprocess` (`embed` or `tag`) → 202 with a job; `GET /jobs`; `GET /jobs/{id}`; `POST /jobs/{id}/cancel`; `GET /jobs/{id}/events` (Server-Sent Events) |
| Analyze | `POST /analyze` (multipart upload, ≤ 50 MB) → BPM, key, loudness and energy. Nothing is stored. |
| Reference song (M10) | `POST /reference` (multipart `file`, same type and size rules as `/analyze`) → `{upload_id, filename, duration_s, model_id}`. The first 4 minutes are embedded with the default embedder (the way catalog tracks are) and the vector, not the audio, is kept in memory. Pass the `upload_id` to `POST /search` (below). 503 without the `ml` extra; 422 for a wrong file type or audio that can't be decoded; 413 over the size limit. |

Errors are JSON `{"detail": "..."}`:

| Code | Meaning |
|---|---|
| 422 | Bad input (also a reference track with no embedding for the current model, a `reference` with both or neither of `track_id` and `upload_id`, or a `reference_weight` outside 0–1) |
| 404 | Unknown id (also an unknown reference `track_id`, or an `upload_id` that expired: the store is lost on restart) |
| 409 | Conflict: a job is already running, a field is pinned by an environment variable, the secret backend is read-only, a reference upload was embedded with another model than the one searched (the default embedder changed since the upload), or there is no labelling pool yet (`/labels/next`, `/labels/pool`, `/labels/progress`: "No labelling pool yet: run mcrar scenes pool") |
| 413 | An upload is over 50 MB (`/analyze`, `/reference`) |
| 503 | Missing prerequisite: no `ml` extra for text search or a reference upload (or for a genre/mood filter when a matching track has no usable stored tags), no Jamendo client id, or no ready LLM for a rerank |
| 502 | Jamendo failed, or the LLM call of a rerank failed |

## Behaviour worth knowing

- **Audio is never re-hosted.** A Jamendo preview is a 307 redirect to a fresh stream URL. The
  URL is looked up again because the stored one expires, and is cached for 30 minutes. It carries
  no client id. A local track is served from the path stored in the catalog, with HTTP Range
  support. No request can name a file to stream.
- **Models.** Every embedder can be selected, including the non-commercial MuQ-MuLan (each
  entry in `GET /settings` carries `commercial_ok` as information). Stored tags count only when
  they come from the tagging model currently selected in `models/registry.json`; tags from an
  older head are ignored until `mcrar tag` re-tags.
- **Tag scores in search results** (the `tags` term, `top_tags` and the explanation) are not raw
  probabilities. Each label is standardised over the catalog and passed through a sigmoid, so
  0.5 means "an average track for this label", and genre and mood scores share one scale. The
  raw stored probabilities are in `GET /tracks/{id}`. A genre/mood filter without text needs no
  `ml` extra when every matching track has stored tags from the allowed model.
- **Game scenes (M9).** `scenes` take the ids, display names or synonyms of the 14 labels of
  `GET /vocab`'s `scene` set (combat, boss, exploration, menu, town, puzzle, stealth, horror,
  victory, defeat, credits, cutscene, chase, ambient); an unknown one is a 422. Like genres and
  moods they are soft: they feed the `tags` term, and the parser also hints scenes from the text
  (`parsed.preferences.scene_hints`, for example "boss fight" or "victory jingle"). Scene tags
  come from a zero-shot model that `mcrar scenes build` creates from text prompts and the
  catalog's own CLAP vectors (two variants, plain and centered; hand labels, see
  `docs/labelling.md`, decide which one is used), then `mcrar tag --label-sets scene` stores
  them; until a track has
  them, its scene score is zero-shot on the fly (needs the `ml` extra). `intensity` sets the
  energy target (`low` 0.25, `mid` 0.5, `high` 0.8) and wins over an energy word in the text
  ("calm"); `scenes` and `intensity` are part of the filters a rating is keyed by (a
  filter-only search).
- **Search by a reference song.** `reference` is exactly one of `{track_id}` (a catalog track,
  which must have an embedding for the current model and is left out of its own results) or
  `{upload_id}` from `POST /reference`. A reference needs no text or filter, and a reference
  track needs no `ml` extra (its embedding is already stored); a text in the same request does.
  Results are ranked by the audio–audio cosine; with text, the semantic weight is split:
  `reference_weight` is the reference's share (1 = reference only, 0 = text only, though the
  reference tracks still join the candidates). Both cosines are min-max scaled over the candidates
  and the breakdown gains a `reference` term. The explanation says "Sounds close to / similar to /
  Loosely like". Filters and relaxation work as for text. A search with a reference has no
  `rating`s (they are filed under text and filters only).
- **Uploaded references are in memory only.** The last 32 uploads are kept (least recently used
  first out) and all are lost on restart, so a client must be ready to upload again after a 404.
  They hold the vector, file name and duration, never the audio.
- **Ingest jobs.** Only one job runs at a time (a second gets 409). A finished job's report
  lists `new_track_ids` (up to 200). Jobs use the same loaded
  model as search.
  - The event stream replays from `Last-Event-ID` or `?after=` and ends with `done`, `failed` or
    `cancelled`.
  - A cancel takes effect at the next track.
  - Without the `ml` extra, an ingest still analyses tracks and reports a `warning` event.
- **Settings** are written atomically to `config/settings.toml`, validated before writing, and
  applied to the running server. Paths, the secrets backend, and the API host and port can't be
  changed over HTTP.
  - **Changing `default_embedder`** unloads the models the server has loaded (the VRAM comes
    back) and loads the new default in the background (`GET /health` shows it as `loading`, then
    `ready`). While an ingest job runs nothing is unloaded; the other models are released when
    the job ends, which also unloads the CLAP model a job loaded for tagging when it is not the
    default. A request that still holds an unloaded model answers 503 ("was unloaded ... try
    again").

## Security model (local desktop use)

The server listens on loopback, but any web page open in the user's browser can still send
requests to `127.0.0.1`. The defences:

- **Host check.** Only loopback names and the configured host are accepted, which blocks DNS
  rebinding.
- **Origin check.** State-changing requests (anything but GET, HEAD and OPTIONS) whose `Origin`
  is not a loopback page get 403.
- **No CORS headers.** Other sites can't read responses.
- **Secrets are write-only over HTTP.** No response, error or log contains a secret value. Job
  errors and events are stripped of URLs and `client_id` values.

**Before hosting it for other people,** the API needs authentication. It also needs
`POST /ingest/local` and `POST /analyze` disabled or sandboxed, because they read the server's
disk, and `GET /tracks/{id}` exposes local file paths.
