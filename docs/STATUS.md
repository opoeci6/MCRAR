# Project status and decision log

The living record of what MCRAR has done, what was decided and why, what is open, and what
exists only on the owner's machine. `docs/PLAN.md` is the plan; this file is the state.
**Update it whenever a milestone lands or a decision is made.**

Last updated: 2026-10-12.

## 1. Milestones

| # | Status | Where | Notes |
|---|---|---|---|
| M0 Scaffold + project-local toolchain | Done | `dev` | uv 0.13.0, Node 24.21.0, Python 3.11 under `.tools/`; `mcrar doctor` |
| M1 Audio analysis | Done | `dev` | `mcrar analyze`; analysis version `audio-v2` (energy recalibrated, §3.4) |
| M2 Catalog, Jamendo + local ingest, licensing | Done | `dev` | `mcrar ingest jamendo/local`, `mcrar catalog …` |
| M3a Embedders + bake-off | Done | `dev` | Default embedder `clap@195c3a3`; report in `docs/embedder_bakeoff.md` |
| M3b Tagging | **PR [#3](https://github.com/opoeci6/MCRAR/pull/3) open, changes requested** | `m3b-tagging` (collaborator NineJZ356 + Codex) | Spec `docs/handover/M3b-tagging.md`; see §5.1 |
| M3c CNN baseline (optional) | Not done | — | The collaborator skipped it; unassigned |
| M4 Search and ranking | Done | `dev` | `mcrar search`; ingest embeds by default |
| M5 API | Not started | — | The owner said to wait before starting |
| M6–M11 | Not started | — | See `docs/PLAN.md` §5 |

Test suite on `dev`: 961 passed, 29 skipped (default); also passes without the `ml` extra (CI).
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
- **`commercial_mode = true` by default.** Anything trained on or calibrated with non-commercial
  data (MuQ-MuLan weights, MTG-Jamendo and DEAM labels) is refused or skipped in that mode. The
  owner keeps the commercial option open.
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
- **MuQ-MuLan** stays available with `MCRAR_COMMERCIAL_MODE=false`.
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
- **Zero-shot tag scores** are standardised over the whole catalog, then passed through a
  sigmoid. Stored `tag_probs` from M3b win when present.
- **Ingest** embeds with `default_embedder` by default (`--no-embed` to skip) and appends M3b
  tagging stages through one guarded import.
- **Result quality:** on the 15 rated searches the top-2 mean rating is 1.35, against CLAP
  alone 1.40 (no loss).

### 3.6 CI and tests
- CI runs on Windows without the `ml` extra. The tests force Typer's plain output
  (`_TYPER_FORCE_DISABLE_TERMINAL`), because Actions makes Typer emit colour codes. Tests that
  fake models also fake torch availability.

## 4. State that lives only on the owner's machine (git-ignored)

| What | Where | Notes |
|---|---|---|
| Catalog | `data/catalog.db` | 1,054 Jamendo tracks (green 320, amber 402, red 329, unknown 3), features `audio-v2`, embeddings for all three models, **no `tag_probs` yet** (run `mcrar tag` after PR #3 merges) |
| Song Describer Dataset | `data/benchmarks/sdd/` | 3.2 GB; embeddings per model under `embeddings/` |
| Bake-off results | `data/benchmarks/results/` | SDD, tag eval, benchmark, candidates (+ private model map), the owner's 88 ratings (`user_ratings.json`), scored ratings |
| DEAM archives | `data/datasets/deam/download/` | 1.3 GB, used for the checksum cross-check in issue #1 |
| Model weights | `.cache/huggingface/` | about 14 GB; includes three extra CLAP checkpoints downloaded while diagnosing the broken one (`larger_clap_music`, `larger_clap_general`, `clap-htsat-unfused`), which can be deleted |
| Secrets | `.secrets/secrets.toml` | `jamendo_client_id` (the client secret is not needed) |
| Listening-test page | https://claude.ai/artifact/NPEKNfqBEZZBDeHx8ZD2J4 | private; ratings stored in its database |

## 5. Open items

### 5.1 PR #3 (M3b tagging) — waiting for the collaborator
The owner's review requested two changes:
1. **CLI startup regression.** `cli.py` imports `mcrar.ml.datasets.cli`, which imports
   `mcrar.audio` (librosa, scipy), so every `mcrar` command pays about 2 s. Move the heavy imports
   inside the commands, and add a test that `import mcrar.cli` loads none of librosa, scipy,
   torch or sklearn.
2. **Commit authorship.** Rebuild the branch with the collaborator as author and
   `Co-authored-by: Codex <codex@openai.com>` (all 7 commits were authored as Codex).

Verified in review:
- tests 992/989 (no torch)/29 (models)
- licence selection in both modes
- `mcrar tag` on a copy of the real catalog: 25 s, 0 failures; genre top-1 agrees with Jamendo
  uploader tags on 66%

Results:
- genre: logreg, macro F1 0.51
- mood/theme: MLP PR-AUC 0.14 in non-commercial mode; zero-shot-unsupervised in commercial mode
  (ROC-AUC 0.66, poorly calibrated)
- valence and arousal: MLP R² 0.67 and 0.69, non-commercial only

**After it merges:**
1. Re-run the full checks.
2. Run `mcrar tag` on the real catalog.
3. Update this file and the README.

### 5.2 Follow-ups
- **M4: normalise mood scores per label in the tag term.** Calibrated mood probabilities are
  low in absolute terms (multi-label base rates), so a mood counts far less than a genre, and the
  commercial zero-shot mood scores are uncalibrated.
- **CLI search speed.** `mcrar search` with text loads CLAP on every run (about 15 s); the M5
  server should keep it loaded.
- **Torch temp files.** torch writes a small kernel cache (about 250 KB) to the system temp
  folder; it could be redirected into `.cache/`.
- **Starlette warning:** a deprecation warning about `httpx` in tests (harmless).
- **M3c** (optional CNN baseline) and the optional "m3b-embeddings" Release asset were not done.
- **Disk:** the extra CLAP checkpoints in `.cache/huggingface` can be deleted (§4).

### 5.3 Next milestone (waiting for the owner's go)
**M5 API:** FastAPI wrapping search (CLAP kept loaded), track details, preview/stream redirects,
settings, ingest with progress over SSE, reference upload, projects/shortlists and credits
export. M6 (the UI) builds on it.

## 6. GitHub history

- **[#1](https://github.com/opoeci6/MCRAR/issues/1) DEAM checksums.** Approved exception: SHA-256
  observed independently by the owner and the collaborator (matching), labelled `observed`, plus
  ZIP CRC and member checks. Closed.
- **[#2](https://github.com/opoeci6/MCRAR/issues/2) MTG split counts.** Split-0 has 17,982
  tracks and 56 tags (train 9,949 / validation 3,802 / test 4,231); the audio release has 18,486
  and 59. The spec was corrected. Closed.
- **[#3](https://github.com/opoeci6/MCRAR/pull/3) M3b tagging PR.** Open, changes requested
  (§5.1).
