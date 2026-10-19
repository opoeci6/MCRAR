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
| Meta | `GET /health`, `GET /vocab` (genre and mood labels for filters), `GET /stats` |
| Search | `POST /search` `{text?, filters{max_risk, vocal, bpm_min/max, duration_min_s/max_s, sources, genres, moods}, limit, offset, explain}` → results with a score breakdown, explanation and the stored `rating` (0–2 or null) for this query, plus `match: {top_cosine, weak}` (the raw text–audio cosine of the best hit, and whether it is below `search.weak_cosine`, by default 0.40 for CLAP and MuQ-MuLan, none for GLAP); `POST /search/import` `{text, filters, limit 1–100 = 50}` → 202 with an `ingest-query` job that searches Jamendo for the query and imports up to `limit` tracks not yet in the catalog (embedded with the default model and CLAP, then tagged) |
| LLM (M7, optional; see `docs/llm.md`) | `GET /llm` → `{enabled, ready, preset, label, kind, model, reason, rerank_top_n}`, where `reason` is `disabled`, `missing_model`, `missing_key` or null. `POST /llm/test` `{preset?, model?, base_url?}` → always 200 with `{ok: true, model, elapsed_ms}` or `{ok: false, error}`; it tests unsaved values too. `POST /search/rerank` takes the `/search` body (text required) → the same response shape, with the top `llm.rerank_top_n` results in the LLM's order, each item's `llm_rank` and `llm_explanation`, and `rerank: {model, verdict: good\|partial\|poor, summary, search_terms, elapsed_ms}`. It answers 503 when no LLM is ready and 502 when the LLM call fails. Every `/search` response also has `parsed.source` (`rules`/`llm`), `parsed.search_terms` and `llm: {used, model, cached, error} \| null` |
| Ratings | `PUT /ratings` `{text?, filters?, track_id, rating: 0\|1\|2}`; `DELETE /ratings` (same body without `rating`); `GET /ratings?limit&offset`. A rating is keyed by the lowercased query text, or by canonical filters for a filter-only search. |
| Tracks | `GET /tracks?source&risk&limit&offset`; `GET /tracks/{id}`; `GET /tracks/{id}/stream`; `GET /tracks/{id}/credits?format=txt\|md\|json` |
| Projects | `GET/POST /projects`; `GET/PATCH/DELETE /projects/{id}`; `GET /projects/{id}/items`; `PUT/DELETE /projects/{id}/items/{track_id}` (with an optional note); `GET /projects/{id}/credits?format=` |
| Settings | `GET/PUT /settings` (editable: `default_embedder`, `search.*`, `llm.*`; the view also lists `llm_presets`); `GET /secrets` (names only); `PUT/DELETE /secrets/{name}` |
| Ingest | `POST /ingest/jamendo`, `POST /ingest/local`, `POST /ingest/reprocess` (`embed` or `tag`) → 202 with a job; `GET /jobs`; `GET /jobs/{id}`; `POST /jobs/{id}/cancel`; `GET /jobs/{id}/events` (Server-Sent Events) |
| Analyze | `POST /analyze` (multipart upload, ≤ 50 MB) → BPM, key, loudness and energy. Nothing is stored. Reference-song similarity is M10. |

Errors are JSON `{"detail": "..."}`:

| Code | Meaning |
|---|---|
| 422 | Bad input |
| 404 | Unknown id |
| 409 | Conflict: a job is already running, a field is pinned by an environment variable, or the secret backend is read-only |
| 503 | Missing prerequisite: no `ml` extra for text search (or for a genre/mood filter when a matching track has no usable stored tags), no Jamendo client id, or no ready LLM for a rerank |
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
