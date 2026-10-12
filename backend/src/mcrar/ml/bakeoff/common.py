"""Paths, timestamps and JSON helpers shared by the bake-off commands."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from mcrar.config import Settings
    from mcrar.ml.embedders.base import Embedder

TEXT_BATCH = 64


class BakeoffError(RuntimeError):
    """A bake-off problem whose message is fit to show to the user."""


def benchmarks_dir(settings: Settings) -> Path:
    return settings.data_dir / "benchmarks"


def sdd_dir(settings: Settings) -> Path:
    return benchmarks_dir(settings) / "sdd"


def results_dir(settings: Settings) -> Path:
    return benchmarks_dir(settings) / "results"


def timestamp() -> str:
    """A sortable UTC stamp for file names, e.g. ``20261011T093000Z``."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def created_at() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BakeoffError(f"file not found: {path}") from None
    except (OSError, ValueError) as exc:
        raise BakeoffError(f"cannot read {path} ({type(exc).__name__})") from None


def latest_result(directory: Path, prefix: str) -> Path | None:
    """The newest ``<prefix>_<timestamp>.json`` in ``directory`` (never a ``.private.json``)."""
    if not directory.is_dir():
        return None
    found = sorted(
        p for p in directory.glob(f"{prefix}_*.json") if not p.name.endswith(".private.json")
    )
    return found[-1] if found else None


def model_pairs(model_ids: list[str]) -> list[tuple[str, str]]:
    """Every unordered pair of models, in the order given."""
    return list(combinations(model_ids, 2))


def models_info(model_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Registry facts (key, licence, commercial flag) for model ids; unknown ids are skipped."""
    from mcrar.ml.registry import MODELS

    by_id = {spec.model_id: spec for spec in MODELS.values()}
    return {
        m: {
            "key": by_id[m].key,
            "license": by_id[m].license,
            "commercial_ok": by_id[m].commercial_ok,
        }
        for m in model_ids
        if m in by_id
    }


def intersect_ids(id_arrays: Sequence[np.ndarray]) -> np.ndarray:
    """Sorted ids present in every array (empty if there are no arrays)."""
    common: set[int] | None = None
    for ids in id_arrays:
        current = {int(i) for i in ids}
        common = current if common is None else common & current
    return np.asarray(sorted(common or ()), dtype=np.int64)


def align(track_ids: np.ndarray, matrix: np.ndarray, wanted: np.ndarray) -> np.ndarray:
    """The rows of ``matrix`` for the ``wanted`` ids, in that order."""
    row = {int(t): i for i, t in enumerate(track_ids)}
    return matrix[[row[int(t)] for t in wanted]]


def embed_texts(embedder: Embedder, texts: Sequence[str], batch: int = TEXT_BATCH) -> np.ndarray:
    """Text embeddings in batches, as one ``(n, dim)`` array."""
    parts = [embedder.embed_text(list(texts[i : i + batch])) for i in range(0, len(texts), batch)]
    if not parts:
        return np.empty((0, embedder.dim), dtype=np.float32)
    return np.concatenate(parts).astype(np.float32)


def unit_rows(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation (zero rows stay zero)."""
    m = np.asarray(matrix, dtype=np.float32)
    return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12)
