# MCRAR: ML music recommender for listeners and indie game devs (implementation plan)

> This is the original plan (approved 2026-10-11), lightly annotated with later results. What has
> actually been built, the decisions taken along the way and the open items are tracked in
> [`docs/STATUS.md`](STATUS.md).
>
> **2026-10-15: `commercial_mode` was removed.** Every model and tagging head is usable, and the
> README will state that the project is not for commercial use because of model and data
> licences. Mentions of commercial mode below are historical. The music licence checks (risk
> badges, "safe for commercial game") are unaffected.

> **2026-10-19: M7 is done** (`docs/llm.md`, STATUS §3.11). The LLM parses each text search and
> reranks the top 20 on request. OpenAI-compatible services come first, then Anthropic. Spotify
> query generation moved to M8, because there was no Spotify code yet.

## Context

This is a greenfield repo: only `README.md`, `LICENSE`, `.gitignore` and `.claude/` exist. The user wants a music recommender that:
1. uses ML to identify a track's characteristics (genre, BPM, mood, …)
2. searches royalty-free music and Spotify for tracks that match the user's input
3. can optionally use an LLM

It should also help **indie game devs** find music they can legally use in their games.

User decisions:
- **Input:** a text description and structured filters. Reference-song search is agreed as a late milestone.
- **Platform:** a desktop app, built so it can be web-hosted later.
- **ML approach:** a mix of pretrained models and our own training. The VRAM cost of each option is weighed in §2.
- **LLM:** prioritize **online APIs with the user's own key**. Local LLMs are heavy on a regular PC, so they stay possible but are not a focus.
- **Commercial status:** "maybe, keep it open". Default to permissively licensed models and data. Non-commercial-only parts are opt-in and gated by a setting.
- **Game-dev scope:**
  - in now: license safety + credits generator
  - wanted, pending a difficulty check (see §6): game-scene tags and indexing the user's own asset packs
  - deferred: loop analysis

---

## 1. Key facts that shape the design

1. **The Spotify API gives no audio and no audio features.** Since Nov 2024, new Spotify apps can't use `audio-features`, `audio-analysis`, `recommendations` or `preview_url`. Since Feb 2026, Development Mode also requires the app owner to have Premium, with about 5 users per new app.
   - ML runs only on audio we can fetch: **Jamendo (API), the user's local folders and asset packs, and later Freesound (API)**.
   - Spotify is a separate, text/metadata-only search with links out. Each user brings their own client ID/secret.
2. **BPM and key use DSP, not ML** (librosa). ML handles genre, mood, game-scene tags and text-to-audio matching.
3. **Ingest → analyse offline → index → query.** Searches run against a pre-built catalog.
4. **A joint text-audio embedding model** lets free text match audio directly. It also enables zero-shot tagging (each tag becomes a text prompt) and reference-song similarity.

---

## 2. ML choices

### 2a. Embedding model: newer than CLAP, chosen by a bake-off

CLAP (2023) is no longer the best option. There are three candidates, all hidden behind an `Embedder` interface. The `embeddings` table keys rows by model id, so switching models only means re-embedding the catalog.

| Model | Year | License | Size / VRAM (inference) | Notes |
|---|---|---|---|---|
| LAION CLAP `larger_clap_music_and_speech` | 2023 | permissive | small, ~0.45 GB in fp16, fine on CPU | **Chosen default (M3a result, see below).** `larger_clap_music` was dropped: its Hugging Face checkpoint maps every prompt to the same embedding. |
| **GLAP** `mispeech/GLAP` (Xiaomi) | 2025 | Apache-2.0 | ~0.9B params, roughly 2–4 GB in fp16; slow on CPU | General audio (music, speech, sound), multilingual queries. Needs `trust_remote_code=True`, so pin the revision. |
| **MuQ-MuLan-large** (Tencent) | 2025 | **CC-BY-NC-4.0** | ~2.65 GB checkpoint, roughly 3–6 GB | Music-specific and the strongest in the recent comparisons I found. **Opt-in only, behind a "non-commercial mode" setting.** Its repo ships a pickle `.bin`, so load it only from a pinned revision. |

**M3a result (2026-10-11):** CLAP is the default (`default_embedder = "clap"`, model id
`clap@195c3a3`). On the owner's blind ratings of 15 game-music searches it tied MuQ-MuLan and
clearly beat GLAP, while being permissive and the smallest. MuQ-MuLan led the automatic benchmarks
and stays available in non-commercial mode. Full numbers: `docs/embedder_bakeoff.md`.

Others noted but not planned:
- CLaMP 3 (2025): better for symbolic/MIDI and multilingual queries.
- AllMusicCaps (2026 preprint): too new to rely on.

**Bake-off (milestone M3a):**
- **Data:** ~50 English test queries (including game-scene queries) over a ~1–2k-track Jamendo sample. Relevance is judged by the user, plus Song Describer / MusicCaps captions.
- **Metrics:** recall@10, nDCG@10, embed throughput on the user's GPU and on CPU, and peak VRAM.
- **Pick:** the best permissive model becomes the default. MuQ-MuLan is enabled only if it wins clearly and non-commercial mode is on.

All VRAM figures are estimates, to be confirmed by M3a measurements.

### 2b. Tagging: the three options, re-evaluated

| | A. Train from scratch (CNN on mel) | B. Pretrained only (zero-shot prompts on the embedding) | **C. Mix (recommended)** |
|---|---|---|---|
| Training VRAM | ~2–6 GB; days on CPU | none | ≈0: MLP heads on embeddings train in minutes on CPU |
| Data | Full audio download, tens of GB | none | Embeddings only |
| Quality | lowest | decent, varies by tag | best: zero-shot where it's good, trained heads where it isn't |
| Learning value | highest | lowest | good |

**Decision: C.**
- Every tag (genre, mood, game scene) starts as zero-shot prompts.
- An MLP head is trained only where it beats zero-shot on the held-out split.
- **A** is an optional learning benchmark (M3c).

### 2c. Datasets: training data vs. what users search

These are different things.
- **The catalog that users search, preview and download** is the live **Jamendo API**, plus local folders and asset packs, plus Freesound later. The datasets below are never shown to users.
- **Training and evaluation data**:
  - **MTG-Jamendo** (2019): old, but still *the* standard mood/genre tagging benchmark; music characteristics don't go stale. Annotations are **CC BY-NC-SA**, so heads trained on it are flagged non-commercial.
  - **JamendoMaxCaps** (2025): 362k instrumental Jamendo tracks with machine-generated (Qwen2-Audio) captions. Useful for extra text-audio evaluation or light alignment fine-tuning later. Check its license before use. Captions are synthetic, so it isn't a gold standard.
  - **Song Describer Dataset** (human captions) and **MusicCaps**: retrieval evaluation.
  - **FMA** (CC-licensed audio): genre heads with a permissive data path.
  - **DEAM**: valence/arousal.
- A `models/registry.json` entry records each head's **data license**. Commercial mode disables NC heads and NC embedders and falls back to zero-shot.

---

## 3. Preview and download (recommended: yes)

- **Preview:** play the source's own stream URL (Jamendo `audio`) in an inline player.
- **Download:** link to the source's official download (Jamendo `audiodownload`, only when `audiodownload_allowed`). Every download includes a license + attribution text file.
  - **Never re-host or cache third-party audio** in the app or a future server.
- **Spotify:** no previews are available through the API any more, so show a link out. Optionally use Spotify's embed widget; check that it works in the desktop webview.
- Local and asset-pack files play straight from disk.

---

## 4. Architecture

```
 Desktop shell (pywebview → WebView2)  ─┐  same React+Vite+TS build is web-hostable
                                        ▼  HTTP (localhost; later HTTPS)
 FastAPI backend (Python 3.11, uv)
  recommend/  parse → retrieve → rank → explain
  llm/        OpenAI-compatible (OpenAI, OpenRouter, Groq, Gemini-compat, … and, for free,
              local Ollama/LM Studio) + Anthropic native; structured JSON; optional
  sources/    jamendo · local_folder (incl. asset packs) · spotify (metadata) · freesound (music-like sounds, M12)
  audio/      decode · BPM · key · energy · duration
  ml/         embedders (CLAP/GLAP/MuQ-MuLan) · zero-shot tagger · heads · eval · bake-off
  licensing/  normalize licenses → {commercial_ok, attribution, share_alike, no_derivs} → risk level; credits export
  catalog/    SQLite + VectorIndex (numpy brute force → hnswlib/sqlite-vec later)
```

**Hosting-readiness rules:**
- The frontend uses HTTP only.
- Config comes from env vars and a settings file.
- Secrets go through `SecretStore`: OS keyring on desktop, env vars when hosted.
- The repository and `VectorIndex` interfaces allow moving to Postgres + pgvector.
- Settings include `commercial_mode`.

**Layout:**
- `backend/src/mcrar/{config,secrets,cli}.py` plus the `audio/ ml/ catalog/ sources/ licensing/ recommend/ llm/ api/` packages
- `backend/tests/`, `frontend/`, `desktop/`, `docs/`
- `data/` and `models/` are gitignored

**Data model (SQLite):**
- `tracks`: source, source_id, title, artist, duration, stream/download URLs, license_url, `license_code`, `risk` (green/amber/red), attribution_text, audiodownload_allowed, source_tags
- `features`: bpm, bpm_conf, key, mode, energy, loudness
- `tag_probs`: head, label, prob, method (zeroshot/head)
- `embeddings`: track_id, model_id, vector
- `projects` and `shortlist_items`: game projects

**Query flow:**
1. Query: text plus filters (genre, mood, game scene, BPM, energy, instrumental, license risk ≤ X, duration) plus an optional reference track.
2. Parse: a rule-based parser by default. With an LLM, a schema-validated JSON parse that falls back to rules on failure.
3. Hard filters in SQL, then embedding top-K (text→audio, or audio→audio for a reference track).
4. Weighted rank with the score breakdown returned.
5. Template explanation, or an LLM rerank of the top 20 plus explanations.
6. Spotify is a separate section and is never mixed into the audio-scored results.

**LLM privacy:** send only the query text and track metadata, never audio or keys. Default to a cheap model, cache parses, and cap tokens.

---

## 4b. Project-local development environment (user requirement)

**Everything that development needs lives inside the repo folder. Nothing is installed or configured system-wide.**

| Thing | Location (all gitignored) | How |
|---|---|---|
| uv binary | `.tools/uv/` | standalone installer with `UV_INSTALL_DIR=.tools/uv` and `UV_NO_MODIFY_PATH=1` |
| Python interpreter | `.tools/python/` | `UV_PYTHON_INSTALL_DIR=.tools/python`, `UV_PYTHON_PREFERENCE=only-managed` (never uses or touches system Python) |
| venv | `backend/.venv/` | uv default |
| uv cache | `.cache/uv/` | `UV_CACHE_DIR` |
| Node.js | `.tools/node/` | official portable Windows zip, no installer |
| npm cache / modules | `.cache/npm/`, `frontend/node_modules/` | `npm_config_cache`; never use `npm -g` |
| ffmpeg (only if needed) | `.tools/ffmpeg/` | portable static build. Prefer `soundfile`, whose wheel bundles libsndfile with MP3 support, so ffmpeg may not be needed at all. |
| Model weights | `.cache/huggingface/`, `.cache/torch/` | `HF_HOME`, `TORCH_HOME` |
| Datasets / catalog DB / trained heads | `data/`, `models/` | config paths are relative to the repo |
| Dev secrets (API keys) | `.secrets/secrets.toml` | `SecretStore` backend `file` is the dev default. The OS keyring backend is opt-in, for the packaged app only, because keyring writes to Windows Credential Manager. |
| Build output | `build/`, `dist/` | PyInstaller |

**Scripts (M0):**
- `scripts/bootstrap.ps1` (plus a `bootstrap.sh` for Git Bash): downloads the pinned versions of uv, Node and ffmpeg (optional) into `.tools/`, **verifies their SHA-256 checksums**, and is idempotent.
- `scripts/dev-env.ps1`: sets the variables above and prepends `.tools/*` to `PATH` **for the current shell session only**. It never uses `setx`, never writes to the registry, and never edits the user profile.
- `scripts/dev.ps1`: runs backend + frontend using the project-local tools.

**Rules for every implementer and agent:**
- Never run `pip install --user`, `npm -g`, `winget`, `choco`, `setx`, or global `uv tool install`.
- Always run commands through `dev-env`.

**Unavoidable system-level pieces**, which already exist on most PCs:
- the NVIDIA GPU driver (PyTorch wheels bundle the CUDA runtime, so no CUDA toolkit install is needed)
- the WebView2 runtime that pywebview uses, which ships with Windows 10/11

Neither gets installed by the scripts. They are only checked for, with a clear message if missing.

---

## 5. Milestones (each is a standalone implementer task)

Every milestone needs:
- ruff and pytest passing
- no network access in unit tests (mocked HTTP; synthetic fixture audio)
- a short note in `docs/`

| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold: **project-local toolchain per §4b** (bootstrap, dev-env, dev scripts); uv project, ruff, pytest; `config.py` (pydantic-settings, incl. `commercial_mode`, all paths repo-relative); `secrets.py` (`file` backend as dev default, `keyring` opt-in); `mcrar` CLI; Vite skeleton; gitignore for `.tools/ .cache/ .secrets/ data/ models/ build/ dist/ *.db` | From a fresh clone, `bootstrap` + `dev-env` lead to `uv run pytest` and `npm run build` passing. `where python` / `where node` outside the dev-env shell are unchanged. Nothing new appears in `%APPDATA%\uv`, `%LOCALAPPDATA%\uv`, `~/.cache/huggingface` or the global npm prefix. |
| M1 | `audio/`: decoding (soundfile, falling back to librosa + ffmpeg); BPM with octave folding and confidence; key via chroma + Krumhansl templates; energy and duration | Synthetic 120 BPM click comes out 120±2; C-major progression comes out as C major |
| M2 | `catalog/` + `sources/jamendo.py` + `sources/local_folder.py` + `licensing/` (details below) | Re-ingest creates no duplicates; the `audiodownload_allowed=false` path is tested; the license mapping has a full table test |
| M3a | `ml/embedders/` (CLAP, GLAP, MuQ-MuLan) behind `Embedder`, with device auto-select, fp16 on CUDA, pinned revisions. NC-licensed models are refused unless `commercial_mode=false`. Bake-off script and report (recall@10, nDCG@10, throughput, peak VRAM) | Report in `docs/embedder_bakeoff.md`; default model set in config |
| M3b | **Handed over to a collaborator: full spec in `docs/handover/M3b-tagging.md`.** Tagging: a zero-shot tagger (prompt sets per label, kept in TOML) plus heads trained on FMA (genre), MTG-Jamendo (mood/theme) and DEAM (valence/arousal) CLAP embeddings, with calibration. Heads are `.npz` with numpy inference; `models/registry.json` records labels, data licence, `commercial_ok` and metrics. A `TaggingStage` (`needs_audio = False`) writes `tag_probs` from stored embeddings | For each label set, the method (zero-shot or head) that wins on the official test split is used, per commercial mode; the logistic-regression baseline is beaten; `docs/model_card.md` written |
| M3c | *(optional, learning; also handed over)* Option A short-chunk CNN on the same FMA split, compared in the model card | Comparison table present |
| M4 | `recommend/`: rule parser, retrieval, weighted rank, explanation. If nothing matches, relax filters one at a time and report which were relaxed | Unit tests on a ~20-track synthetic catalog cover the filters, the license-risk filter, relaxation and score sums |
| M5 | API: `POST /search`, `GET /tracks/{id}`, `GET /tracks/{id}/stream` (redirect to the source or serve a local file), `GET/PUT /settings`, `POST /ingest` (SSE progress), `POST /analyze` (reference upload), project/shortlist CRUD, `GET /projects/{id}/credits` | TestClient tests pass |
| M6 | Frontend: query box and filters (incl. a "safe for commercial game" toggle and duration range); results with inline player, tag chips, score breakdown and a **license badge (green/amber/red) with attribution**; download button where allowed; shortlist/projects; credits export; settings (API keys, commercial mode, ingestion) | Search → preview → shortlist → export credits works end-to-end against a local catalog |
| M7 | LLM (`llm/`), **API-first**: `LLMProvider.complete_json(messages, schema)`; `OpenAICompatProvider` (base_url + key covers OpenAI, OpenRouter, Groq, Gemini-compat and local servers) and `AnthropicProvider`. Uses: query parse, Spotify query generation, top-20 rerank and explanation. Timeouts, validation, fallback. Keys never logged | Fake-provider tests cover valid, invalid and timeout replies; one manual run against a real API key |
| M8 | Spotify (`sources/spotify.py`): Client Credentials with the user's own keys; `/search?type=track`; 429 handling with backoff; disabled cleanly when no keys are set; metadata only | Mocked tests pass; the UI shows a separate section with links out |
| M9 | Game-scene tags (see §6): prompt sets plus a ~200–300-track hand-labelled eval set using a small labelling page in the UI; head trained only if it beats zero-shot | Per-scene precision@10 reported in the model card |
| M10 | Reference song: upload a file or pick a track; audio→audio similarity, optionally blended with text (`α·text + (1−α)·ref`) | API and UI work; covered by tests |
| M11 | Desktop packaging: pywebview launcher, PyInstaller one-folder build, models downloaded on first run with progress, CPU build by default | Packaged app searches on a clean Windows machine |
| Later | Freesound source (API key, license filter); loop-point and jingle-vs-BGM analysis; image/concept-art → music description via a vision LLM; ONNX export to shrink the build | — |

**M2 details:**
- **Jamendo client:**
  - paged `/tracks` with `include=musicinfo licenses`
  - stores the license URL, `audiodownload_allowed` and the stream URL
  - rate limiting plus a disk cache, mindful of the ~35k requests/month free tier
- **Local-folder ingest:**
  - recursive scan of wav, ogg, mp3 and flac
  - a **per-folder license declaration** (a `license.yaml` sidecar, or a choice in the UI on import), for asset packs
- **Licensing:** maps CC0, CC-BY, CC-BY-SA, NC, ND, the Pixabay license and "user-declared" to flags and a risk level, then generates attribution text.
- **Ingest pipeline:** analyse each track, embed it and store it. Idempotent and resumable.

**Dependencies:**
- M0 → M1 → M2 and M3a in parallel
- M3a → M3b → M4 → M5 → M6. M4 runs in parallel with M3b against the interface fixed in the handover spec, falling back to zero-shot tags until the heads land.
- After M5: M7, M8, M9 and M10, each independent of the others
- M11 last
- M3c any time after M3b

---

## 6. Game-dev features: what each involves and how hard it is

- **License safety + credits** (M2 licensing, M6 UI). **Difficulty: low.**
  - Risk levels:
    - **green:** CC0, CC-BY, Pixabay license
    - **amber:** CC-BY-SA, because syncing music to visuals may count as an adaptation
    - **red:** NC and ND
  - The credits export (TXT/JSON/Markdown) is generated per project.
  - Show an "informational, not legal advice" note and link to Jamendo Licensing for commercial licences.
- **Indexing your own asset packs** (inside M2). **Difficulty: low.**
  - It reuses the local-folder ingest. The only new work is the per-folder license declaration and support for game audio formats such as OGG.
  - High value: devs can search their Kenney, OpenGameArt, Humble and asset-store packs by description.
- **Game-scene tags** (M9). **Difficulty: medium.**
  - Example tags: combat, boss, exploration, menu/title, town/shop, puzzle, stealth, horror, victory/defeat jingle, credits, plus an intensity level.
  - The zero-shot prompts are easy. The real work is quality checking: no public dataset has these labels, so ~200–300 tracks need hand-labelling for evaluation. A head is trained only if it beats zero-shot. This is a good learning exercise.
- **Defaults that help game devs** (cheap to add to M4 and M6):
  - an **"instrumental only"** filter
  - duration filters (jingle < 15 s, BGM > 60 s)
  - a "**soundtrack cohesion**" mode: given one picked track, find others near it in embedding space but at a different intensity or scene, for a consistent soundtrack
- **Deferred:** seamless loop-point detection (beat-aligned end-to-start similarity). Exporting trimmed loops is a modification, which red/ND licenses forbid.

---

## 7. Risks

- Spotify policy keeps tightening, so Spotify stays isolated and optional.
- Embedder licenses (MuQ-MuLan is NC) and dataset licenses (MTG-Jamendo is NC) are enforced through `commercial_mode` and the registry.
- GLAP and MuQ-MuLan load with remote code or pickle files: pin revisions and never auto-update.
- BPM octave errors: show confidence and accept ×2 and ×½ tempos when confidence is low.
- License risk levels are guidance only, so every tracked license links to its source page.

## 8. Verification (end-to-end)

0. Fresh clone, then `scripts/bootstrap.ps1`, then `. scripts/dev-env.ps1`. The toolchain should come only from `.tools/`, and no files should appear outside the repo, apart from the browser/webview's own profile.
1. Run `uv run pytest` and `ruff check` in `backend/`, and `npm run build` in `frontend/`.
2. `mcrar ingest jamendo --tags lofi,rock,ambient,electronic,chiptune,orchestral --limit 300` and `mcrar ingest local <asset-pack folder>`: the row counts in all tables match, and every track has a risk level.
3. `docs/embedder_bakeoff.md` and `docs/model_card.md` exist with real numbers, and the default embedder matches the bake-off winner.
4. Run these queries in the UI and check the top 10 by listening:
   - "calm piano for studying under 90 BPM"
   - "tense stealth level, no vocals"
   - "8-bit boss battle"
   - "cozy town theme"
   - also with "safe for commercial game" on: no red tracks appear
5. Shortlist 5 tracks, export the credits, and check the attribution text and license links. Download is offered only where allowed.
6. Without an LLM key, everything works. With an API key, the parsed JSON appears in the debug panel and explanations show up.
7. With Spotify keys, a separate section with links out appears. Without them, it is hidden and there are no errors.
8. ~~Toggle commercial mode~~ (removed 2026-10-15): switching the default embedder to MuQ-MuLan and back works, and search still works.
9. Install the packaged Windows build on a clean machine and repeat step 4.
