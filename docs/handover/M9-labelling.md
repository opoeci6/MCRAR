# Handover: label game scenes for M9 (part B)

For the collaborator and the coding agent helping them. The owner labels part A; you label
**part B**. What a label means and the whole workflow are in [`docs/labelling.md`](../labelling.md);
this page is the short checklist for your side.

**What you get from the owner:** `scene-pack.json`, the list of 269 tracks to label (Jamendo ids,
titles, artists and which part each belongs to; no keys).
**What you send back:** one labels file, `my-labels.json`.
**Time:** about 150 tracks (119 in part B plus 30 shared with the owner), roughly 30–60 s each.

## Rules for the agent

- Run every command through the env wrapper: `scripts/with-env.sh <cmd>` (Git Bash) or
  `scripts\with-env.ps1 <cmd>` (PowerShell). Install nothing system-wide (no `pip --user`,
  `npm -g`, `winget`, `choco`, `setx`, registry writes or global `uv tool install`); everything
  stays under `.tools/` and `.cache/` (`docs/dev-setup.md`).
- The Jamendo client id is the human's secret: **the human types it** at the hidden prompt of
  `mcrar secrets set`. Never ask for it in chat, never print or log it, never put it in a file,
  a command line or a commit.
- This task changes no code. Do not commit, push, or open pull requests. Never commit `data/`,
  `.secrets/`, `.tools/`, `.cache/` or `config/settings.toml`.
- The labels themselves are the human's judgement: the agent may help set up, run commands and
  export, but must not choose labels.

## Steps

1. **Get the code** (the work is on `dev`):

   ```bash
   git fetch origin
   git checkout dev
   git pull --ff-only
   ```

2. **Set up or refresh the toolchain** (idempotent; fine on an existing clone):

   ```bash
   scripts/bootstrap.sh          # PowerShell: scripts\bootstrap.ps1 (see docs/dev-setup.md)
   scripts/with-env.sh npm --prefix frontend run build
   ```

   The `ml` extra (PyTorch) is not needed for labelling: no audio is analysed or embedded.

3. **Store your own Jamendo client id** (free from <https://devportal.jamendo.com>; the human
   types it at the hidden prompt):

   ```bash
   scripts/with-env.sh uv run --directory backend mcrar secrets set jamendo_client_id
   ```

4. **Import the pack** the owner sent. Tracks missing from your catalog are fetched from Jamendo
   by id, metadata only; anything that cannot be fetched is listed and skipped.

   ```bash
   scripts/with-env.sh uv run --directory backend mcrar scenes import-pack path/to/scene-pack.json
   ```

   It should end with `Pool of 269 tracks: ... fetched`. If you already have a pool from an
   earlier attempt, add `--force` (labels are kept; they belong to tracks).

5. **Label.** Start the app and open it in a browser:

   ```bash
   scripts/with-env.sh uv run --directory backend mcrar serve
   ```

   Go to <http://127.0.0.1:8000/#/label> (the **Labelling** tab), set **Part** to **Part B** and
   **Your name** to one fixed name (use the same name every session, e.g. `nine`).
   - Listen (the first minute is enough; "Jump to 30% / 60%" helps), tick **every** scene the
     music could plausibly play in, or **None of these**, optionally set intensity, then **Save
     and next**. **Skip** only for a track you cannot judge.
   - Keyboard: `1`–`9`, `0`, `Q`, `W`, `E`, `R` toggle the 14 scenes; `N` none; `A`/`S`/`D`
     intensity low/mid/high; `Enter` save; `K` skip; `B` back; `Space` play/pause.
   - Judge the sound, not the title; do not look tracks up. Back and the pool list let you fix a
     label later. You can stop and continue another day: progress is stored in your catalog.
   - The page says "All done for this part" when part B is finished.

6. **Export and send your labels** (use the same name you labelled under):

   ```bash
   scripts/with-env.sh uv run --directory backend mcrar scenes export-labels my-labels.json --labeller "nine"
   ```

   (The **Export my labels** link on the Labelling tab downloads the same file.) Send
   `my-labels.json` to the owner. It holds Jamendo ids, titles, your scene choices and
   timestamps only.

## If something goes wrong

- "No Jamendo client id is configured" on import: step 3 was skipped. An auth error (HTTP
  401/403): the id is wrong; store it again.
- `No labelling pool yet` on the Labelling tab: step 4 did not finish; run it again.
- A track does not play: Jamendo may have removed it. Skip it.
- The page is blank at `/`: the frontend was not built (step 2).
- Questions about what a scene means: `docs/labelling.md`, "What a label means".
