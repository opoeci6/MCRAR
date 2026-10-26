"""Train, evaluate and publish licensed artifacts without coupling CLI or runtime to training."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import numpy as np

from mcrar.config import Settings
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.datasets.service import MTG_MEMBERSHIP, dataset_root, samples_for, training_data
from mcrar.ml.tagging.metrics import evaluate
from mcrar.ml.tagging.registry import entry_id, read_registry, select_entry, write_registry
from mcrar.ml.tagging.runtime import Tagger, load_tagger

DATASETS = {
    "genre": "fma-medium",
    "moodtheme": "mtg-moodtheme",
    "valence": "deam",
    "arousal": "deam",
}
VARIANTS = ("mlp", "logreg", "zeroshot-calibrated", "zeroshot-unsupervised")


def _dataset(label_set: str) -> str:
    if label_set not in DATASETS:
        raise ValueError(f"unknown label set: {label_set}; choose from {', '.join(DATASETS)}")
    return DATASETS[label_set]


def prediction_matrix(tagger: Tagger, x: np.ndarray) -> np.ndarray:
    probs = tagger.predict(x)
    return np.column_stack([probs[label] for label in tagger.labels])


def reference_embeddings(settings: Settings) -> np.ndarray:
    # Read only split membership and embeddings; no target arrays reach the label-free fitter.
    samples = samples_for(settings, "fma-medium")
    train_ids = {s.id for s in samples if s.split == "train"}
    path = dataset_root(settings, "fma-medium") / f"embeddings/{EMBEDDER}.npz"
    with np.load(path, allow_pickle=False) as data:
        ids, matrix = data["ids"], data["matrix"]
    if (
        matrix.dtype != np.float32
        or matrix.shape != (len(ids), 512)
        or len(set(ids.tolist())) != len(ids)
        or not np.isfinite(matrix).all()
        or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-3)
    ):
        raise ValueError("invalid unlabelled FMA reference embeddings")
    expected, present = {s.id for s in samples}, set(ids.tolist())
    if present - expected:
        raise ValueError("reference embedding ids are outside FMA metadata")
    if missing := expected - present:
        report_path = path.with_suffix(".report.json")
        if not report_path.is_file() or missing != {
            int(i) for i in json.loads(report_path.read_text())["failures"]
        }:
            raise ValueError("FMA reference embedding run is incomplete; resume datasets embed")
    return matrix[np.isin(ids, list(train_ids))].copy()


def train_entry(
    settings: Settings,
    label_set: str,
    variant: str,
    *,
    seed: int = 0,
    epochs: int = 100,
    n_resamples: int = 1000,
) -> dict:
    from mcrar.ml.tagging.training import calibrate, train_logreg, train_mlp
    from mcrar.ml.tagging.zeroshot import PROMPTS, calibrated, prompt_vectors, unsupervised

    started = time.monotonic()
    name = _dataset(label_set)
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {', '.join(VARIANTS)}")
    provenance_path = dataset_root(settings, name) / "provenance.json"
    if not provenance_path.is_file():
        raise ValueError(f"{name}: no verified download provenance; run mcrar datasets download")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if name == "mtg-moodtheme":
        # Also annotate verified downloads completed before the handover count correction.
        provenance.update(MTG_MEMBERSHIP)
    ids, x, y, splits, labels, kind = training_data(settings, name, label_set)
    train, valid, test = [splits == s for s in ("train", "validation", "test")]
    if variant == "logreg":
        tagger = calibrate(
            train_logreg(label_set, kind, labels, x[train], y[train], seed=seed), x[valid], y[valid]
        )
    elif variant == "mlp":
        tagger = calibrate(
            train_mlp(
                label_set,
                kind,
                labels,
                x[train],
                y[train],
                x[valid],
                y[valid],
                seed=seed,
                epochs=epochs,
            ),
            x[valid],
            y[valid],
        )
    else:
        from mcrar.ml.embedders import load_embedder

        embedder = load_embedder("clap", settings=settings)
        try:
            vectors = prompt_vectors(embedder, PROMPTS / f"{label_set}.toml", labels)
        finally:
            close = getattr(embedder, "close", None)
            if close:
                close()
        tagger = (
            calibrated(label_set, kind, labels, vectors, x[valid], y[valid])
            if variant == "zeroshot-calibrated"
            else unsupervised(label_set, kind, labels, vectors, reference_embeddings(settings))
        )
    metrics = evaluate(
        y[test],
        prediction_matrix(tagger, x[test]),
        kind,
        ids=ids[test],
        n_resamples=n_resamples,
        seed=0,
    )
    heads = settings.models_dir / "heads"
    heads.mkdir(parents=True, exist_ok=True)
    temporary = heads / f".{label_set}-{variant}.npz"
    tagger.save(temporary)
    identity = entry_id(label_set, variant, temporary)
    path = heads / f"{identity}.npz"
    temporary.replace(path)
    source_licence = (
        "CC BY 4.0"
        if label_set == "genre"
        else "CC BY-NC-SA 4.0"
        if label_set == "moodtheme"
        else "CC BY-NC (version unspecified, per DEAM manual)"
    )
    commercial = label_set == "genre" or (
        label_set == "moodtheme" and variant == "zeroshot-unsupervised"
    )
    entry = {
        "id": identity,
        "method": tagger.method,
        "variant": variant,
        "file": f"heads/{identity}.npz",
        "seed": seed,
        "metrics": metrics,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "commercial_ok": commercial,
        "data_license": source_licence,
        "dataset_provenance": provenance,
        "training_seconds": time.monotonic() - started,
        "embedding": {"model": EMBEDDER, "max_seconds": 240, "windows": [0.2, 0.5, 0.8]},
        "split_counts": {s: int((splits == s).sum()) for s in ("train", "validation", "test")},
    }
    if tagger.method == "head":
        entry["train_data"] = (
            f"{name} ({'seeded 80/10/10, seed 0' if name == 'deam' else 'official split'})"
        )
        entry["calibration_data"] = f"{name} validation split"
        if variant == "mlp":
            entry["architecture"] = {
                "hidden": 256,
                "activation": "relu",
                "dropout": 0.2,
                "epochs_limit": epochs,
                "patience": 12,
                "optimizer": "Adam",
            }
    else:
        entry["prompts"] = f"backend/src/mcrar/ml/tagging/prompts/{label_set}.toml"
        if variant == "zeroshot-calibrated":
            entry["calibration_data"] = f"{name} validation split"
        else:
            entry["reference_data"] = "FMA-medium training audio embeddings (no labels), slope 1"
            entry["data_license"] = (
                "FMA per-track Creative Commons audio; CC BY 4.0 metadata; labels unused"
                if label_set not in {"valence", "arousal"}
                else source_licence
            )
    registry_path = settings.models_dir / "registry.json"
    registry = (
        read_registry(settings)
        if registry_path.is_file()
        else {"schema": 1, "embedder": EMBEDDER, "label_sets": {}}
    )
    spec = registry["label_sets"].setdefault(
        label_set,
        {
            "kind": kind,
            "labels": labels,
            "display": {t: t.replace("-", " ").title() for t in labels},
            "entries": [],
        },
    )
    if (spec["kind"], spec["labels"]) != (kind, labels):
        raise ValueError("dataset labels do not match the stable registry labels")
    spec["entries"] = [e for e in spec["entries"] if e["variant"] != variant] + [entry]
    write_registry(settings, registry)
    return entry


def evaluate_entries(
    settings: Settings, label_sets: list[str] | None = None, *, n_resamples: int = 1000
) -> tuple[dict, object]:
    registry = read_registry(settings)
    # Sets without a labelled dataset (the zero-shot ``scene`` set) have nothing to evaluate on.
    selected = label_sets or [name for name in registry["label_sets"] if name in DATASETS]
    result = {"schema": 1, "embedder": EMBEDDER, "label_sets": {}}
    for name in selected:
        if name not in registry["label_sets"]:
            raise ValueError(f"unknown registry label set: {name}")
        ids, x, y, splits, labels, kind = training_data(settings, _dataset(name), name)
        test = splits == "test"
        rows = []
        for entry in registry["label_sets"][name]["entries"]:
            tagger = load_tagger(settings.models_dir / entry["file"], entry["id"])
            if tagger.labels != labels:
                raise ValueError("evaluation labels do not match the artifact")
            metrics = evaluate(
                y[test],
                prediction_matrix(tagger, x[test]),
                kind,
                ids=ids[test],
                n_resamples=n_resamples,
            )
            entry["metrics"] = metrics
            rows.append({"id": entry["id"], "variant": entry["variant"], "metrics": metrics})
        result["label_sets"][name] = rows
    write_registry(settings, registry)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = settings.data_dir / f"benchmarks/results/tagging_{timestamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result, output


def selected_entries(settings: Settings) -> dict:
    registry = read_registry(settings)
    selections = {
        name: (entry["id"] if (entry := select_entry(spec)) else None)
        for name, spec in registry["label_sets"].items()
    }
    registry["selected"] = selections
    write_registry(settings, registry)
    return selections
