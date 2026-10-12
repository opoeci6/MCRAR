"""Validate content-addressed artifacts and select the best permitted test-split entry."""

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


def entry_id(label_set: str, variant: str, path: Path) -> str:
    return f"{label_set}-{variant}@{digest(path)[:7]}"


def select_entry(label_set: dict, commercial_mode: bool = True) -> dict | None:
    metric = PRIMARY[label_set["kind"]]
    candidates = [
        e
        for e in label_set["entries"]
        if (e["commercial_ok"] or not commercial_mode)
        and e["metrics"].get("split") == "test"
        and e["metrics"].get("primary") == metric
        and isinstance(e["metrics"].get(metric), (int, float))
        and math.isfinite(e["metrics"][metric])
    ]
    return max(candidates, key=lambda e: (e["metrics"][metric], e["id"])) if candidates else None


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
            if m.get("split") != "test" or m.get("primary") != primary:
                raise ValueError("selection requires test-split metrics")
            if not isinstance(m.get(primary), (int, float)) or not math.isfinite(m[primary]):
                raise ValueError("primary metric must be finite")
            if entry["commercial_ok"] and (
                name in {"valence", "arousal"}
                or (
                    name == "moodtheme"
                    and (entry["method"], entry["variant"]) != ("zeroshot", "zeroshot-unsupervised")
                )
                or "NC" in entry["data_license"].upper()
                or "NON-COMMERCIAL" in entry["data_license"].upper()
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
        entry = select_entry(spec, settings.commercial_mode)
        if entry is not None:
            result.append(load_tagger(settings.models_dir / entry["file"], entry["id"]))
    return result
