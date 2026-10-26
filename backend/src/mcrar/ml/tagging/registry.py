"""Validate content-addressed artifacts and select the best test-split entry.

An entry may carry ``metrics: null`` (not evaluated yet); such an entry is selected only when its
label set has no evaluated one. The ``scene`` set has no test split: its entries may instead be
scored by cross-validation on hand labels (``split: "hand-labels-cv"``, primary
``mean_p_at_10``), which :func:`select_entry` prefers over everything else.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from mcrar.config import Settings
from mcrar.ml.datasets.download import digest
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.tagging.runtime import Tagger, load_tagger

PRIMARY = {"single_label": "macro_f1", "multi_label": "macro_pr_auc", "regression": "r2"}
# "NC" as a licence element (CC BY-NC-SA ...), not as letters inside a word such as "reference"
_NON_COMMERCIAL = re.compile(r"\bNC\b|NON-?COMMERCIAL", re.IGNORECASE)


def entry_id(label_set: str, variant: str, path: Path) -> str:
    return f"{label_set}-{variant}@{digest(path)[:7]}"


# The scene set has no labelled dataset: its entries are scored on the owner's hand labels by
# cross-validation (mean precision@10 over the scenes with enough positives).
HAND_LABELS_SPLIT = "hand-labels-cv"
HAND_LABELS_PRIMARY = "mean_p_at_10"
HAND_LABELS_SETS = ("scene",)


def _finite(metrics: dict, key: str) -> bool:
    return isinstance(metrics.get(key), (int, float)) and math.isfinite(metrics[key])


def _hand_label_rank(entry: dict) -> tuple[bool, float]:
    """Preference among equal scores, larger is better: a zero-shot entry before a trained head
    (the simpler model), and among zero-shot entries the lower centering."""
    return entry["method"] == "zeroshot", -float(entry.get("centering", 0.0))


def select_entry(label_set: dict) -> dict | None:
    """The entry with the best finite primary metric.

    Entries scored on hand labels (``split == "hand-labels-cv"``, the ``scene`` set only) come
    first: the best ``mean_p_at_10`` wins, ties go to the simpler entry (zero-shot before head,
    then the lower ``centering``, then the larger id). Otherwise the best test-split primary
    metric wins (ties: the larger id).

    Entries without metrics (``metrics: null``, e.g. the zero-shot scene taggers before any
    labels exist) only count when no entry has any: then an entry marked ``"prefer": true`` wins,
    else the newest (by ``created_at``, then id).
    """
    metric = PRIMARY[label_set["kind"]]
    hand = [
        e
        for e in label_set["entries"]
        if (m := e["metrics"]) is not None
        and m.get("split") == HAND_LABELS_SPLIT
        and m.get("primary") == HAND_LABELS_PRIMARY
        and _finite(m, HAND_LABELS_PRIMARY)
    ]
    if hand:
        return max(
            hand, key=lambda e: (e["metrics"][HAND_LABELS_PRIMARY], *_hand_label_rank(e), e["id"])
        )
    candidates = [
        e
        for e in label_set["entries"]
        if (m := e["metrics"]) is not None
        and m.get("split") == "test"
        and m.get("primary") == metric
        and _finite(m, metric)
    ]
    if candidates:
        return max(candidates, key=lambda e: (e["metrics"][metric], e["id"]))
    unevaluated = [e for e in label_set["entries"] if e["metrics"] is None]
    return (
        max(unevaluated, key=lambda e: (bool(e.get("prefer")), e.get("created_at", ""), e["id"]))
        if unevaluated
        else None
    )


def _check_metrics(name: str, primary: str, m: object) -> None:
    """Metrics must be test-split ones with a finite primary; the scene set may instead carry
    cross-validated hand-label metrics (no other set may use that split)."""
    if isinstance(m, dict) and name in HAND_LABELS_SETS and m.get("split") == HAND_LABELS_SPLIT:
        primary = HAND_LABELS_PRIMARY
        if m.get("primary") != primary:
            raise ValueError(f"hand-label metrics need the {primary} primary")
    elif not isinstance(m, dict) or m.get("split") != "test" or m.get("primary") != primary:
        raise ValueError(
            "selection requires test-split metrics"
            + (" (or hand-labels-cv metrics)" if name in HAND_LABELS_SETS else "")
        )
    if not _finite(m, primary):
        raise ValueError("primary metric must be finite")


def validate_registry(registry: dict, models: Path | None = None) -> None:
    if registry.get("schema") != 1 or registry.get("embedder") != EMBEDDER:
        raise ValueError("registry requires schema 1 and clap@195c3a3")
    if not isinstance(registry.get("label_sets"), dict):
        raise ValueError("registry has no label_sets")
    ids = set()
    for name, spec in registry["label_sets"].items():
        labels = spec.get("labels", [])
        if not re.fullmatch(r"[a-z0-9-]+", name) or spec.get("kind") not in PRIMARY:
            raise ValueError(f"invalid label set: {name}")
        if (
            not labels
            or len(set(labels)) != len(labels)
            or any(not re.fullmatch(r"[a-z0-9-]+", label) for label in labels)
            or set(spec.get("display", {})) != set(labels)
        ):
            raise ValueError(f"invalid labels/display for {name}")
        if spec["kind"] == "regression" and labels != ["value"]:
            raise ValueError(f"{name}: regression requires the value label")
        for entry in spec["entries"]:
            required = {
                "id",
                "method",
                "variant",
                "file",
                "data_license",
                "commercial_ok",
                "seed",
                "metrics",
                "created_at",
            }
            if not required <= entry.keys() or not isinstance(entry["commercial_ok"], bool):
                raise ValueError(f"incomplete registry entry for {name}")
            if entry["method"] not in {"head", "zeroshot"}:
                raise ValueError("invalid entry method")
            if not entry["data_license"] or not isinstance(entry["seed"], int):
                raise ValueError("entry needs a data licence and deterministic seed")
            if entry["id"] in ids:
                raise ValueError("duplicate entry id")
            ids.add(entry["id"])
            variant = entry["variant"]
            if not isinstance(variant, str) or not re.fullmatch(r"[a-z0-9-]+", variant):
                raise ValueError("entry variant must be a lowercase stable identifier")
            if not re.fullmatch(re.escape(f"{name}-{variant}@") + r"[0-9a-f]{7}", entry["id"]):
                raise ValueError(f"invalid entry id: {entry['id']}")
            relative = Path(entry["file"])
            if relative.as_posix() != f"heads/{entry['id']}.npz":
                raise ValueError("artifact path must match its content-addressed entry id")
            m = entry["metrics"]
            primary = PRIMARY[spec["kind"]]
            if m is not None:  # null: not evaluated (no labelled data yet)
                _check_metrics(name, primary, m)
            if entry["commercial_ok"] and (
                name in {"valence", "arousal"}
                or (
                    name == "moodtheme"
                    and (entry["method"], entry["variant"]) != ("zeroshot", "zeroshot-unsupervised")
                )
                or _NON_COMMERCIAL.search(entry["data_license"])
            ):
                raise ValueError("non-commercial fitted parameters cannot be commercial-safe")
            if models is not None:
                path = models / relative
                if entry_id(name, variant, path) != entry["id"]:
                    raise ValueError(f"artifact hash mismatch: {entry['id']}")
                tagger = load_tagger(path, entry["id"])
                if (tagger.label_set, tagger.kind, tagger.labels, tagger.method) != (
                    name,
                    spec["kind"],
                    labels,
                    entry["method"],
                ):
                    raise ValueError("artifact metadata does not match registry")


def read_registry(settings: Settings) -> dict:
    path = settings.models_dir / "registry.json"
    if not path.is_file():
        raise ValueError("no tagging registry; run mcrar tagging train first")
    registry = json.loads(path.read_text(encoding="utf-8"))
    validate_registry(registry, settings.models_dir)
    return registry


def write_registry(settings: Settings, registry: dict) -> None:
    validate_registry(registry, settings.models_dir)
    path = settings.models_dir / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(registry, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_taggers(settings: Settings) -> list[Tagger]:
    registry = read_registry(settings)
    result = []
    for spec in registry["label_sets"].values():
        entry = select_entry(spec)
        if entry is not None:
            result.append(load_tagger(settings.models_dir / entry["file"], entry["id"]))
    return result
