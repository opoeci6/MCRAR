# M3b tagging model card

Generated from `models/registry.json` by `uv run --directory backend python -m mcrar.ml.tagging.report` (through the env wrapper).

## Data and provenance

All audio embeddings use `clap@195c3a3` (LAION larger CLAP music and speech, Apache-2.0), mono decoding at 48 kHz, a 240 s cap and the canonical `embed_track` three-window aggregation. Windows are 10 s, centred at 20%, 50% and 80%, with short clips padded. Batch processing replays the same window outputs through `embed_track`; the default suite checks equivalence.

| Dataset | Labels/licence | Split | Embedded / expected | Skipped |
|---|---|---|---|---|
| fma-medium | 16 genres; metadata CC BY 4.0; audio per-track CC | Official train/validation/test | 24980 / 25000 | 20 |
| mtg-moodtheme | 56 mood/theme labels; CC BY-NC-SA 4.0 | Official split-0 | 17982 / 17982 | 0 |
| deam | Valence/arousal; CC BY-NC (version unspecified, per DEAM manual) | Seed 0 random 80/10/10 by song id | 1802 / 1802 | 0 |

FMA archive SHA-1 values (publisher's README):

- `fma_metadata.zip`: `f0df49ffe5f2a6008d7dc83c6915b31835dfe733`
- `fma_medium.zip`: `c67b69ea232021025fca9231fc1c7c1a063ab50b`

Source: [FMA](https://github.com/mdeff/fma). MTG metadata and the official downloader are pinned to commit `cafd8e20c265ed84f1e61f1c875327971f43a62f`; every tar and extracted audio file is checked against that commit's SHA-256 manifests. Transfers resume with HTTP Range, retry transient failures with bounded backoff and retain strict integrity checks. Four simultaneous full transfers were used; higher concurrency returned HTTP 503 here.

The pinned MTG split-0 TSVs contain 17,982 labelled tracks (9,949 train, 3,802 validation, 4,231 test) and 56 tags. The full audio release contains 18,486 tracks and 59 tags; ambiental, horror and mellow are absent from split-0. All 100 audio archives are verified, while embedding, training, calibration and evaluation use only the official split members. The other 504 tracks are excluded. The owner confirmed this correction in [issue #2](https://github.com/opoeci6/MCRAR/issues/2#issuecomment-6117456637) and updated the handover; no split or section 4 interface was changed.

### DEAM checksum exception

The [official DEAM page](https://cvml.unige.ch/databases/DEAM/) publishes no archive checksums. The owner explicitly approved the exception in [issue #1](https://github.com/opoeci6/MCRAR/issues/1#issuecomment-6116833123). The owner and collaborator independently downloaded both archives over HTTPS on 2026-10-11 (America/Halifax) and obtained identical SHA-256 hashes. These are **observed**, not publisher-issued checksums. The committed `backend/src/mcrar/ml/datasets/deam_checksums.json` records both observers, timestamps, URLs, byte sizes, Last-Modified and ETag headers. The downloader enforces the pins without a fallback and checks all ZIP CRCs and member counts.

| Archive | Bytes | SHA-256 | ZIP members | MP3s | CRC failures |
|---|---|---|---|---|---|
| DEAM_audio.zip | 1343203527 | `e2814325f573ade8caebc697f0efcfdf7207142b737d72558a416117ca591353` | 1803 | 1802 | 0 |
| DEAM_Annotations.zip | 4735283 | `809b0feb4ba6196c1eda9b2b7b33b892b11fa71457cfceb0d47e832ed1a5f15f` | 3619 | — | 0 |

Static per-song means are mapped from [1,9] to [0,1] with `(x-1)/8`. The [DEAM manual](https://cvml.unige.ch/databases/DEAM/manual.pdf) specifies CC BY-NC without a version. Every valence/arousal artifact remains `commercial_ok: false`.

## Evaluation

Every method uses the same held-out test items within each label set. All model seeds are 0. Primary metrics are genre macro F1, mood/theme macro PR-AUC (non-interpolated average precision), and regression R². Intervals are percentile 95% item-bootstrap intervals, 1,000 resamples with seed 0. Nonlinear metrics are recomputed in each resample using the bake-off bootstrap helpers; the genre accuracy interval also reuses `bootstrap_mean_ci`. ROC-AUC excludes labels with only one class; PR-AUC for a label with no positives is zero. The registry records the valid resample/label counts.

### genre

| Variant | Test n | Primary (95% CI) | Accuracy | Top-3 | ECE |
|---|---|---|---|---|---|
| logreg | 2572 | 0.5106 [0.4849, 0.5329] | 0.7146 | 0.8950 | 0.0256 |
| mlp | 2572 | 0.5080 [0.4819, 0.5312] | 0.7189 | 0.9012 | 0.0166 |
| zeroshot-calibrated | 2572 | 0.2580 [0.2430, 0.2717] | 0.4187 | 0.7018 | 0.0340 |
| zeroshot-unsupervised | 2572 | 0.2628 [0.2453, 0.2778] | 0.3779 | 0.6365 | 0.1710 |

### moodtheme

| Variant | Test n | Primary (95% CI) | Macro ROC-AUC | ECE |
|---|---|---|---|---|
| logreg | 4231 | 0.1314 [0.1290, 0.1425] | 0.7462 | 0.0024 |
| mlp | 4231 | 0.1445 [0.1413, 0.1555] | 0.7648 | 0.0023 |
| zeroshot-calibrated | 4231 | 0.0773 [0.0751, 0.0857] | 0.6434 | 0.0030 |
| zeroshot-unsupervised | 4231 | 0.0785 [0.0765, 0.0872] | 0.6555 | 0.6306 |

### valence

| Variant | Test n | Primary (95% CI) | Pearson r | MAE |
|---|---|---|---|---|
| logreg | 181 | 0.5982 [0.5075, 0.6736] | 0.7748 | 0.0703 |
| mlp | 181 | 0.6670 [0.5847, 0.7289] | 0.8175 | 0.0656 |
| zeroshot-calibrated | 181 | 0.0177 [-0.0509, 0.0713] | 0.1510 | 0.1187 |
| zeroshot-unsupervised | 181 | -2.1198 [-2.7768, -1.6309] | -0.1517 | 0.2115 |

### arousal

| Variant | Test n | Primary (95% CI) | Pearson r | MAE |
|---|---|---|---|---|
| logreg | 181 | 0.5983 [0.4905, 0.6852] | 0.7750 | 0.0781 |
| mlp | 181 | 0.6890 [0.6074, 0.7590] | 0.8312 | 0.0684 |
| zeroshot-calibrated | 181 | -0.0017 [-0.0459, 0.0281] | 0.0472 | 0.1321 |
| zeroshot-unsupervised | 181 | -1.3038 [-1.8715, -0.8616] | 0.0581 | 0.1932 |

### MLP versus the linear baseline

- genre: MLP macro_f1 0.5080 does not exceed the linear baseline (0.5106). These are test point estimates, not a paired significance test.
  The prescribed fixed 256-unit architecture and validation-loss early stopping did not improve this test metric. Nonlinear capacity does not guarantee a gain on pretrained CLAP features; the cause was not isolated by an ablation. Selection keeps the best measured entry and no hyperparameters were tuned on the test set.
  Genre accuracy is 0.7189 for MLP versus 0.7146 for logreg, and ECE is 0.0166 versus 0.0256. These improvements do not override the prescribed macro-F1 selection rule; the primary CIs overlap.
  A per-class diagnostic of this run found lower MLP F1 for country (0.5714 vs 0.6667, 18 test items), spoken (0.1905 vs 0.2727, 12 items) and folk (0.3775 vs 0.4259, 152 items). Both heads had zero F1 for blues, easy-listening and soul-rnb (8, 6 and 42 test items). These observations explain the aggregate tradeoff, without isolating its cause.
- moodtheme: MLP macro_pr_auc 0.1445 exceeds the linear baseline (0.1314). These are test point estimates, not a paired significance test.
- valence: MLP r2 0.6670 exceeds the linear baseline (0.5982). These are test point estimates, not a paired significance test.
- arousal: MLP r2 0.6890 exceeds the linear baseline (0.5983). These are test point estimates, not a paired significance test.

### DEAM 2015 test subset

Only **held-out test** songs with ids 2001–2058 appear below. Including their training/validation songs would leak fitted data into this comparison. Seed 0 leaves only three of these songs in the test partition, so these subset statistics are highly uncertain and must not drive selection.

| Label set | Variant | n | R² | Pearson r |
|---|---|---|---|---|
| valence | logreg | 3 | -0.3006 | 0.9303 |
| valence | mlp | 3 | -0.5670 | 0.8258 |
| valence | zeroshot-calibrated | 3 | -1.6640 | -0.9966 |
| valence | zeroshot-unsupervised | 3 | 0.6855 | 0.9915 |
| arousal | logreg | 3 | 0.3966 | 0.6468 |
| arousal | mlp | 3 | 0.4588 | 0.8083 |
| arousal | zeroshot-calibrated | 3 | -0.3612 | -0.3457 |
| arousal | zeroshot-unsupervised | 3 | -0.9928 | -0.3438 |

## Selection and licences

Selection is the highest finite test primary metric among permitted entries; ties use the entry id for deterministic ordering. Evaluation labels alone do not fit the unlabelled commercial fallback. All parameters fitted to MTG/DEAM labels, including calibration, are non-commercial.

| Label set | Commercial mode | Non-commercial mode |
|---|---|---|
| genre | genre-logreg@2b67df0 | genre-logreg@2b67df0 |
| moodtheme | moodtheme-zeroshot-unsupervised@15d3513 | moodtheme-mlp@b2ac67d |
| valence | no entry | valence-mlp@f2069d3 |
| arousal | no entry | arousal-mlp@51348c6 |

## Heads and calibration

Logistic regression uses C=10 with up to 1,000 iterations; mood/theme uses independent balanced binary classifiers, and continuous labels use ridge regression (alpha=1). The MLP uses one 256-unit ReLU hidden layer, dropout 0.2, Adam (learning rate 0.001), batches of 256, up to 100 epochs and patience 12 on the official validation loss. Mood/theme uses a capped positive-class loss weight. Training/export and runtime predictions use numeric numpy arrays; no pickle is saved or loaded and inference needs no torch.

Classification heads and zero-shot scores use validation-only temperature scaling (genre) or per-label Platt scaling (mood/theme). ECE uses 15 equal-width probability bins. Continuous outputs use validation-only affine calibration and clipping to [0,1]; MAE is reported rather than classification ECE. Unsupervised zero-shot variants use only FMA training audio embeddings to estimate per-label score means/stds, with fixed slope 1; labels never enter that fitter. Regression/multi-label outputs use sigmoid, genre uses softmax.

Prompt scores are mean cosine over templates × synonyms; the averaged text vectors are intentionally not renormalised. Full prompt vectors, texts and the prompt file hash are stored in each zero-shot NPZ. A GPU test compares them against a fresh pinned CLAP load.

## Domain shift and failure cases

FMA uses 30 s clips, while MTG and the catalog use full tracks capped at 240 s; DEAM mixes 45 s excerpts and 2015 full songs. Sparse three-window sampling can miss intros, outros and changing moods. Genre categories overlap; rare genres and subjective mood/theme labels are difficult. The unsupervised fallback produces bounded scores without supervised probability calibration. The weak continuous zero-shot results show that pleasant/intense prompt similarity is not a reliable substitute for trained emotion regression. Corrupt or sub-second audio is counted in each dataset's embedding report; missing embeddings fail catalog tagging clearly.

The commercial mood/theme fallback is poorly calibrated in this run: ECE 0.6306, macro PR-AUC 0.0785 and macro ROC-AUC 0.6555. Its scores support relative ranking; calibrated probability thresholds are unreliable.

The optional M3c CNN and owner-catalog weak-label sanity check were not run; this milestone uses the prescribed CLAP heads and no Jamendo API key.

## Hardware and recorded time

NVIDIA GeForce RTX 4080 SUPER (16,376 MiB), driver 595.97, CUDA PyTorch 2.11.0+cu130. Embedding CLI uses at most 32 windows per forward pass and bounds BLAS/OpenMP CPU thread pools to four. The pinned Hugging Face test weights were cached as ordinary repo-local files because Windows denied a symlink; no system settings were changed.

| Dataset | Device | Dtype | Recorded embedding seconds |
|---|---|---|---|
| fma-medium | cuda | fp16 | 2212.9220 |
| mtg-moodtheme | cuda | fp16 | 2098.2350 |
| deam | cuda | fp16 | — |

Sum of per-entry training/evaluation wall times: 195.4 s (includes prompt model loading and bootstrap evaluation). Embedding timing covers the final embedding loop, excluding CLAP loading, setup/downloads and earlier interrupted invocations. DEAM embedding wall time was not captured. Detailed per-entry times and seeds are in the registry.

## Reproduction

Run every command with `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\with-env.ps1` (or `scripts/with-env.sh`). The repo-local bootstrap and `mcrar doctor` establish/verify the environment. Then:

```text
uv run --directory backend mcrar datasets download fma-medium|mtg-moodtheme|deam
uv run --directory backend mcrar datasets embed <dataset> --batch-size 32 --device cuda
uv run --directory backend mcrar tagging train <label-set> --variant <variant>
uv run --directory backend mcrar tagging evaluate
uv run --directory backend mcrar tagging select
uv run --directory backend mcrar tag [--label-sets genre,moodtheme] [--force]
uv run --directory backend python -m mcrar.ml.tagging.report
```

Label sets: genre, moodtheme, valence, arousal. Variants: logreg, mlp, zeroshot-calibrated, zeroshot-unsupervised. Dataset embeddings and raw audio remain git-ignored in `data/`; audio can be removed with `--delete-audio` only after its embedding has been checkpointed. No optional embedding release was uploaded.
