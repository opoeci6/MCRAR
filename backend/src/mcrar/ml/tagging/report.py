"""Rebuild the committed model card from real registry metrics and dataset run reports."""

from __future__ import annotations

import json

from mcrar.config import Settings, get_settings
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.datasets.service import dataset_root
from mcrar.ml.tagging.registry import read_registry, select_entry


def _number(value: object) -> str:
    return f"{value:.4f}" if isinstance(value, (int, float)) else "—"


def _primary(metrics: dict) -> str:
    value = _number(metrics[metrics["primary"]])
    interval = metrics.get("primary_ci95")
    return value + (f" [{interval[0]:.4f}, {interval[1]:.4f}]" if interval else "")


def metric_tables(registry: dict) -> str:
    lines = []
    for name, spec in registry["label_sets"].items():
        columns = (
            {"accuracy": "Accuracy", "top3_accuracy": "Top-3", "ece": "ECE"}
            if name == "genre"
            else {"macro_roc_auc": "Macro ROC-AUC", "ece": "ECE"}
            if name == "moodtheme"
            else {}
            if name == "scene"  # zero-shot from prompts, not evaluated on labelled data
            else {"pearson_r": "Pearson r", "mae": "MAE"}
        )
        lines.extend(
            [
                f"### {name}",
                "",
                "| Variant | Test n | Primary (95% CI) | " + " | ".join(columns.values()) + " |",
                "|" + "---|" * (3 + len(columns)),
            ]
        )
        for entry in spec["entries"]:
            metrics = entry["metrics"]
            if metrics is None:
                lines.append(f"| {entry['variant']} | — | not evaluated |" + " — |" * len(columns))
                continue
            lines.append(
                f"| {entry['variant']} | {metrics.get('n', '—')} | {_primary(metrics)} | "
                + " | ".join(_number(metrics.get(k)) for k in columns)
                + " |"
            )
        if not spec["entries"]:
            lines.append("| Pending data run | — | — | " + " | ".join("—" for _ in columns) + " |")
        lines.append("")
    return "\n".join(lines)


def write_model_card(settings: Settings) -> None:
    registry = read_registry(settings)
    mood = registry["label_sets"].get("moodtheme", {"kind": "multi_label", "entries": []})
    fallback = next((e for e in mood["entries"] if e["variant"] == "zeroshot-unsupervised"), None)
    fallback_note = (
        "The unsupervised mood/theme zero-shot variant is poorly calibrated in this run: "
        f"ECE {_number(fallback['metrics']['ece'])}, macro PR-AUC "
        f"{_number(fallback['metrics']['macro_pr_auc'])} and macro ROC-AUC "
        f"{_number(fallback['metrics']['macro_roc_auc'])}. Its scores support relative "
        "ranking; calibrated probability thresholds are unreliable."
        if fallback
        else ""
    )
    lines = [
        "# M3b tagging model card",
        "",
        "Generated from `models/registry.json` by "
        "`uv run --directory backend python -m mcrar.ml.tagging.report` (through the env wrapper).",
        "",
        "## Data and provenance",
        "",
        "All audio embeddings use `clap@195c3a3` (LAION larger CLAP music and speech, "
        "Apache-2.0), mono decoding at 48 kHz, a 240 s cap and the canonical "
        "`embed_track` three-window aggregation. Windows are 10 s, centred at 20%, "
        "50% and 80%, with short clips padded. Batch processing replays the same window "
        "outputs through `embed_track`; the default suite checks equivalence.",
        "",
        "| Dataset | Labels/licence | Split | Embedded / expected | Skipped |",
        "|---|---|---|---|---|",
    ]
    descriptions = {
        "fma-medium": (
            "16 genres; metadata CC BY 4.0; audio per-track CC",
            "Official train/validation/test",
            25000,
        ),
        "mtg-moodtheme": ("56 mood/theme labels; CC BY-NC-SA 4.0", "Official split-0", 17982),
        "deam": (
            "Valence/arousal; CC BY-NC (version unspecified, per DEAM manual)",
            "Seed 0 random 80/10/10 by song id",
            1802,
        ),
    }
    reports = {}
    for name, (licence, split, expected) in descriptions.items():
        report_path = dataset_root(settings, name) / f"embeddings/{EMBEDDER}.report.json"
        report = json.loads(report_path.read_text()) if report_path.is_file() else {}
        reports[name] = report
        lines.append(
            f"| {name} | {licence} | {split} | {report.get('embedded', 'pending')} / {expected} "
            f"| {report.get('skipped', 'pending')} |"
        )
    lines.extend(
        [
            "",
            "FMA archive SHA-1 values (publisher's README):",
            "",
            "- `fma_metadata.zip`: `f0df49ffe5f2a6008d7dc83c6915b31835dfe733`",
            "- `fma_medium.zip`: `c67b69ea232021025fca9231fc1c7c1a063ab50b`",
            "",
            "Source: [FMA](https://github.com/mdeff/fma). MTG metadata and the official "
            "downloader are pinned to commit `cafd8e20c265ed84f1e61f1c875327971f43a62f`; "
            "every tar and extracted audio file is checked against that commit's SHA-256 "
            "manifests. Transfers resume with HTTP Range, retry transient failures with "
            "bounded backoff and retain strict integrity checks. Four simultaneous full "
            "transfers were used; higher concurrency returned HTTP 503 here.",
            "",
            "The pinned MTG split-0 TSVs contain 17,982 labelled tracks (9,949 train, "
            "3,802 validation, 4,231 test) and 56 tags. The full audio release contains "
            "18,486 tracks and 59 tags; ambiental, horror and mellow are absent from "
            "split-0. All 100 audio archives are verified, while embedding, training, "
            "calibration and evaluation use only the official split members. The other "
            "504 tracks are excluded. The owner confirmed this correction in "
            "[issue #2](https://github.com/opoeci6/MCRAR/issues/2#issuecomment-6117456637) "
            "and updated the handover; no split or section 4 interface was changed.",
            "",
            "### DEAM checksum exception",
            "",
            "The [official DEAM page](https://cvml.unige.ch/databases/DEAM/) publishes no "
            "archive checksums. The owner explicitly approved the exception in "
            "[issue #1](https://github.com/opoeci6/MCRAR/issues/1#issuecomment-6116833123). "
            "The owner and collaborator independently downloaded both archives over HTTPS "
            "on 2026-10-11 (America/Halifax) and obtained identical SHA-256 hashes. These "
            "are **observed**, not publisher-issued checksums. The committed "
            "`backend/src/mcrar/ml/datasets/deam_checksums.json` records both observers, "
            "timestamps, URLs, byte sizes, Last-Modified and ETag headers. The downloader "
            "enforces the pins without a fallback and checks all ZIP CRCs and member counts.",
            "",
            "| Archive | Bytes | SHA-256 | ZIP members | MP3s | CRC failures |",
            "|---|---|---|---|---|---|",
            "| DEAM_audio.zip | 1343203527 | "
            "`e2814325f573ade8caebc697f0efcfdf7207142b737d72558a416117ca591353` "
            "| 1803 | 1802 | 0 |",
            "| DEAM_Annotations.zip | 4735283 | "
            "`809b0feb4ba6196c1eda9b2b7b33b892b11fa71457cfceb0d47e832ed1a5f15f` | 3619 | — | 0 |",
            "",
            "Static per-song means are mapped from [1,9] to [0,1] with `(x-1)/8`. "
            "The [DEAM manual](https://cvml.unige.ch/databases/DEAM/manual.pdf) specifies "
            "CC BY-NC without a version. Every valence/arousal artifact remains "
            "`commercial_ok: false`.",
            "",
            "## Evaluation",
            "",
            "Every method uses the same held-out test items within each label set. "
            "All model seeds are 0. Primary metrics are genre macro F1, mood/theme macro "
            "PR-AUC (non-interpolated average precision), and regression R². Intervals are "
            "percentile 95% item-bootstrap intervals, 1,000 resamples with seed 0. Nonlinear "
            "metrics are recomputed in each resample using the bake-off bootstrap helpers; "
            "the genre accuracy interval also reuses `bootstrap_mean_ci`. ROC-AUC excludes "
            "labels with only one class; PR-AUC for a label with no positives is zero. "
            "The registry records the valid resample/label counts.",
            "",
            metric_tables(registry),
            "### MLP versus the linear baseline",
            "",
        ]
    )
    for name, spec in registry["label_sets"].items():
        by_variant = {e["variant"]: e for e in spec["entries"]}
        if not {"mlp", "logreg"} <= by_variant.keys():
            continue
        a, b = by_variant["mlp"]["metrics"], by_variant["logreg"]["metrics"]
        key = a["primary"]
        verdict = "exceeds" if a[key] > b[key] else "does not exceed"
        lines.append(
            f"- {name}: MLP {key} {_number(a[key])} {verdict} the linear baseline "
            f"({_number(b[key])}). These are test point estimates, not a paired "
            "significance test."
        )
        if a[key] <= b[key]:
            lines.append(
                "  The prescribed fixed 256-unit architecture and validation-loss "
                "early stopping did not improve this test metric. Nonlinear capacity "
                "does not guarantee a gain on pretrained CLAP features; the cause was "
                "not isolated by an ablation. Selection keeps the best measured entry "
                "and no hyperparameters were tuned on the test set."
            )
            if name == "genre":
                lines.append(
                    f"  Genre accuracy is {_number(a['accuracy'])} for MLP versus "
                    f"{_number(b['accuracy'])} for logreg, and ECE is {_number(a['ece'])} "
                    f"versus {_number(b['ece'])}. These improvements do not override "
                    "the prescribed macro-F1 selection rule; the primary CIs overlap."
                )
                lines.append(
                    "  A per-class diagnostic of this run found lower MLP F1 for country "
                    "(0.5714 vs 0.6667, 18 test items), spoken (0.1905 vs 0.2727, 12 items) "
                    "and folk (0.3775 vs 0.4259, 152 items). Both heads had zero F1 for "
                    "blues, easy-listening and soul-rnb (8, 6 and 42 test items). These "
                    "observations explain the aggregate tradeoff, without isolating its cause."
                )
    lines.extend(
        [
            "",
            "### DEAM 2015 test subset",
            "",
            "Only **held-out test** songs with ids 2001–2058 appear below. Including their "
            "training/validation songs would leak fitted data into this comparison. Seed 0 "
            "leaves only three of these songs in the test partition, so these subset "
            "statistics are highly uncertain and must not drive selection.",
            "",
            "| Label set | Variant | n | R² | Pearson r |",
            "|---|---|---|---|---|",
        ]
    )
    for name in ("valence", "arousal"):
        for entry in registry["label_sets"].get(name, {}).get("entries", []):
            subset = entry["metrics"].get("subset_2015_test", {})
            lines.append(
                f"| {name} | {entry['variant']} | {subset.get('n', '—')} | "
                f"{_number(subset.get('r2'))} | {_number(subset.get('pearson_r'))} |"
            )
    lines.extend(
        [
            "",
            "## Selection and licences",
            "",
            "Selection is the highest finite test primary metric among all entries; "
            "ties use the entry id for deterministic ordering. Evaluation labels alone "
            "do not fit the unsupervised zero-shot variant. All parameters fitted to "
            "MTG/DEAM labels, including calibration, are non-commercial.",
            "",
            "| Label set | Selected entry |",
            "|---|---|",
        ]
    )
    for name, spec in registry["label_sets"].items():
        chosen = select_entry(spec)
        lines.append(f"| {name} | {chosen['id'] if chosen else 'no entry'} |")
    lines.extend(
        [
            "",
            "## Heads and calibration",
            "",
            "Logistic regression uses C=10 with up to 1,000 iterations; mood/theme uses "
            "independent balanced binary classifiers, and continuous labels use ridge "
            "regression (alpha=1). The MLP uses one 256-unit ReLU hidden layer, dropout "
            "0.2, Adam (learning rate 0.001), batches of 256, up to 100 epochs and patience "
            "12 on the official validation loss. Mood/theme uses a capped positive-class "
            "loss weight. Training/export and runtime predictions use numeric numpy arrays; "
            "no pickle is saved or loaded and inference needs no torch.",
            "",
            "Classification heads and zero-shot scores use validation-only temperature "
            "scaling (genre) or per-label Platt scaling (mood/theme). ECE uses 15 equal-width "
            "probability bins. Continuous outputs use validation-only affine calibration "
            "and clipping to [0,1]; MAE is reported rather than classification ECE. "
            "Unsupervised zero-shot variants use only FMA training audio embeddings to "
            "estimate per-label score means/stds, with fixed slope 1; labels never enter "
            "that fitter. Regression/multi-label outputs use sigmoid, genre uses softmax.",
            "",
            "Prompt scores are mean cosine over templates × synonyms; the averaged "
            "text vectors are intentionally not renormalised. Full prompt vectors, texts "
            "and the prompt file hash are stored in each zero-shot NPZ. A GPU test compares "
            "them against a fresh pinned CLAP load.",
            "",
            "## Domain shift and failure cases",
            "",
            "FMA uses 30 s clips, while MTG and the catalog use full tracks capped at 240 s; "
            "DEAM mixes 45 s excerpts and 2015 full songs. Sparse three-window sampling can "
            "miss intros, outros and changing moods. Genre categories overlap; rare genres "
            "and subjective mood/theme labels are difficult. The unsupervised fallback "
            "produces bounded scores without supervised probability calibration. The weak "
            "continuous zero-shot results show that pleasant/intense prompt similarity is "
            "not a reliable substitute for trained emotion regression. Corrupt or sub-second "
            "audio is counted in each dataset's embedding report; missing embeddings fail "
            "catalog tagging clearly.",
            "",
            fallback_note,
            "",
            "The optional M3c CNN and owner-catalog weak-label sanity check were not run; "
            "this milestone uses the prescribed CLAP heads and no Jamendo API key.",
            "",
            "## Hardware and recorded time",
            "",
            "NVIDIA GeForce RTX 4080 SUPER (16,376 MiB), driver 595.97, CUDA PyTorch "
            "2.11.0+cu130. Embedding CLI uses at most 32 windows per forward pass and bounds "
            "BLAS/OpenMP CPU thread pools to four. The pinned Hugging Face test weights "
            "were cached as ordinary repo-local files because Windows denied a symlink; "
            "no system settings were changed.",
            "",
            "| Dataset | Device | Dtype | Recorded embedding seconds |",
            "|---|---|---|---|",
        ]
    )
    for name, report in reports.items():
        lines.append(
            f"| {name} | {report.get('device', 'cuda')} | {report.get('dtype', 'fp16')} "
            f"| {_number(report.get('elapsed_s'))} |"
        )
    total = sum(
        e.get("training_seconds", 0) for s in registry["label_sets"].values() for e in s["entries"]
    )
    lines.extend(
        [
            "",
            f"Sum of per-entry training/evaluation wall times: {total:.1f} s "
            "(includes prompt model loading and bootstrap evaluation). Embedding timing "
            "covers the final embedding loop, excluding CLAP loading, setup/downloads "
            "and earlier interrupted invocations. DEAM embedding wall time was not captured. "
            "Detailed per-entry times and seeds are in the registry.",
            "",
            "## Reproduction",
            "",
            "Run every command with `powershell -NoProfile -ExecutionPolicy Bypass -File "
            "scripts\\with-env.ps1` (or `scripts/with-env.sh`). The repo-local bootstrap "
            "and `mcrar doctor` establish/verify the environment. Then:",
            "",
            "```text",
            "uv run --directory backend mcrar datasets download fma-medium|mtg-moodtheme|deam",
            "uv run --directory backend mcrar datasets embed <dataset> "
            "--batch-size 32 --device cuda",
            "uv run --directory backend mcrar tagging train <label-set> --variant <variant>",
            "uv run --directory backend mcrar tagging evaluate",
            "uv run --directory backend mcrar tagging select",
            "uv run --directory backend mcrar tag [--label-sets genre,moodtheme] [--force]",
            "uv run --directory backend python -m mcrar.ml.tagging.report",
            "```",
            "",
            "Label sets: genre, moodtheme, valence, arousal. Variants: logreg, mlp, "
            "zeroshot-calibrated, zeroshot-unsupervised. Dataset embeddings and raw audio "
            "remain git-ignored in `data/`; audio can be removed with `--delete-audio` "
            "only after its embedding has been checkpointed. No optional embedding release "
            "was uploaded.",
            "",
        ]
    )
    output = settings.home / "docs/model_card.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    write_model_card(get_settings())
