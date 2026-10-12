# Handover: M3b (tagging) and M3c (optional CNN baseline)

**Audience:** a collaborator and their coding agents (Codex). Read `AGENTS.md` first: its
environment rules are not optional. Product context is in `docs/PLAN.md` (§2b, §2c and the M3b and
M3c rows of §5). Results that led here are in `docs/embedder_bakeoff.md`.

**Branch:** create `m3b-tagging` from `dev` and open a pull request into `dev` when done. The
owner's Claude Code session reviews the PR and runs the real-model checks. CI must be green.

**Questions:** if something in this spec is unclear or seems wrong, open a GitHub issue or ask
in the PR instead of guessing. Changing an interface in section 4 needs agreement first, because
milestone M4 (search and ranking) is being built against it in parallel.

---

## 1. Goal

Give every catalog track calibrated tag probabilities for three label sets:

| Label set | Labels | Training data | Labels licence | `commercial_ok` of trained heads |
|---|---|---|---|---|
| `genre` | 16 FMA top-level genres | FMA-medium | CC BY 4.0 | **true** |
| `moodtheme` | 56 MTG-Jamendo mood/theme tags | MTG-Jamendo `autotagging_moodtheme` | CC BY-NC-SA 4.0 | false |
| `valence`, `arousal` | one value each, in [0, 1] | DEAM | non-commercial (confirm on the DEAM site) | false |

For every label set, compare a **zero-shot** method (CLAP text prompts, no training) against
**trained heads** (an MLP and a logistic-regression baseline) on the official test split, and
record all of them in `models/registry.json`. At runtime MCRAR uses, per label set, the
best-scoring entry that the current `commercial_mode` allows. In the default commercial mode,
non-commercial heads are skipped, so the commercial-safe zero-shot variant must stay good enough
to fall back on.

M3c (optional, for learning): train a small CNN on FMA-medium mel-spectrograms with the same split
and compare it with the CLAP-embedding heads.

## 2. Ground rules specific to this work

- **Embed with exactly `clap@195c3a3`.** Use `mcrar.ml.embedders.load_embedder("clap", settings=...)`
  and `mcrar.ml.embedders.embed_track`, decoding with `mcrar.audio.load_audio(path, sr=embedder.sample_rate, mono=True, max_seconds=240)`.
  This is how the catalog was embedded (`mcrar.ingest.EmbeddingStage`): the same model revision,
  the same 240 s cap and the same three windows. Any other model, revision, cap or windowing gives
  vectors the heads were not trained on, and they would fail silently on the real catalog.
- **No pickle.** Save heads as `.npz` (weights plus metadata arrays) and run inference in plain
  numpy. Train with torch or scikit-learn as you like, then export. Runtime tagging must work
  without torch installed.
- **Data stays in `data/` (git-ignored).** Use `data/datasets/<name>/` for downloads and
  `data/datasets/<name>/embeddings/clap@195c3a3.npz` (`ids`, `matrix` float32) for embeddings.
  Audio may be deleted after embedding (`--delete-audio`). Run M3c first if you want it, because
  it needs the FMA audio.
- **Licences travel with the artifacts.** Every registry entry records the licence of the data it
  was trained or calibrated on, and `commercial_ok`. Anything fitted to non-commercial labels is
  `commercial_ok: false`, including calibration parameters fitted on MTG-Jamendo or DEAM labels.
- **Determinism:** fixed seeds, recorded in the registry.
- **No Jamendo API is needed.** The datasets are downloaded directly. Don't ask for the owner's
  Jamendo client id. If you want a local catalog for manual testing, register your own free
  client id and store it with `mcrar secrets set jamendo_client_id`.

## 3. Datasets

Verify every download against its published checksum and make each command idempotent and
resumable.

### FMA-medium (genre)
- Files: `fma_metadata.zip` (342 MiB) and `fma_medium.zip` (22 GiB, 25,000 clips of 30 s), from
  `https://os.unil.cloud.switch.ch/fma/`. SHA-1 checksums are in the README of
  `https://github.com/mdeff/fma`:
  - `fma_metadata.zip`: `f0df49ffe5f2a6008d7dc83c6915b31835dfe733`
  - `fma_medium.zip`: `c67b69ea232021025fca9231fc1c7c1a063ab50b`
- Labels: `tracks.csv` has a two-row header. Use `("track", "genre_top")` as the single label,
  `("set", "subset") <= "medium"` and the official `("set", "split")` (`training`, `validation`,
  `test`).
- Audio path: `fma_medium/{tid // 1000:03d}/{tid:06d}.mp3`. A few FMA files are known to be
  corrupt or too short. Skip them, count them and report the count.
- Labels licence: CC BY 4.0 (metadata). Audio: per-track Creative Commons, used here only to
  compute embeddings.

### MTG-Jamendo, mood/theme subset (moodtheme)
- The audio release has 18,486 full tracks and 59 mood/theme tags (`audio-low` type, about 46 GB).
  The official split-0 keeps **17,982 tracks** (train 9,949, validation 3,802, test 4,231; no
  overlap) and **56 tags** (`ambiental`, `horror` and `mellow` are dropped), checked at MTG commit
  `cafd8e20c265ed84f1e61f1c875327971f43a62f`. Embed, train, calibrate and evaluate on the split-0
  members and the 56 split tags only. The other 504 tracks may be embedded but are never used for
  training, calibration or metrics. Report both counts in the model card and registry (issue #2).
- Use the official download script from `https://github.com/MTG/mtg-jamendo-dataset`
  (`scripts/download/download.py --dataset autotagging_moodtheme --type audio-low --from mtg-fast`),
  run with the project interpreter (`scripts/with-env.sh uv run --directory backend python ...`)
  from a **pinned commit** of that repository cloned under `data/datasets/mtg-jamendo/repo/`.
  Record the commit hash in the registry.
- Splits: `data/splits/split-0/autotagging_moodtheme-{train,validation,test}.tsv`. Tags look like
  `mood/theme---happy`; store the label as `happy`.
- Labels licence: **CC BY-NC-SA 4.0**, non-commercial research only.

### DEAM (valence and arousal)
- 1,802 songs, audio about 1.3 GB, from `https://cvml.unige.ch/databases/DEAM/`. Confirm the
  licence and file names there and record them.
- Use the static per-song averages (`valence_mean`, `arousal_mean`, scale 1 to 9) and map them to
  [0, 1] with `(x - 1) / 8`.
- Split: there is no single official split. Use a seeded random 80/10/10 split over song ids
  (seed 0, recorded in the registry) and also report the results on the 2015 songs (ids 2001 to
  2058) separately.
- Labels licence: non-commercial.

## 4. Interfaces (M4 depends on these; do not change without agreement)

### 4.1 Registry: `models/registry.json` (committed)

```json
{
  "schema": 1,
  "embedder": "clap@195c3a3",
  "label_sets": {
    "genre": {
      "kind": "single_label",
      "labels": ["blues", "classical", "...16 ids..."],
      "display": {"blues": "Blues", "old-time-historic": "Old-Time / Historic"},
      "entries": [
        {
          "id": "genre-mlp@1a2b3c4",
          "method": "head",
          "variant": "mlp",
          "file": "heads/genre-mlp@1a2b3c4.npz",
          "train_data": "FMA-medium (official split)",
          "data_license": "CC BY 4.0",
          "commercial_ok": true,
          "seed": 0,
          "metrics": {"split": "test", "primary": "macro_f1", "macro_f1": 0.0, "accuracy": 0.0},
          "created_at": "2026-10-20T12:00:00Z"
        },
        {
          "id": "genre-zeroshot@5d6e7f8",
          "method": "zeroshot",
          "variant": "calibrated",
          "prompts": "backend/src/mcrar/ml/tagging/prompts/genre.toml",
          "file": "heads/genre-zeroshot@5d6e7f8.npz",
          "calibration_data": "FMA-medium validation split",
          "data_license": "CC BY 4.0",
          "commercial_ok": true,
          "metrics": {"split": "test", "primary": "macro_f1", "macro_f1": 0.0}
        }
      ]
    }
  }
}
```

- `labels` are stable lowercase ids (`[a-z0-9-]+`). `display` holds the human names.
- `kind` is `single_label` (genre: softmax over labels), `multi_label` (moodtheme: an independent
  probability per label) or `regression` (valence and arousal: one label `value`, in [0, 1]).
- Entry `id` is `<label set>-<variant>@<first 7 hex of the sha256 of the .npz file>`. It is
  written to the catalog as `model_version`, so it must change whenever the weights change.
- `metrics.primary` is the selection metric: `macro_f1` for `single_label`, `macro_pr_auc` for
  `multi_label` and `r2` for `regression`. Also report accuracy (genre), macro ROC-AUC
  (moodtheme) and Pearson r (valence and arousal).
- Selection rule (implement it in code, `select_entry`): among the entries with
  `commercial_ok: true`, or all entries when `commercial_mode` is false, take the highest primary
  metric on the test split. Report "no entry" when none is allowed; valence and arousal
  will have none in commercial mode, and that is fine.

### 4.2 Runtime module: `backend/src/mcrar/ml/tagging/`

```python
from mcrar.ml.tagging import load_taggers, tagging_stages, Tagger

taggers: list[Tagger] = load_taggers(settings)      # one per label set with an allowed entry
t = taggers[0]
t.label_set        # "genre"
t.kind             # "single_label" | "multi_label" | "regression"
t.labels           # ["blues", ...]
t.entry_id         # "genre-mlp@1a2b3c4"
t.method           # "head" | "zeroshot"  (the catalog's tag_probs.method)
t.predict(matrix)  # (n, 512) float32 L2-normalised CLAP embeddings -> dict[label, np.ndarray (n,)] in [0, 1]

stages = tagging_stages(settings)                    # list[TaggingStage], one per tagger
```

- `predict` is pure numpy. The zero-shot taggers need the text embeddings of their prompts.
  Compute them once when building the zero-shot entry and store them in its `.npz`, so runtime
  never loads CLAP.
- `TaggingStage` implements `mcrar.ingest.Stage` with `needs_audio = False`:
  - `name = f"tag:{label_set}"` and `version = entry_id`.
  - `is_current(repo, track_id)`: the track has `tag_probs` rows for `head=label_set` with
    `model_version == entry_id`.
  - `run(repo, track_id, audio=None)`: reads `repo.get_embedding(track_id, "clap@195c3a3")`,
    raises a clear error if the embedding is missing, predicts and writes
    `repo.set_tag_probs(track_id, head=label_set, method=t.method, model_version=entry_id, probs=...)`.
  - The pipeline already supports such stages. `mcrar.ingest.needs_audio(stage)` is False, the
    stage gets `audio=None`, no audio is downloaded for it, and it can follow the embedding stage
    in the same pass. See `backend/tests/ml/test_ml_stored_input_stages.py`.
- The catalog API you write through is `CatalogRepository.set_tag_probs` and `get_tag_probs`
  (`backend/src/mcrar/catalog/repository.py`). `method` must be `"zeroshot"` or `"head"`, and
  every probability must be in [0, 1].

### 4.3 Zero-shot prompts: `backend/src/mcrar/ml/tagging/prompts/<label set>.toml`

TOML, read with the standard library's `tomllib` (the project uses TOML everywhere; no YAML
dependency):

```toml
templates = ["{label} music", "a {label} song", "this track sounds {label}"]

[labels]
happy = ["happy", "joyful"]
old-time-historic = ["old-time historic", "early 20th century recording"]
```

The score of a label is the mean cosine similarity over templates × synonyms. Two variants per
label set:
- `calibrated`: a temperature (single label) or per-label Platt scaling (multi label), fitted on
  the validation split. It inherits that split's licence.
- `unsupervised` (commercial-safe for moodtheme): no labels are used. Each label's score is
  standardised with a mean and standard deviation over a reference set of unlabelled embeddings,
  then passed through a sigmoid with a fixed slope. Use the FMA-medium training embeddings as the
  reference set (CC BY 4.0 labels are not used, only the audio embeddings), and store the
  statistics in the `.npz`.

### 4.4 CLI (keep `cli.py` edits to registrations)

Put the commands in your own modules (for example `mcrar/ml/datasets/cli.py` and
`mcrar/ml/tagging/cli.py`, each with a `typer.Typer()`) and register them in `cli.py` with one
`app.add_typer(...)` or `app.command(...)` line each:

```
mcrar datasets download fma-medium|mtg-moodtheme|deam
mcrar datasets embed fma-medium|mtg-moodtheme|deam [--delete-audio] [--batch-size N]
mcrar tagging train genre|moodtheme|valence|arousal [--variant mlp|logreg|zeroshot-calibrated|zeroshot-unsupervised]
mcrar tagging evaluate [label sets...]        # test-split metrics for every entry, writes data/benchmarks/results/tagging_<ts>.json
mcrar tagging select                           # writes models/registry.json and prints the chosen entry per mode
mcrar tag [--label-sets ...] [--force]         # tags the catalog from stored embeddings (no network, no audio)
```

Follow the existing CLI style: lazy torch imports, `error: ...` with exit 1, and progress lines
like the `mcrar embed` command. Do not edit the `ingest` commands. The owner adds tagging to
ingest in M4, using your `tagging_stages(settings)`.

## 5. Training and evaluation

- **Heads:**
  - `logreg`: scikit-learn `LogisticRegression` (one-vs-rest for multi label, ridge regression for
    valence and arousal). It is the baseline the MLP must beat.
  - `mlp`: one hidden layer (256 or 512 units, ReLU, dropout) with early stopping on the
    validation split. Use a weighted or focal loss for the unbalanced moodtheme tags if it helps.
  - Calibrate on validation: temperature for single label and per-label Platt scaling for
    multi label. Record the calibration error (ECE) next to the metrics.
- **Report** everything on the **test split**, the same split for every method:

  | Label set | Primary | Also |
  |---|---|---|
  | genre | macro F1 | accuracy, top-3 accuracy |
  | moodtheme | macro PR-AUC | macro ROC-AUC (published CLAP-style baselines are around 0.75 to 0.80) |
  | valence, arousal | R² | Pearson r (and the 2015 subset separately) |

- Add bootstrap 95% confidence intervals for the primary metric (resampling test items, 1,000
  resamples, seed 0). `mcrar.ml.bakeoff.metrics` already has `bootstrap_mean_ci` and
  `paired_bootstrap_diff`; reuse them.
- **Domain shift:** the datasets are 30 s clips (FMA) or full tracks capped at 240 s (MTG,
  DEAM), while the catalog is full tracks capped at 240 s. Mention this in the model card. You
  may also report genre accuracy on the owner's catalog Jamendo genres as an extra sanity check
  if you build a catalog yourself.

## 6. Deliverables (the pull request)

1. Code: `backend/src/mcrar/ml/datasets/`, `backend/src/mcrar/ml/tagging/` (and
   `backend/src/mcrar/ml/baselines/` for M3c), plus the CLI registrations.
2. `models/registry.json` and `models/heads/*.npz` (small, committed; the `.gitignore` already
   allows exactly these).
3. `docs/model_card.md`: data and licences, metrics tables with confidence intervals, the entry
   selected per label set in commercial and non-commercial mode, calibration, domain shift,
   known failure cases, and M3c's comparison table if done.
4. Tests (section 7), all green, plus `ruff`.
5. Optional, not in git: upload `data/datasets/*/embeddings/clap@195c3a3.npz` as assets of a
   GitHub Release named `m3b-embeddings` (about 100 MB in total), so retraining doesn't need the
   70 GB of audio again. Say so in the PR.
6. In the PR description: the commands you ran, their outputs (metric tables), the dataset
   commits and checksums, GPU and time used, and anything you could not do.

## 7. Tests required

Default suite (no network, no real model, no real dataset; use tiny synthetic data and
`FakeEmbedder`). Name files `backend/tests/ml/test_ml_tagging_*.py` and
`backend/tests/ml/test_ml_datasets_*.py`.

- Dataset parsers on tiny synthetic CSV/TSV files that copy the real formats: FMA two-row header
  and split, MTG tag prefix and splits, DEAM scale mapping.
- Checksum verification and idempotent re-download (a fake HTTP transport or a local file server
  fixture; no real downloads).
- Embedding a dataset: resumable, uses `embed_track` with `max_seconds=240` (assert the call), and
  deletes audio only after a successful write.
- Head round trip: train a logreg and an MLP on separable synthetic data, export to `.npz`, load
  with numpy only, and get the same predictions (within tolerance) as before export.
- Zero-shot: both variants on synthetic text/audio vectors. The unsupervised variant uses no
  labels (assert it), and probabilities are in [0, 1].
- Registry: schema validation, entry ids derived from the file hash, and `select_entry` in both
  modes (a non-commercial winner is skipped in commercial mode, and "no entry" is handled).
- `TaggingStage`: `needs_audio` is False, `is_current` follows `entry_id`, a missing embedding
  fails cleanly, and writes go through `set_tag_probs` with the right `method`. Use
  `reprocess_catalog` with a temp catalog to check that no audio is fetched.
- CLI smoke tests with `typer.testing.CliRunner`, including `mcrar tag` on a temp catalog.
- Real-model tests (`@pytest.mark.models`): the zero-shot prompt text embeddings match a fresh
  CLAP load, so the stored prompt vectors are not stale.

## 8. M3c (optional): CNN baseline

- A short-chunk CNN (3 s mel-spectrogram chunks, about 5 conv blocks, chunk predictions averaged
  per clip) on FMA-medium, same official split, genre only.
- Compare its test macro F1 and accuracy with the CLAP-embedding heads in `docs/model_card.md`.
  This is for learning: it is not selectable at runtime and adds no registry entry.
- Code goes in `backend/src/mcrar/ml/baselines/`. Tests only cover the data pipeline and the model
  shapes on synthetic input.

## 9. Acceptance checklist (the reviewer will check each item)

- [ ] `mcrar datasets download/embed` work end to end for all three datasets, and the checksums are verified.
- [ ] All embeddings were made with `clap@195c3a3`, `embed_track` and `max_seconds=240`.
- [ ] For each label set: zero-shot and heads are evaluated on the test split, the MLP beats logreg (or the PR explains why not), and the CIs are reported.
- [ ] `models/registry.json` follows section 4.1. The heads are `.npz` with numpy inference. Licences and `commercial_ok` are correct.
- [ ] `mcrar tag` tags the catalog with no network and no audio, and `tag_probs` rows carry the entry ids.
- [ ] In the default commercial mode, `genre` uses a commercial-safe entry, `moodtheme` falls back to `zeroshot-unsupervised`, and valence and arousal are absent.
- [ ] `docs/model_card.md` is complete.
- [ ] Default test suite, `ruff check` and `ruff format --check` pass. CI is green. `-m models` tests pass on a GPU machine.
- [ ] The diff stays within the files in section 6 plus registrations in `cli.py` and dependencies in `pyproject.toml`/`uv.lock`.
