# Project status and decision log

The living record of what MCRAR has done, what was decided and why, what is open, and what
exists only on the owner's machine. `docs/PLAN.md` is the plan; this file is the state.
**Update it whenever a milestone lands or a decision is made.**

Last updated: 2026-10-15.

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
| M7–M11 | Not started | — | See `docs/PLAN.md` §5 |

Test suite on `dev`: 1,337 passed, 30 skipped (default); 1,334 passed without the `ml` extra
(CI); 29 real-model tests with `-m models`. Frontend: 190 vitest tests, plus oxlint and the
build (CI runs all three).
CI: GitHub Actions on Windows (`.github/workflows/ci.yml`); runs #5 onwards are green.

## 2. How we work

- **Branches.** One branch per milestone or fix, cut from `dev`, merged into `dev` with
  `--no-ff`. `main` still holds only the initial commit. `dev` is pushed to GitHub
  (`opoeci6/MCRAR`, private). Merged local branches are kept.
- **Pushing.** Push `dev` only when the owner asks. Before every push: run the default suite in
  the normal env **and** in a scratch venv without the `ml` extra (as CI does), and grep the
  outgoing commits for the Jamendo client id (`git log -p origin/dev..dev | grep -c <id>` must
  be 0).
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

## 3. Decisions and the reasons for them

### 3.1 Product and licensing
- **Spotify is metadata and search only.** Since 2024–2026 its API gives no audio, no audio
  features and no previews for new apps, and Development Mode is limited to about 5 users. ML
  runs only on audio we can fetch: Jamendo, local folders and asset packs, and Freesound later.
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
  regular PC). It is milestone M7.

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
  - Pages are hash tabs: Search, Projects, Library, Settings.
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
    best hit. Its threshold is `search.weak_cosine`, by default 0.40 for CLAP.
    - **Calibration** (raw top-1 cosine on the 1,054-track catalog): the 15 rated game-music
      queries scored 0.41–0.66. Clearly weak queries scored lower: "intense fight" 0.32, "anime
      opening" 0.37, "bagpipes" 0.39.
    - **J-pop isn't caught.** "j-pop" scores 0.57 and "japanese vocal" 0.47, because CLAP can't
      tell J-pop from pop. That is why the button is also always shown. A better weak-match
      judgment is a job for M7 (the LLM).
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

## 4. State that lives only on the owner's machine (git-ignored)

| What | Where | Notes |
|---|---|---|
| Catalog | `data/catalog.db` | 1,054 Jamendo tracks (green 320, amber 402, red 329, unknown 3), features `audio-v2`, embeddings for all three models, `tag_probs` for every track (genre logreg, mood/theme MLP, valence and arousal MLP; re-tagged 2026-10-15 in 48 s, 0 failures), schema v3 (ratings table, decoded names); the next open with the new code applies v4 (decoded credit lines and accents) || Catalog backup | `data/catalog.pre-tag.db` | Copy taken before the first `mcrar tag`; can be deleted |
| Song Describer Dataset | `data/benchmarks/sdd/` | 3.2 GB; embeddings per model under `embeddings/` |
| Bake-off results | `data/benchmarks/results/` | SDD, tag eval, benchmark, candidates (+ private model map), the owner's 88 ratings (`user_ratings.json`), scored ratings |
| DEAM archives | `data/datasets/deam/download/` | 1.3 GB, used for the checksum cross-check in issue #1 |
| Model weights | `.cache/huggingface/` | about 14 GB; includes three extra CLAP checkpoints downloaded while diagnosing the broken one (`larger_clap_music`, `larger_clap_general`, `clap-htsat-unfused`), which can be deleted |
| Secrets | `.secrets/secrets.toml` | `jamendo_client_id` (the client secret is not needed) |
| Listening-test page | https://claude.ai/artifact/NPEKNfqBEZZBDeHx8ZD2J4 | private; ratings stored in its database |

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
- **Per-query import polish:**
  - The weak-match threshold is calibrated for CLAP only; with another default embedder the
    notice never shows, but the button still works.
  - A search limited to local sources still offers the Jamendo import.
  - `search.weak_cosine` can't be cleared back to the default through the API, only in
    `settings.toml`.
- **A flaky backend test?** One full run on 2026-10-15 had a single failure that did not
  reproduce in the next nine runs, and the job tests passed six times in a row. If it shows up
  again, note the test name.
- **CLI search speed.** `mcrar search` with text still loads CLAP on every run (about 15 s). The
  API server keeps it loaded, so use `mcrar serve` for repeated searches.
- **API polish:**
  - The 50 MB analyze limit is checked after Starlette has spooled the upload.
  - Duplicate project names return 422, not 409.
  - On Windows, stopping `uv run mcrar serve` by killing its parent can leave the Python child
    running; use Ctrl+C.
- **Torch temp files.** torch writes a small kernel cache (about 250 KB) to the system temp
  folder; it could be redirected into `.cache/`.
- **Starlette warning:** a deprecation warning about `httpx` in tests (harmless).
- **Disk:** the extra CLAP checkpoints in `.cache/huggingface` and `data/catalog.pre-tag.db`
  can be deleted (§4).
- **BPM on slow classical.** Octave folding into 70–180 gives some slow classical pieces 160–174
  BPM (seen in a calm classical search). Low tempo confidence should widen the BPM match (×½), as
  PLAN §7 says.
- **UI follow-ups:**
  - **Tag scores display.** Top-tag chips show standardised scores as percentages (e.g.
    "Trailer 94%"). They are relative strengths, not probabilities, so a label such as "strong /
    typical" may read better.
  - **Shortlist badges.** The shortlist's licence badges show risk and code only; the items
    endpoint has no attribution.
  - **Add-to-project menu.** It makes one request per project to find which projects already
    hold a track; a "projects containing track" endpoint would be cleaner if there are many
    projects.
  - **Narrow windows.** Below about 900 px the header scrolls sideways; the UI is desktop-first.
  - **Cancelled imports.** Tracks whose metadata was saved before a cancel stay in the catalog
    without analysis or embedding; "Re-embed missing tracks" completes them.

### 5.3 Next milestone (waiting for the owner's go)
M7 (LLM query parsing and rerank, API key first), M8 (Spotify metadata section), M9 (game-scene
tags, with a hand-labelled set that can use the new rating UI) and M10 (reference song) can follow
in any order; M11 (desktop packaging) comes last.

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
