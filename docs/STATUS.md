# Project status and decision log

The living record of what MCRAR has done, what was decided and why, what is open, and what
exists only on the owner's machine. `docs/PLAN.md` is the plan; this file is the state.
**Update it whenever a milestone lands or a decision is made.**

Last updated: 2026-10-28.

## 1. Milestones

| # | Status | Where | Notes |
|---|---|---|---|
| M0 Scaffold + project-local toolchain | Done | `dev` | uv 0.13.0, Node 24.21.0, Python 3.11 under `.tools/`; `mcrar doctor` |
| M1 Audio analysis | Done | `dev` | `mcrar analyze`; analysis version `audio-v2` (energy recalibrated, §3.4) |
| M2 Catalog, Jamendo + local ingest, licensing | Done | `dev` | `mcrar ingest jamendo/local`, `mcrar catalog …` |
| M3a Embedders + bake-off | Done | `dev` | Default embedder `clap@195c3a3`; report in `docs/embedder_bakeoff.md` |
| M3b Tagging | Done (PR [#3](https://github.com/opoeci6/MCRAR/pull/3), merged 2026-10-12) | `dev` | By collaborator NineJZ356 with Codex. `mcrar datasets/tagging/tag`; results in `docs/model_card.md`; see §3.7 |
| M3c CNN baseline (optional) | Not done | — | The collaborator skipped it; unassigned |
| M4 Search and ranking | Done | `dev` | `mcrar search`; ingest embeds by default |
| M5 API | Done (2026-10-14) | `dev` | `mcrar serve`; routes, security model and limits in `docs/api.md`; see §3.8 |
| M6 UI | Done (2026-10-15) | `dev` | React UI served by `mcrar serve` at `/`; result ratings; see §3.9 |
| M7 Optional LLM | Done (2026-10-19) | `dev` | A query parse on every text search, a top-20 rerank on click. OpenAI-compatible presets plus Anthropic; `docs/llm.md`; see §3.11 |
| M10 Reference song | Done (2026-10-26) | `dev` | "Find similar" on a result, or upload a song; blends with a text. `POST /api/reference`, `mcrar search --like`; see §3.12 |
| M9 Game-scene tags | Done (2026-10-28) | `dev` | 14 scenes, scene and intensity filters, Labelling tab, `mcrar scenes …`; 269 hand-labelled tracks (owner and Simon); the trained hybrid head `scene-logreg-hybrid@5f5ba48` is selected (cross-validated mean P@10 0.414 against 0.407 for the centered zero-shot). See §3.13 |
| QoL batch 1 | Done (2026-10-27) | `dev` | Projects entries like result rows, notes with timestamps, source label, model switch status and VRAM release, repeat; see §3.14. Then tempo readings, tag chips in words, torch caches (§3.15) |
| QoL batch 2 | Done (2026-10-28) | `dev` | Library search, drop a song to find similar, add tracks by link, and the review fixes (search import per source and by Source filter); see §3.17. The local-music picker and drop follow after the demo |
| M8 Spotify section | **On hold (2026-10-27)**: the owner will discuss it with the collaborator | — | Spotify facts and the owner's choices in §3.1; other platforms in §5.3 |
| M12 Freesound | Done (2026-10-28) | `dev` | Music-like sounds from Freesound: Library tab, `mcrar ingest freesound`, and "search for more" on Jamendo and Freesound; see §3.16 |
| M11 | Not started | — | See `docs/PLAN.md` §5 |

Test suite on `dev`, counted after M12 (2026-10-28):
- Backend, default env: 2,340 passed, 30 skipped.
- Without the `ml` extra (as CI runs it): 2,337 passed, 31 skipped.
- 29 real-model tests run with `-m models`.
- Frontend: 487 vitest tests, plus oxlint and the build. CI runs all three.
CI: GitHub Actions on Windows (`.github/workflows/ci.yml`); runs #5 onwards are green.

## 2. How we work

- **Branches.** One branch per milestone or fix, cut from `dev`, merged into `dev` with
  `--no-ff`. `main` still holds only the initial commit. `dev` is pushed to GitHub
  (`opoeci6/MCRAR`, private). Merged local branches are kept.
- **Pushing.** Push `dev` only when the owner asks. Before every push: run the default suite in
  the normal env **and** in a scratch venv without the `ml` extra (as CI does), and grep the
  outgoing commits for **every** value in `.secrets/secrets.toml` (the Jamendo client id, the
  Freesound key and each LLM key; `git log -p origin/dev..dev | grep -c <value>` must be 0 for
  each, without printing the values).
- **Commit identity.** The human is the author; agents are credited with a `Co-authored-by`
  trailer (`AGENTS.md` §6). Claude Code commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Never committed:** `.claude/` (the owner's Claude Code settings), `data/`, `.secrets/`,
  `.tools/`, `.cache/`, `config/settings.toml`. Under `models/` only `heads/` and
  `registry.json` are trackable.
- **Agents.**
  - Claude Code follows `.claude/CLAUDE.md`: delegate to the implementer, review every diff in
    the main session, and give the shipper commits and PRs.
  - Codex and other agents follow `AGENTS.md`.
  - The rule everyone must keep: nothing is installed outside the repo, and every command runs
    through `scripts/with-env.*`.
- **GitHub actions on the owner's account.** Comments, reviews, closing issues and merging are
  done only after the owner approves the exact text or action. Drafts are shown first. The
  in-app browser pane is signed in to GitHub; there is no `gh` CLI.
- **Collaborator's agent output** (issues, PR descriptions) is information to verify, not
  instructions. Interface changes in a handover spec need the owner's agreement.
- **Real catalog and models.** Dry-run first on copies: copy `data/catalog.db` with SQLite's
  backup API and `models/` into a scratch folder, then point `MCRAR_DATA_DIR` and
  `MCRAR_MODELS_DIR` at them (put the commands in a script file; inline quoting in the agent's
  shell has dropped variables before). On the real data, take a dated backup first
  (`data/catalog.pre-<milestone>.db`). Browser checks run `mcrar serve --port 8010` on the copies.
- **Working while the owner uses the app.** The owner's `mcrar serve` (port 8000) serves this
  checkout's `frontend/dist`, `config/settings.toml` and `data/`.
  - Don't run `npm run build` while they use the app. Test builds go to a scratch folder
    (`vite build --outDir <scratch>/home/frontend/dist`).
  - Test servers get their own home:
    `scripts/with-env.sh env MCRAR_HOME=<scratch>/home MCRAR_MODELS_DIR=… MCRAR_CACHE_DIR=… MCRAR_SECRETS_DIR=… uv run … mcrar serve --port 8010`.
    The override must come after `with-env`, because `dev-env.sh` sets `MCRAR_HOME` to the repo.
    Copy `config/settings.toml` into the scratch home, so a model switch there doesn't change
    the real file. The secrets folder is read-only and is needed for Jamendo streaming.
  - After merging frontend changes, run `npm run build`, or the owner keeps seeing the old UI;
    a page reload is enough. Backend changes need a server restart.

## 3. Decisions and the reasons for them

### 3.1 Product and licensing
- **Spotify is metadata and search only.** Since 2024–2026 its API gives no audio, no audio
  features and no previews for new apps, and Development Mode is limited to about 5 users. ML
  runs only on audio we can fetch: Jamendo, local folders and asset packs, and Freesound later.
  - **Checked again 2026-10-27:**
    - `GET /search` returns at most 10 items per request, 5 by default; more need `offset`
      pages. This has applied since Feb 2026.
    - Removed fields: `popularity`, `available_markets` and `linked_from` on tracks, `label` on
      albums, and `followers` on artists.
    - The batch `GET /tracks`, `/artists` and `/albums` are gone; `GET /tracks/{id}` remains.
    - A Development Mode app works only while its owner has Premium.
    - Since July 2026, quotas count per developer account, and a 429 may carry
      `reason: "QUOTA_EXCEEDED"`.
  - **Owner's choices for when M8 resumes:**
    - the section loads on click ("Show matches on Spotify"), never with every search;
    - link out only, no embed player;
    - the keys come from someone with Premium (the owner has none), entered by the human.
- **No commercial mode (since 2026-10-15).** It used to default to on and refuse anything
  trained on or calibrated with non-commercial data (MuQ-MuLan weights, MTG-Jamendo and DEAM
  labels). The owner removed it: every model and head is usable, and the README will say the
  project is not for commercial use (for example hosting it as a service) because of those
  licences. `commercial_ok` stays in the registries as licence information. A leftover
  `commercial_mode` line in `config/settings.toml` is ignored and dropped on the next save.
- **Licence risk for game use** (`mcrar.licensing`):
  - green: CC0, PDM, CC BY, Pixabay
  - amber: CC BY-SA, Free Art License (share-alike may reach a game)
  - red: any NC or ND
  - unknown: unparseable

  It is guidance, not legal advice, and every track links to its licence. Search never relaxes
  the licence filter, and when the UI limit and a phrase in the text disagree, the stricter one
  wins.
- **The LLM is optional and API-first** (the user's own key; local models are too heavy for a
  regular PC). It was built in M7 (§3.11). OpenAI-compatible services come first, then
  Anthropic.

### 3.2 Embedding model (M3a, 2026-10-11)
- **CLAP won:** `laion/larger_clap_music_and_speech` at revision `195c3a3`, model id
  `clap@195c3a3`. On the owner's blind ratings of 15 game-music searches (88 tracks, 100%
  coverage), CLAP scored 1.40/2 and tied MuQ-MuLan (1.33, not significant); both beat GLAP
  (0.60). CLAP is also permissive and the smallest (0.45 GB VRAM in fp16).
- **The automatic benchmarks disagreed.** Song Describer R@10 ranked MuQ-MuLan 0.42 > GLAP 0.36 >
  CLAP 0.32; the Jamendo genre-tag check ranked MuQ-MuLan 0.54 > CLAP 0.29 > GLAP 0.17. The human
  ratings decided, per the rule in the bake-off report.
- **`laion/larger_clap_music` is broken on Hugging Face:** `logit_scale` loads as 1.0 and every
  prompt gets the same embedding. A real-model regression test guards against this kind of
  collapse.
- **MuQ-MuLan** stays available as a non-default option (non-commercial weights).
- **Pins:** torch is 2.11 (cu130) because torchaudio, which GLAP and MuQ need, stopped at 2.11.
  transformers is below 5 because muq breaks on 5.x.

### 3.3 Jamendo facts (measured)
- **Size:** about 856k tracks; only about 18% (155k) allow commercial use and modification
  (`--commercial-only` maps to `ccnc=false&ccnd=false`). About 20% offer a paid licence
  (`prolicensing`), and its URL is shown even on red tracks.
- **Empty pages:** the API sometimes returns an empty page for a query that has results seconds
  later. The first page is retried up to 3 times (2, 4, 8 s); one retry was not enough. Example
  tags that returned little: `epic` (0), `suspense` (4).
- **Stream URLs** carry signed, per-track `from=` tokens and may expire. They are refreshed with
  `get_tracks` before downloads. Download URLs have no token and are used for links.
- **Quota:** the free tier allows about 35k API requests a month; a usage counter lives in
  `.cache/jamendo/usage.json`. Audio downloads don't count.
- **The client id is a secret:** it is redacted in logs, errors, the cache and httpx's own log.

### 3.4 Audio analysis
- BPM is folded into 70–180. Tempo confidence is 0.6–0.95 on synthetic clicks but 0.2–0.6 on
  real music, which matters for any threshold.
- **Energy recalibrated to `audio-v2`** on 190 Jamendo tracks across 16 genres. Loudness maps
  −30…−8 LUFS and onset rate maps 3…7 per second. The 10th–90th percentile of energy went from
  0.49–0.80 to 0.30–0.83, and genre order is kept (classical about 0.30, techno about 0.82).
- Decoding uses soundfile only; the system ffmpeg is deliberately not used. Example of a
  rejected file: a FLAC whose header claims 74 minutes in 27 MB.

### 3.5 Search (M4)
- **Parsing:**
  - Hard filters from text: BPM, vocals, duration and jingle, licence phrases.
  - Soft preferences: energy and tempo words, genre and mood labels from the vocabulary.
  - The rest of the text is the semantic query.
- **Ranking:**
  - weighted terms: semantic 0.6, tags 0.2, BPM 0.1, energy 0.1; only active terms count, and
    the contributions sum to the score
  - ties break green-licence first, then by id
  - the per-artist cap (2) demotes tracks instead of dropping them
- **Relaxation order:** duration, then BPM (to a soft target), then vocals. The licence filter
  and the source filter are never relaxed.
- **Unknown values pass filters.** Tracks with an unknown vocal flag or duration pass, because
  local asset packs never have a vocal flag.
- **Tag scores are standardised per label** (2026-10-15).
  - Zero-shot cosines and stored M3b `tag_probs` alike become a z-score over the catalog, passed
    through `sigmoid(1.7 z)`. For stored tags, the z-score is over the tracks tagged by the
    allowed model, with a missing label counting as 0. Stored rows win when present.
  - Why: raw probabilities had very different scales per label set. The commercial zero-shot
    mood head gives 0.6–0.97 for nearly everything, calibrated MTG mood probabilities are low
    by base rate, and the genre head is peaky. So one set dominated the tag term, and stored and
    zero-shot scores did not mix.
  - The stored statistics are cached against a cheap signature of the head's rows (count, max
    rowid, sum of probabilities). Computing them for the mood head takes about 0.35 s on the
    real catalog.
- **Filter-only genre/mood search needs no torch** when every track in the pool has stored tags
  from the allowed model. The text model (zero-shot) is loaded only for an embedded pool track
  without usable stored tags; without the `ml` extra that is a 503.
- **Ingest** embeds with `default_embedder` by default (`--no-embed` to skip) and appends M3b
  tagging stages through one guarded import.
- **Result quality** on the owner's 15 rated searches. Method: run each query text through the
  search over the whole catalog, take the top 2, and average the owner's ratings of the hits
  that were rated. Unrated hits are left out and counted.

  | Ranking | Top-2 mean | Rated / unrated hits |
  |---|---|---|
  | M4: zero-shot tags only, before M3b tagged the catalog | 1.35 | 23 / 7 |
  | Stored raw probabilities (M3b tags, until 2026-10-15) | 1.22 | 23 / 7 |
  | Stored, standardised per label (zero-shot mood head) | 1.25 | 24 / 6 |
  | Same, with the MTG mood MLP after commercial mode was removed (current, 2026-10-15) | 1.32 | 22 / 8 |

  - For comparison, CLAP alone scored 1.40 on its own top 2 in the bake-off.
  - The sample is small: each step is one or two tracks changing.
  - Reranking only each query's rated candidates gives 1.40 for every variant, because the text
    match decides the top 2 there.

### 3.6 CI and tests
- CI runs on Windows without the `ml` extra. The tests force Typer's plain output
  (`_TYPER_FORCE_DISABLE_TERMINAL`), because Actions makes Typer emit colour codes. Tests that
  fake models also fake torch availability.
- `import mcrar.cli` must not load librosa, scipy, torch or sklearn (a fresh-process test
  enforces it); heavy imports go inside the commands.
- CLI output that may hold titles or paths goes through `mcrar.console.echo`. Piped output on
  Windows uses the locale code page (GBK on the owner's machine), and plain `typer.echo` crashed
  `mcrar tag` on a title with "É".

### 3.7 Tagging (M3b, 2026-10-12)
- All heads read stored `clap@195c3a3` vectors. Runtime is numpy only, so `mcrar tag` needs no
  network, audio or torch. Artifacts are `.npz` files under `models/heads/`, listed in
  `models/registry.json` with content-derived ids and data licences.
- **Selection** (the best test-split primary metric; until 2026-10-15 commercial mode fell back
  to `moodtheme-zeroshot-unsupervised@15d3513` and had no valence/arousal):

  | Label set | Selected head |
  |---|---|
  | genre (FMA) | `genre-logreg@2b67df0`, macro F1 0.51 |
  | mood/theme (MTG) | `moodtheme-mlp@b2ac67d`, PR-AUC 0.14 (zero-shot: 0.08) |
  | valence, arousal (DEAM) | MLP, R² 0.67 / 0.69 (shown in the track drawer, not used in ranking) |

- The genre MLP did not beat logreg on macro F1 (0.508 vs 0.511), so the rule selects logreg.
- On the owner's catalog, genre top-1 agrees with the uploaders' Jamendo genre tags on 66% of
  844 comparable tracks. The main confusions are classical/folk → instrumental and hip-hop/pop →
  electronic.

### 3.8 HTTP API (M5, 2026-10-14)
- **Shape.**
  - `create_app()` factory; a lifespan owns one `AppState` (catalog, `ModelPool`,
    `SearchService`, `JobManager`).
  - Sync endpoints run on the threadpool. That is safe because the repository and the search
    service lock their shared state.
  - The pool loads each model once and serialises calls to it, and search and ingest jobs share
    that one loaded model.
- **Local-only security.**
  - Host allow-list (against DNS rebinding) and a loopback-`Origin` check on state-changing
    requests.
  - No CORS; the dev UI goes through the Vite proxy.
  - Secrets are write-only over HTTP.
  - Hosting for others needs authentication first, and `ingest/local` and `analyze` turned off
    (`docs/api.md`).
- **Tag versions.** Stored tags count only when their `model_version` is the registry entry
  currently selected, so tags from a replaced head stop ranking until `mcrar tag` re-tags.
- **Never re-host audio.** Jamendo previews are 307 redirects to a fresh URL, which carries no
  client id. Local files are served from the catalog path, with Range support.
- **Ingest jobs.**
  - One at a time. Cancel works by raising from the progress callback, because the pipeline
    has no cancel token.
  - Server-Sent Events with replay.
  - `ingest.stages.build_stages` is shared with the CLI.
- **End-to-end on a copy of the real catalog** (24/24 checks):
  - text search 0.1–0.2 s with CLAP warm
  - stream 307 with no `client_id`
  - local ingest, then a Range 206 on the file
  - project credits
  - settings round trip
  - Jamendo ingest over SSE, 409 on a second job, and cancel
  - foreign `Host` gets 400 and a foreign `Origin` gets 403
  - no secret in the server log

### 3.9 UI and ratings (M6, 2026-10-15)
- **Owner's choices:**
  - a clean look that follows the system light or dark theme
  - English only, with all text in `strings.ts` modules so a translation can be added later
  - result ratings as a real user feature, stored locally
- **Stack.** React 19 with no UI kit, router or data-fetching library.
  - Pages are hash tabs: Search, Projects, Library, Labelling (M9) and Settings.
  - There is one typed API client in `frontend/src/api/`.
  - Styling is CSS Modules with design tokens on `:root`, redefined for dark mode.
  - Tests use vitest, jsdom and Testing Library.
- **Audio is never fetched in JavaScript.** One `<audio>` element plays
  `/api/tracks/{id}/stream`, which redirects to Jamendo or serves the local file.
- **Download** opens the source's own download page and also saves the track's licence file
  (`/api/tracks/{id}/credits?format=txt`).
- **Ratings** ("Not a fit / OK / Good fit", stored as 0/1/2).
  - Storage: a `ratings` table, added by catalog migration v2.
  - Key: the lowercased, whitespace-collapsed query text; a filter-only search uses canonical
    filter JSON instead.
  - The UI rates against the exact request that produced the results, not the edited form.
  - `mcrar ratings import` loaded the 88 listening-test ratings in testing.
  - `mcrar ratings eval` reproduces the 1.25 top-2 mean (24 rated / 6 unrated) on a copy of the
    catalog.
- **Query text is lowercased before embedding.** CLAP's text encoder is case-sensitive:
  "Tense stealth level" and "tense stealth level" gave completely different top results. The
  rated queries were all lowercase, so the benchmark is unchanged.
- **End-to-end in the built-in browser,** on a copy of the real catalog with `mcrar serve
  --warm`:
  - text search in about 0.6 s cold and 70 ms warm
  - a rating that persists for the same query
  - Jamendo preview playback through the redirect
  - "safe for commercial game" leaving only green results
  - creating a project from the result menu
  - the risk summary with the restricted warning
  - credits md export with the full attribution lines
  - a Jamendo ingest of 3 tracks with live progress
  - cancelling a 15-track ingest after 2 tracks
  - the commercial-mode round trip with confirmation (the mode was removed afterwards)
  - the secret never shown
  - dark mode: body text at 15.7:1 contrast and badges at 9.6:1

### 3.10 After M6 (2026-10-15)
- **`frontend/src/lib/` was never committed.** The Python template's `lib/` rule in `.gitignore`
  hid it, so a fresh clone of the M6 UI could not build. It is now un-ignored and tracked.
- **Licence card.** The credit line's URLs are links, the card no longer selects as a whole, and
  a "Copy credit" button copies the line.
- **HTML entities in Jamendo names.** The API sends names like "Jazyus &amp; EdSeGaMe".
  - `parse_track` now decodes the title, artist and album.
  - Catalog migration v3 decodes the stored names.
  - v4 decodes the stored credit lines and accents such as `&eacute;`, without decoding
    anything twice.
- **Commercial mode removed** (§3.1). The real catalog was re-tagged with the selected heads, and
  the top-2 mean rose to 1.32 (§3.5).
- **Per-query Jamendo import.**
  - **The weak-match signal.** The ranked scores are min-max normalised (the top hit is always
    1.0), so search now also returns `match: {top_cosine, weak}`, the raw CLAP cosine of the
    best hit. Its threshold is `search.weak_cosine`, by default 0.40 for CLAP and for
    MuQ-MuLan, and none for GLAP.
    - **Calibration** (raw top-1 cosine on the 1,054-track catalog): the 15 rated game-music
      queries scored 0.41–0.66. Clearly weak queries scored lower: "intense fight" 0.32, "anime
      opening" 0.37, "bagpipes" 0.39.
    - **J-pop isn't caught.** "j-pop" scores 0.57 and "japanese vocal" 0.47, because CLAP can't
      tell J-pop from pop. That is why the button is also always shown. A better weak-match
      judgment is a job for M7 (the LLM).
    - **MuQ-MuLan** (same queries): it scores "j-pop" lowest of all (0.38, "anime opening" 0.40,
      "japanese vocal" 0.45), but 5 of 18 good queries also fall under 0.40, as low as 0.32.
      0.40 was chosen anyway, because the notice is only a suggestion and missing a weak search
      costs more than an extra notice.
    - **GLAP's** cosines all sit near 0 (−0.07 to 0.11) and carry no signal, so it has no
      threshold.
  - **Jamendo queries** (`recommend/jamendo_query.py`), from a live check of the API:
    - `search=` is full-text over names and tags and works well. "j-pop" returns generic pop,
      but "jpop" works, so short hyphenated compounds are joined.
    - `lang=` fails with an internal error, so no language filter is sent.
    - The queries, in order: the normalised text, the original text, then the content words as
      `fuzzytags`. Each carries the vocal, duration and green-licence filters.
  - **The pipeline** (`ingest_jamendo_queries`) skips tracks already in the catalog before any
    download and stops after 50 new ones.
  - **The job** embeds with the default embedder and CLAP (tags need CLAP), then tags.
  - **The UI.** A weak result shows a notice with "Search Jamendo for more"; otherwise the
    button sits under the results of every text search. While the job runs, its progress shows
    inline with Cancel. When it finishes, the search re-runs and the new tracks are marked "New".
  - **End-to-end on a catalog copy:**
    - "j-pop": 50 new tracks in 145 s, 0 failures. A Japanese track ranked first, but only 2 of
      the top 20 were new.
    - "japanese vocal": 10 of its top 20 were new.
    - "anime opening" showed the weak notice. Cancelling its import after a few seconds kept 6
      tracks, and the search re-ran.
    - The licence card links opened, and the server log had no client id.

### 3.11 Optional LLM (M7, 2026-10-19)
Details are in `docs/llm.md`.
- **Owner's choices:**
  - OpenAI-compatible services come first: OpenAI, DeepSeek, SiliconFlow, Z.AI, OpenRouter,
    Gemini and Groq through their OpenAI endpoints, plus "Other" for Ollama, LM Studio and
    regional endpoints. Anthropic comes second.
  - The parse runs automatically; the rerank runs on click.
  - Default models: `gpt-6-luna` (cheap and more capable than `gpt-5-nano`), `glm-5.3-flash`
    (cheaper than `glm-5.2`) and `claude-haiku-5-5`.
- **Providers.**
  - The OpenAI-compatible provider uses plain httpx. Anthropic uses the official `anthropic`
    SDK (1.15, which brings in `httpx2`).
  - Each preset has its own key secret, `llm_api_key_<preset>`, read on every call, so a saved
    key works without a restart.
  - JSON mode steps down (`json_schema` → `json_object` → none) when a service rejects it.
  - Model-specific flags are sent only with the preset's default model. Examples: DeepSeek's
    `thinking: disabled`, and `reasoning_effort: none` for `gpt-6-luna`, which has no "minimal".
    GLM-5.3 can't turn thinking off.
- **The parse never overrides the rules.**
  - UI filters, rule constraints, the licence and the sources stay as they are.
  - The LLM adds an English `semantic_text`, so other languages work, plus genre and mood
    hints, energy and tempo preferences, vocal and duration filters only where none were set,
    and Jamendo `search_terms` (used first by "Search Jamendo for more").
  - Results are cached per query and filters. A failure falls back to the rules with a note
    and is remembered for 60 s.
- **The rerank** reorders only the results that already passed the filters. It adds an
  explanation per track and a verdict; "poor" suggests a Jamendo import. Titles and tags are
  sent as data, never licence data, URLs or ids.
- **Search terms in the "j-pop" case.** For "j-pop" the LLM gives `jpop`, `japanese pop`,
  `anime pop`. The rerank's verdicts were honest: "partial" for "j-pop", because the catalog has
  no real J-pop.
- **End-to-end check** on a catalog copy with the owner's OpenAI key and `gpt-6-luna`:
  - **Speed:** the connection test took 2.1 s. A first parse adds about 3 s to a search, and a
    cached one about 0.1 s. A rerank of 20 takes about 5 s.
  - **A Japanese query** (日本のアニメのオープニング曲) was read as "Energetic Japanese anime
    opening theme ...", with search terms `anime`, `jpop`, `jrock`.
  - **"tense stealth level, no vocals"** kept the rule-parsed instrumental filter. The LLM added
    Dark, Soundscape and Game moods.
  - **In the UI:** the rerank showed an explanation per track, and Undo restored the order.
  - **Key check:** no key-like string appeared in the server log, in `/api/settings`,
    `/api/secrets`, `/api/llm`, or in the page.
- **Ratings eval: undecided.**
  - `mcrar ratings eval` (top-2 mean) gave 1.32 for rules (22 rated hits, 8 unrated).
  - With `--llm` it gave 1.40, but on only 5 rated hits, with 25 unrated.
  - The LLM's English rewrite changes the CLAP results so much that most hits were never rated,
    so the two can't be compared yet. See §5.2.
- **Model list (2026-10-20, the owner's request).** Settings → LLM has a "Load models" button
  (`POST /api/llm/models`, `mcrar llm models`), and the model field suggests the loaded names
  while still taking any typed name.
  - It is fetched only on click.
  - Non-chat models are hidden by id patterns, plus OpenAI-only ones (legacy completion models,
    codex, `-pro`, sora). With the owner's key, OpenAI listed 64 models.
  - Z.AI documents no list endpoint and is untested.
- **Player bar (2026-10-20).** Below 1,100 px the seek bar moves to a second row; before, it
  collapsed into the volume control. Below 560 px the badge gets a row too.
  - Checked at widths from 1,400 px down to 400 px: nothing overlaps and the bar never
    overflows.
  - A related fix: below 1,000 px the page's bottom padding no longer drops to 40 px, which
    had hidden the last rows behind the bar.

### 3.12 Reference song (M10, 2026-10-26)
- **How it ranks.** A reference song is a new rank term, `reference`: the min-max scaled
  audio-audio cosine. It shares the semantic weight with the text. With both, the text gets
  `W·(1−w)` and the reference `W·w`, where `w` is `reference_weight` (default 0.5, the UI
  slider). Alone, it gets all of `W`. `SearchWeights` is unchanged.
  - The pool is the union of the text's and the reference's top lists; every pool track gets
    both cosines. A picked track is left out of its own results.
  - The weak-match notice is for text only (its 0.40 is a text-audio threshold).
- **Where the reference comes from.**
  - A catalog track (`reference: {track_id}`): its stored vector, so no torch is needed.
  - An upload (`POST /api/reference`): embedded once with the default embedder and kept in an
    in-memory LRU of 32 (lost on restart). Searches name its `upload_id`. An unknown id gives
    404 and a changed model 409; the UI then clears the reference and asks for the upload again.
  - One recipe (`embed_audio_source`: first 240 s, 3 windows) is shared by ingest, uploads and
    `--like-file`, so uploaded and stored vectors match.
- **Wording bands, measured on the catalog** (1,054 tracks). Audio-audio cosines sit on a
  different scale per model, so "Sounds close to / similar to / Loosely like" uses per-model
  bands (`REFERENCE_BANDS` in `recommend/explain.py`): CLAP 0.80 / 0.65, GLAP 0.93 / 0.88,
  MuQ-MuLan 0.80 / 0.62. Close is about a track's few nearest neighbours, similar about its
  nearest 50.

  | Model | top-1 cosine (median) | top-10 | top-50 | top-10 neighbours with the same top genre |
  |---|---|---|---|---|
  | CLAP | 0.856 | 0.755 | 0.643 | 72% (random 24%) |
  | GLAP | 0.948 | 0.918 | 0.884 | 68% |
  | MuQ-MuLan | 0.867 | 0.750 | 0.619 | 68% |

  The genre heads are trained on CLAP vectors, so CLAP's 72% is partly circular; GLAP's and
  MuQ's 68% are an independent sign that neighbours are musically close.
- **End-to-end check** (catalog copy, built UI):
  - "Find similar" on the piano piece "Crystaleyes" gave mostly solo piano and classical
    pieces, without the track itself. It cleared the text, focused the "Sounds like" chip, and
    hid the ratings and the rerank button.
  - Adding the text "sad" showed the slider; moving it to "Reference song" reordered the list
    towards the reference-only order.
  - Uploads: three 2-minute Song Describer clips (`data/benchmarks/sdd`) of catalog tracks each
    found their own track first. Measured again 2026-10-27: an upload of a 2-minute MP3 takes about
    0.42 s end to end once the model is loaded (decoding and resampling about 0.28 s, CLAP about
    0.15 s); the first upload after a model switch waits for the load (7.7 s). The earlier "about
    4 s" was such a first upload. `mcrar search --like-file` takes about 30 s, mostly loading
    CLAP.
- **Not in v1:** the LLM rerank refuses a reference (its prompt knows only the text), and a
  search with a reference has no ratings (they are filed under text and filters). See §5.2.

### 3.13 Game-scene tags (M9, code 2026-10-26; results 2026-10-28)
- **Owner's choices:** 14 scenes (PLAN §6's 11 plus cutscene, chase and ambient); intensity
  Low/Mid/High drives the existing energy target (0.25 / 0.5 / 0.8) for now, and the labels
  record intensity so DSP energy and the arousal head can be compared; the collaborator
  (NineJZ356) labels part of the pool.
- **Zero-shot, standardised on the catalog.** `prompts/scene.toml` (game-music phrasings,
  templates such as "video game music for {label}"), embedded with CLAP and z-scored against the
  catalog's own CLAP vectors (the FMA reference is not on this machine any more, and the catalog
  is the domain that matters). Entries carry `metrics: null` until labels exist.
- **Two variants, because of a dry run.** With the plain prompts the 14 top-10 lists shared most
  of their tracks (83 distinct tracks; the same cinematic pieces topped combat, boss, stealth,
  defeat and credits): the shared "game music" direction dominated. Subtracting 0.75 × the mean
  label vector gave 124 distinct tracks, and proxies improved (share of a scene's top 10 with an
  expected mood: stealth 0.4 → 0.9, defeat 0.2 → 0.7). The proxies are weak (the mood head lives
  in the same CLAP space), so both variants are kept: `scene-zeroshot-catalog@540a9cd` (plain) and
  `scene-zeroshot-catalog-centered@be97137` (selected until the labels decide).
- **Labelling pool:** each variant's top 10 per scene plus 100 seeded random tracks, 269 in all
  (part A 120, part B 119, 30 labelled by both for agreement). Every track in either variant's
  top 10 is labelled, so P@10 has full coverage; the random part gives a head negatives.
- **Evaluation and the head (`mcrar scenes eval` / `train`).** Per-scene P@10 over the catalog
  and on the labelled pool; a hybrid logistic-regression head (trained columns where a scene has
  ≥ 5 positives, zero-shot columns otherwise — zero-shot scoring is linear in the CLAP vector, so
  both fit one artifact) is selected only if its cross-validated mean P@10 beats zero-shot (ties
  go to the simpler entry). Also Spearman ρ of energy and arousal against the intensity labels,
  and Cohen's κ per scene between the two labellers. Results feed the model card's "Game scenes"
  section.
- **Search:** scenes are soft labels like moods (the tag term); the rule parser reads scene words
  ("boss fight" → boss + combat, "stealth level" → stealth, "victory jingle" → victory and ≤ 20 s);
  the LLM parse fills scenes too. A UI intensity overrides energy words in the text.
- **Labelling tab:** one track at a time, no model scores shown, keyboard shortcuts, jump to
  30 % / 60 %, Back and a pool list for revisiting, export of one's labels. Labels move between
  catalogs by Jamendo id (`mcrar scenes export-pack / import-pack / export-labels /
  import-labels`; the collaborator's import fetches only metadata with their own key).
- **Checked end to end** on catalog copies: real build and tagging (11 s and a few seconds),
  pool 269; labelling by keyboard and mouse, Skip, Back with the label prefilled, jump to 30 % on
  real audio; labels exported and imported into another copy, and a pack imported with identical
  positions and parts; a search with Stealth + Low intensity scored the stealth tag and energy
  0.25. Then the same build, tags and pool on the real catalog (backup `data/catalog.pre-m9.db`).

- **Results (2026-10-28).** The owner labelled part A (150 tracks) and the collaborator
  (labeller name "Simon") part B (149: all 119 plus the 30 shared; file
  `data/labels/scene-labels-Simon.json`). Imported into the real catalog after a trial on a copy.
  - Cross-validated mean P@10 on the 269 labelled tracks: plain zero-shot 0.307, centered
    zero-shot 0.407, hybrid head 0.414. The head wins narrowly; over CV seeds 0 to 8 it won
    eight times (0.414 to 0.464) and tied once, so the win is consistent but small. It is
    selected and the whole catalog (Jamendo and Freesound) was re-tagged with it.
  - Strong scenes: horror, menu, town, ambient, exploration, combat. Weak: puzzle, victory,
    defeat, chase (few positives; victory and defeat have 10 each).
  - **The labellers often disagree:** mean Cohen's κ 0.24 on the 30 shared tracks (credits 0.61,
    cutscene 0.58, combat 0.53; boss, menu and puzzle at or below chance). On the owner's labels
    alone the head scored 0.53, so part of the drop is disagreement, which caps any model.
    Intensity agreement can't be judged (only 3 shared tracks have intensity from both).
  - **Intensity stays on DSP energy:** energy and arousal both reach Spearman ρ 0.66 against the
    intensity labels (n = 153), so there is no reason to switch.
  - The model card has the "Game scenes" section. Its dataset rows now fall back to the recorded
    M3b run numbers (`RECORDED_EMBEDDING_RUNS` in `ml/tagging/report.py`), because the dataset
    folders holding the run reports were deleted from this machine; the scene metric table's
    header was fixed (one column too many when a label set has no extra columns).
  - Backup before the import: `data/catalog.pre-m9-labels.db`.
  - **Restart a running server after a selection change:** the search service reads which tag
    versions to trust when it starts, so until then it scores scenes zero-shot.

### 3.14 QoL batch 1 (2026-10-27)
The owner's list from labelling, with their choices (plan of 2026-10-27, branch `qol-1`):
- **Shortlist entries work like result rows.**
  - The title opens the track drawer, as in Search (owner's choice).
  - Download and Find similar come from the shared `features/track/TrackActions.tsx`.
  - The licence badge opens the credit popover.
  - Remove is a labelled button with a trash icon, and Undo stays.
  - Find similar from Projects goes through `#/search?similar=<id>`. It runs once, then the
    param leaves the address without a history entry.
  - The items endpoints return `source_url`, `download_url` (when allowed), the licence URLs and
    `attribution_text` (`track_links`).
- **Notes:**
  - "Add note" until used, then an auto-growing box.
  - Autosave 800 ms after typing, with serialised saves.
  - "Insert current time" is enabled while that track is loaded in the player, playing or
    paused.
  - `m:ss` tokens play the track from there (`player.play(track, {startAt})`).
- **Source label** ("Jamendo" / "Local") from one map (`features/track/sourceLabel.ts`) on
  result rows, shortlist entries and the Library table; M8 adds Spotify there.
- **Model switch.**
  - Saving a new default unloads the other models (`ModelPool.release`) and loads the new one
    in the background.
  - During an ingest job nothing is unloaded. When the job ends, every model but the default is
    released, CLAP included.
  - `/api/health` adds `models` (loading/ready/error, device, dtype) and `gpu` VRAM.
  - The Settings page shows "Model saved", then "Loading …", then "Ready on cuda (fp16) · N MB
    VRAM in use".
  - **Measured on the RTX 3060:** clap → muq-mulan → clap → glap → clap returns to 396 MB
    allocated each time (386 MB on the first load). muq-mulan uses 1,295 MB and glap 1,659 MB.
    Background loads take about 27 s for muq-mulan, 13 s for glap and 4 s for clap.
- **Repeat** toggle in the player bar (`audio.loop`), remembered in `localStorage`.
- **Search box hint:** "Describe the music, e.g. …". With a reference song it reads "Optional:
  steer it with words, e.g. calmer, no vocals". Placeholders use the lighter
  `--color-text-placeholder`. The old example hint had been mistaken for typed text after Find
  similar.
- **Checked in the built UI** on a catalog copy (port 8010, scratch `MCRAR_HOME`, real
  `.secrets` read-only for streaming):
  - a timestamp seek to 0:18, Insert time and autosave;
  - the badge popover, the drawer, and Find similar from the row and from the drawer;
  - the source labels, the model switch status line and toast, and Repeat (loop, pressed,
    stored).

### 3.15 Fixes while waiting for the labels (2026-10-27)
- **Tempo.**
  - The slow-classical problem was the display, not the ranking. All 13 classical tracks shown
    at 150 BPM or more have tempo confidence 0.05–0.33. The rank term and the filter already
    accept ×½ and ×2 below 0.5, so "slow" already matched them at half tempo.
  - Rows and the drawer now show both readings of an uncertain tempo, where the other reading
    lies in 70–180: "71 / 141 BPM" from 140 BPM up, "75 / 150 BPM" under 90. The tooltip says
    "Tempo uncertain: it may be half or double".
  - 666 of the 1,054 tracks are below 0.5. Most sit in 90–140 BPM and keep one number.
  - Search items carry `bpm_confidence`. `BPM_LOW_CONFIDENCE` is defined once, in
    `catalog/repository.py`.
- **Tag chips.**
  - Rows show "Soft · strong" or just "Soft", explained as "Compared with the rest of your
    catalog"; the drawer's percentages are captioned "Model probability" (owner's choice).
  - A row shows a track's five highest standardised scores. Over 8 searches (800 chips) on the
    owner's catalog, 98 % reached 0.9, 54 % reached 0.98 and 29 % reached 0.995. So "strong"
    starts at 0.995 (about z ≥ 3.1), not the planned 0.9.
- **Reference uploads were not slow** (re-measured in §3.12), so the planned window-only
  decoding was dropped: it would save at most about 0.2 s and change the catalog vectors.
- **Torch caches** are redirected into `.cache/` (§5.2).
- **Duplicate uploads show once (2026-10-28).** Jamendo has some pieces under two ids (5 pairs
  in the catalog). Results now keep only the best-ranked copy of a piece: same title and artist
  (case and spacing ignored) and the same length to the second (`piece_key` in
  `recommend/rank.py`); a track without a title, artist or length is never merged. Copies are
  dropped before the artist cap, so a dropped copy does not use up the artist's places, and
  "Find similar" leaves out every copy of the reference track. The catalog is unchanged.
- **Two timestamp-tie test failures fixed (2026-10-28).** On a coarse Windows clock two writes
  can get the same time. `mcrar scenes eval` could then overwrite the previous result file (it
  now steps the name forward by a microsecond), and the ratings-list test saw a tie (it now uses
  a ticking clock).

### 3.16 Freesound (M12, 2026-10-28)
- **Why:** M8 (Spotify) is on hold; Freesound has a free key and CC licences, and its previews may
  be fetched and analysed, so it feeds the catalog like Jamendo.
- **Owner's scope:**
  - Music-like sounds only: the Music and Soundscapes categories, 10 to 600 s by default.
  - **Short sound effects are a future enhancement.** They need a general-audio model (the
    default CLAP is music and speech, MuQ-MuLan is music only) and results without BPM, key or
    genre.
  - "Search for more" comes before SFX.
- **Terms** (freesound.org/help/tos_api):
  - Free for non-commercial use only, which matches the README note planned for the end.
  - One key per application, not to be shared, so each user enters their own
    (`freesound_api_key`; Settings or `mcrar secrets set`).
  - Apps may process and analyse content and keep limited intermediate copies.
  - No full copies of the database.
- **How it works:**
  - Source code: `sources/freesound.py` (header-only token, redaction, `Retry-After`, a 7-day
    response cache, a daily usage counter).
  - Ingest: `ingest_freesound`, `ingest_freesound_ids` and `ingest_freesound_queries`.
    `POST /api/ingest/freesound` starts a job of kind `ingest-freesound`, also as
    `mcrar ingest freesound`, from the Library's Freesound tab.
  - Playback redirects to the stored preview on `freesound.org` only.
  - Audio is the hq mp3 preview, held in memory and never written to disk. Originals need a
    Freesound login, so Download opens the sound page.
- **Licences:**
  - CC0 and CC BY are green and imported by default; CC BY-NC (red) only when chosen.
  - Sampling+ is a new family, `sampling-plus`, **red**: it allows only transformed use, not a
    sound as-is in a game.
  - `gen_ai_preference` is stored in `source_tags`, but doesn't block ingest: our embeddings are
    for search, not generative training. All but 3 of 60 sampled sounds said
    "no-additional-preferences".
- **Music-like filter:** `category:("Music" OR "Soundscapes")`. On "calm ambient loop" the
  categories seen were Music 47, Sound effects 7, Soundscapes 5 and Instrument samples 1. The
  first tag-based filter let 9 sound effects in 100 through; the category filter let none.
- **"Search for more":**
  - It uses every source that has a key, in one `ingest-query` job: Jamendo first, up to half
    the limit, then Freesound with the rest.
  - Freesound queries are the LLM keywords and then the text, at most 3; CC0 and BY, plus BY-NC
    only when the search allows red.
  - `GET /api/search/import/sources` tells the page which sources are usable, and the wording
    follows it.
- **Checked with real keys** on a catalog copy (port 8010):
  - a 20-sound import of "calm ambient loop": 20 new, none failed, 12 CC BY 4.0 and 8 CC0, all
    embedded (default model only) and tagged;
  - previews play from `cdn.freesound.org`;
  - "calm piano loop for a menu screen" ranked a Freesound piano loop 4th among Jamendo tracks;
  - "search for more" with limit 4 gave 2 Jamendo and 2 Freesound in 26 s.

### 3.17 Review fixes and QoL batch 2 (2026-10-28)
An independent review (the `reviewer` agent, Opus at max effort) of the 28 unpushed commits
passed with two minor findings and some nits; the owner had them fixed before the demo together
with new QoL items (plan of 2026-10-28, branch `qol-2`).
- **"Search for more" survives one source failing.** A Jamendo or Freesound error (a rejected key,
  a rate limit) only adds a warning ("Freesound failed: …") and the next source gets the rest of
  the budget; the job fails only when every source failed. A failed source's abort does not mark
  the finished job as aborted. When a failed job still added tracks, the page shows them as New
  with the error as a warning.
- **"Search for more" follows the Source filter.** Only the remote sources in the filter are
  searched; a local-only filter hides the button (the API answers 422), and the button names
  the sources it will use.
- **Library search:** a box above the track table (`GET /api/tracks?q=`): every word must appear
  in the title, artist or album; ASCII letters ignore case (SQLite folds only those); `%` and `_`
  are literal. Debounced 300 ms.
- **Drop a song to find similar:** dropping an audio file anywhere on the Search page uploads it
  as the reference song (an overlay shows while a file is dragged; other drags are ignored).
- **Add by link:** Library > Add music > **By link** (`POST /api/ingest/links`, job
  `ingest-links`). Paste up to 50 Jamendo or Freesound track links (or `jamendo:<id>` /
  `freesound:<id>`); hosts are matched exactly (`sources/links.py`). The report lists what was
  already in the library, what the source didn't return, and what wasn't understood. No licence
  filter: the user picked the track, and its badge shows its risk as usual.
- **Nits:** Settings no longer breaks on a server without `models` in `/api/health`; the model
  card's scene "Test n" shows the labelled tracks and the pending row has the right cells; two
  formatting slips; a test for the Projects "removed entry is not re-added" guard.
- **Checked** on a copy of the real catalog (port 8010, built UI): "booth latin" finds the two
  copies of one piece; a Jamendo link, a Freesound link, one track already there and a junk line
  gave 2 new, 1 already, 1 not understood, with badges and embeddings; a generated WAV dropped on
  Search gave "Sounds like: dropped-tone.wav" and 20 results; the Source-filter 422s.
- **After the demo (owner's choice): local music without typing a path.** Both a "Browse…"
  folder dialog drawn by MCRAR (files stay where they are; only when the server is loopback-only)
  and drop/choose files, which MCRAR copies into `data/library/` (named by content hash, so
  re-adding is a no-op). The Local tab must tell the user the difference (owner's requirement):
  browsing reads files in place, so moving them breaks playback; dropped files are copies that
  use disk space.

## 4. State that lives only on the owner's machine (git-ignored)

| What | Where | Notes |
|---|---|---|
| Catalog | `data/catalog.db` | 1,568 tracks (2026-10-28): 1,079 Jamendo (green 325, amber 414, red 337, unknown 3) and 489 Freesound (all green: CC0 214, CC BY 4.0 259, CC BY 3.0 16). Features `audio-v2`, embeddings for all three models, `tag_probs` for every track (genre logreg, mood/theme MLP, valence and arousal MLP; `scene` from the hybrid head since 2026-10-28), schema v5 (v4: ratings table, names and credit lines decoded, 2026-10-15; v5: `scene_labels` and `label_pool`, 2026-10-26). Hand labels: 269 tracks (owner 150, Simon 149) |
| Catalog backup | `data/catalog.pre-tag.db` | Copy taken before the first `mcrar tag`; can be deleted |
| Catalog backup (M9) | `data/catalog.pre-m9.db` | Copy taken 2026-10-26 before the scene tags, schema v5 and the labelling pool |
| Catalog backup (M12) | `data/catalog.pre-m12.db` | Copy taken 2026-10-28 before the Freesound library build for the demo |
| Catalog backup (M9 labels) | `data/catalog.pre-m9-labels.db` | Copy taken 2026-10-28 after the Freesound build, before Simon's labels, the head and the re-tag |
| Simon's labels | `data/labels/scene-labels-Simon.json` | Part B as the collaborator sent it (149 labels); already imported |
| Labelling pack | `data/scene-pack.json` | The 269-track pool for the collaborator (Jamendo ids, titles, parts; no keys) |
| Song Describer Dataset | `data/benchmarks/sdd/` | 3.2 GB; embeddings per model under `embeddings/` |
| Bake-off results | `data/benchmarks/results/` | SDD, tag eval, benchmark, candidates (+ private model map), the owner's 88 ratings (`user_ratings.json`), scored ratings |
| DEAM archives | `data/datasets/deam/download/` | 1.3 GB, used for the checksum cross-check in issue #1 |
| Model weights | `.cache/huggingface/` | about 14 GB; includes three extra CLAP checkpoints downloaded while diagnosing the broken one (`larger_clap_music`, `larger_clap_general`, `clap-htsat-unfused`), which can be deleted |
| Secrets | `.secrets/secrets.toml` | `jamendo_client_id` (the client secret is not needed); `llm_api_key_openai` (since 2026-10-19); `freesound_api_key` (since 2026-10-28) |
| LLM settings | `config/settings.toml` `[llm]` | enabled with the OpenAI preset (default model `gpt-6-luna`) since 2026-10-19 |
| Listening-test page | https://claude.ai/artifact/NPEKNfqBEZZBDeHx8ZD2J4 | private; ratings stored in its database |

### 4.1 Cleanup candidates (measured 2026-10-28; nothing deleted yet)
Each deletion waits for the owner's word. The plan is to do them at the end of the project.

**Safe now** (about 1.2 to 2.7 GB):

| What | Size | Note |
|---|---|---|
| `.cache/huggingface` `laion/clap-htsat-unfused` | about 1.2 GB | Downloaded while diagnosing the broken checkpoint (M3a); unused |
| `.cache/huggingface` `laion/larger_clap_music` | about 0.75 to 1.5 GB | The same; unused |
| `.cache/huggingface` `laion/larger_clap_general` | about 1.5 GB | Unused now. **Keep it if SFX support is likely**: it's the general-audio CLAP that milestone would need |
| `data/catalog.pre-tag.db` | 11 MB | A backup from before the first tagging |
| `.cache/smoke`, `.cache/smoke-m3a`, `.cache/demo120.wav` | about 6 MB | Early test leftovers |
| `%TEMP%\torch`, `%TEMP%\torchinductor_Admin` | 52 KB | Outside the repo; the caches now go to `.cache/` |

The rest of `.cache/huggingface` (14 GB in total) is in use: `larger_clap_music_and_speech`
(the default CLAP), GLAP, and MuQ-MuLan with the MuQ and xlm-roberta parts it loads.

**When the work that needs them is done:**

| What | Size | Delete when |
|---|---|---|
| `data/catalog.pre-m9.db` | 16 MB | The scene labels are imported and checked (M9) |
| `data/catalog.pre-m12.db` | 17 MB | The Freesound library is confirmed good after the demo |
| `data/catalog.pre-m9-labels.db` | 42 MB | The scene head is confirmed good after the demo |
| `data/benchmarks/` (Song Describer clips, bake-off results) | 3.2 GB | Re-running the bake-off and the model card numbers is no longer needed. Keep it until M9's model card is final |
| `data/datasets/` (DEAM archives) | 1.3 GB | Retraining the valence and arousal heads is no longer needed |

**After development** (about 3 GB; a packaged app needs none of it):
- `.cache/uv`: 2.6 GB. The cache can be pruned, but rebuilding environments then downloads
  again.
- `.cache/npm`: 122 MB.
- `.tools/` (Python, Node and uv): 138 MB.
- `backend/.venv`: 73 MB.
- `frontend/node_modules`: 69 MB.
- The agent's session scratch folder (outside the repo; about 550 MB, holding catalog copies
  and the no-`ml` test environment).

**Leave alone:** `%APPDATA%\NVIDIA\ComputeCache` (1.1 GB) is the graphics driver's cache,
shared with other programs.

## 5. Open items

### 5.1 M3b wrap-up
M3b is merged and the real catalog is tagged. Still open:
- **M3c** (optional CNN baseline) and the optional "m3b-embeddings" Release asset were not done.
- **No weak-label evaluation on the owner's catalog.** The collaborator didn't run it; the 66%
  genre agreement in §3.7 is the only check on the owner's data.

### 5.2 Follow-ups
- **README (near the end of the project).** The README is still a TODO. It must state that the
  project can't be used commercially, for example hosted as a paid service, because MuQ-MuLan's
  weights and the MTG-Jamendo and DEAM labels behind the tagging heads are non-commercial.
- **LLM follow-ups (M7):**
  - **Rules vs LLM on ratings.** To compare them, rate the unrated top hits of the 15 rated
    queries with the LLM on, in the UI, under the same query text. Then run
    `mcrar ratings eval` with and without `--llm` again (§3.11).
  - **Open question.** Should an English query keep its own text for CLAP and use the LLM only
    for hints? The rewrite may help or hurt; the ratings will tell.
  - **Search speed.** A first parse adds about 3 s to a search with `gpt-6-luna`. The cache is
    in memory and is lost on restart.
  - **Rerank keywords.** The rerank's `search_terms` are returned but not yet used by "Search
    Jamendo for more"; the import uses the parse's.
  - **OpenRouter default.** OpenRouter still defaults to `openai/gpt-5-nano`; switch it to
    `gpt-6-luna` if the owner wants the same model there.
  - **Unchecked providers.** JSON mode for SiliconFlow, Z.AI and Gemini is from the docs and
    hasn't been checked with a real key; the step-down covers a wrong guess.
- **Demo library built (2026-10-28, for the demo on Thu 2026-10-29).** 489 music-like
  Freesound sounds in the real catalog (backup `data/catalog.pre-m12.db`), imported through the
  owner's server by the agent's scratch script `fs_library.py`: 22 themes of 25 (ambient loop,
  game music loop, chiptune, 8-bit, orchestral, epic battle, boss fight, menu, calm piano,
  medieval, fantasy village, dungeon, horror, sci-fi, space drone, forest, rain, synthwave, lofi,
  jazz loop, tension, acoustic guitar loop) plus fantasy music, electronic loop and piano loop;
  CC0 and CC BY, most downloaded first; 0 failures, about 2.7 hours. Many themes overlap, so a theme of
  25 gave 1 to 25 new sounds ("fantasy village" found only 2). Then GLAP and MuQ-MuLan
  embeddings for them (2.3 hours, mostly preview downloads) and for the 25 Jamendo tracks that
  "search for more" had added without them. Demo searches (dungeon, boss fight, calm town,
  8-bit menu, rainy forest, stealth) mix both sources sensibly; stealth is the weakest, as the
  M9 eval predicts.
- **Library table on a narrow window:** the track table is wider than about 1,050 px, so the
  page scrolls sideways in a narrow window (seen in the in-app browser; not new in batch 2).
- **No way to remove a track** (found by the owner on 2026-10-28 while testing local files).
  When a local file is moved or deleted, its track stays in the Library and in search results,
  with its embeddings and tags, and playback fails; nothing in the UI, the API or the CLI
  removes it. `CatalogRepository.delete_track` exists (it cascades to features, tags,
  embeddings and shortlist rows) but has no caller. Wanted:
  - a Remove action in the Library (and the track drawer), with a confirmation;
  - a Maintenance step that finds local tracks whose file is gone and offers to remove them;
  - the same for any track (for example an unwanted Jamendo or Freesound import);
  - decide what happens to its ratings and scene labels, which reference the track id.
  It fits with the after-demo local-music work (§3.17), where copied files under
  `data/library/` would also be deleted.
- **Scene follow-ups (M9):**
  - More labels for victory, defeat, chase and puzzle would help most (10 to 22 positives).
  - The two labellers could agree on what boss, menu and puzzle mean (κ near 0) before more
    labelling; `docs/labelling.md` "What a label means" is the place to sharpen.
  - The head was trained on Jamendo music; its scene tags on Freesound loops and ambience are
    unchecked.
- **Reference song follow-ups (M10):**
  - The LLM rerank could take the reference into account (for example its title and top tags).
  - Ratings for reference searches would need their own key (reference plus text and filters).
  - PLAN §6's "soundtrack cohesion" mode (near a picked track, at another intensity or scene)
    can build on the reference term.
- **Per-query import polish:**
  - With GLAP as the default embedder the weak notice never shows; the button still works.
  - `search.weak_cosine` can't be cleared back to the default through the API, only in
    `settings.toml`.
- **A flaky backend test?** One full run on 2026-10-15 had a single failure that did not
  reproduce in the next nine runs, and the job tests passed six times in a row. On 2026-10-28
  two tests failed on timestamp ties (fixed, §3.15); the 2026-10-15 failure may have been one of
  them. If one shows up again, note the test name.
- **CLI search speed.** `mcrar search` with text still loads CLAP on every run (about 15 s). The
  API server keeps it loaded, so use `mcrar serve` for repeated searches.
- **API polish:**
  - The 50 MB analyze limit is checked after Starlette has spooled the upload.
  - Duplicate project names return 422, not 409.
  - On Windows, stopping `uv run mcrar serve` by killing its parent can leave the Python child
    running; use Ctrl+C.
- **Torch temp files.** `PYTORCH_KERNEL_CACHE_PATH` and `TORCHINDUCTOR_CACHE_DIR` now point
  into `.cache/` (2026-10-27). No run could be made to write a kernel cache file to check it in
  practice. The old `%TEMP%\torch` and `%TEMP%\torchinductor_Admin` folders can be deleted by
  hand. `%APPDATA%\NVIDIA\ComputeCache` (1.1 GB) is the GPU driver's cache, shared with other
  programs; it was left alone.
- **Starlette warning:** a deprecation warning about `httpx` in tests (harmless).
- **Disk:** the cleanup candidates are listed with sizes in §4.1.
- **UI follow-ups:**
  - **Add-to-project menu.** It makes one request per project to find which projects already
    hold a track; a "projects containing track" endpoint would be cleaner if there are many
    projects.
  - **Narrow windows.** Below about 900 px the header scrolls sideways; the UI is desktop-first.
  - **Cancelled imports.** Tracks whose metadata was saved before a cancel stay in the catalog
    without analysis or embedding; "Re-embed missing tracks" completes them.
- **QoL batch 1 follow-ups (2026-10-27):**
  - **Rapid switching.** If the default is switched again while the previous new default is
    still loading, that model finishes loading and stays in VRAM until the next switch or the
    end of the next job.
  - **CLAP reloads after each job.** When the default isn't CLAP, every job ends by releasing
    the CLAP it loaded for tagging, so the next import reloads it (about 4 s).
  - **A job that takes its model before it starts** could lose it to a release, and would fail
    with a 503-style error. No route does this today: they all call `pool.get` inside the job.
  - **Narrow windows.** The search hint with a reference ("Optional: steer it with words, …")
    is cut off below about 600 px.

### 5.3 Next milestone (waiting for the owner's go)
These can follow in any order:
- **M8, the Spotify metadata section: on hold (2026-10-27).** The owner will discuss it with
  the collaborator; see §3.1 for the API facts and their choices. It includes LLM query generation
  for Spotify, moved from M7.
- **Freesound follow-ups (M12):**
  - Sound effects, as a future milestone: a general-audio model and SFX-specific results.
  - Imports embed with the default model only. "Re-embed missing tracks" adds the others, as
    for Jamendo.
  - Jamendo's "search for more" terms can be loose. "Gentle harp lullaby" brought two unrelated
    Jamendo tracks, while Freesound's matched.
- **Other platforms** (researched 2026-10-27; numbers marked "reported" are from third-party
  pages). MCRAR can only analyse audio it may fetch, so a platform either feeds the catalog or is a
  link-out section like Spotify.
  - **Freesound:** the best fit, already in PLAN as "later".
    - A free API key gives search and mp3/ogg previews without OAuth; original files need OAuth2.
    - Licences are CC0, CC BY and CC BY-NC.
    - Reported limits: about 60 requests a minute and 2,000 a day.
    - Mostly sound effects, loops and ambience, which game developers need. It would ingest and
      embed like Jamendo.
  - **Openverse:** an open API (anonymous, or a token for more) over audio from Jamendo,
    Freesound and Wikimedia Commons. Mostly duplicates; Wikimedia Commons recordings would be
    new. Low priority.
  - **SoundCloud:** app registration needs an Artist Pro account. Client credentials covers
    search and playback, and its tokens are capped (reported 50 per 12 h per app).
    - Most tracks are all rights reserved, so it would be a link-out section like Spotify. Some
      tracks carry a CC licence in their metadata.
    - Whether its terms allow analysing streams for ML is unverified and likely not. Read the API
      Terms first.
  - **To check before proposing:** Internet Archive netlabels (open API, many CC releases,
    inconsistent licence data) and ccMixter (query API, CC remixes and instrumentals).
  - **Not usable:** OpenGameArt (no API, and we don't scrape), Pixabay (its API has no music) and
    Free Music Archive (API closed).

M11 (desktop packaging) comes last.

## 6. GitHub history

- **[#1](https://github.com/opoeci6/MCRAR/issues/1) DEAM checksums.** Approved exception: SHA-256
  observed independently by the owner and the collaborator (matching), labelled `observed`, plus
  ZIP CRC and member checks. Closed.
- **[#2](https://github.com/opoeci6/MCRAR/issues/2) MTG split counts.** Split-0 has 17,982
  tracks and 56 tags (train 9,949 / validation 3,802 / test 4,231); the audio release has 18,486
  and 59. The spec was corrected. Closed.
- **[#3](https://github.com/opoeci6/MCRAR/pull/3) M3b tagging PR.**
  - The owner requested two changes: lazy CLI imports and human commit authorship.
  - The collaborator rebuilt the branch as one commit, authored by NineJZ356 with a Codex
    co-author trailer.
  - Merged 2026-10-12 as `fbb9b09`. Closes #2.
- **Pushes of `dev`:** 2026-10-20 (M7, player bar, model list, up to `fab2caf`); 2026-10-26
  (M10, M9 code and the labelling handover, up to `d09b72e`). The 2026-10-26 push was checked for
  forbidden paths and stored secrets; the no-`ml` suite ran right after it (green).
