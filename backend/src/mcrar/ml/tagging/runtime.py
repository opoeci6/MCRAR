"""Portable taggers: all stored parameters and inference use numpy, never model frameworks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mcrar.catalog import CatalogRepository
from mcrar.ml.datasets.embedding import EMBEDDER, atomic_npz


def sigmoid(x: np.ndarray) -> np.ndarray:
    return (1 / (1 + np.exp(-np.clip(x, -80, 80)))).astype(np.float32)


def softmax(x: np.ndarray) -> np.ndarray:
    exp = np.exp(x - x.max(axis=1, keepdims=True))
    return (exp / exp.sum(axis=1, keepdims=True)).astype(np.float32)


@dataclass(frozen=True)
class Tagger:
    label_set: str
    kind: str
    labels: list[str]
    entry_id: str
    method: str
    arrays: dict[str, np.ndarray]

    def scores(self, matrix: np.ndarray) -> np.ndarray:
        x = np.asarray(matrix, dtype=np.float32)
        if x.ndim != 2 or x.shape[1] != 512 or not np.isfinite(x).all():
            raise ValueError("taggers require a finite (n, 512) CLAP embedding matrix")
        if len(x) and not np.allclose(np.linalg.norm(x, axis=1), 1, atol=1e-3):
            raise ValueError("CLAP embeddings must be L2-normalised")
        a = self.arrays
        if self.method == "zeroshot":
            return x @ a["text_vectors"].T
        if "hidden_weight" in a:
            x = np.maximum(x @ a["hidden_weight"] + a["hidden_bias"], 0)
        return x @ a["weight"] + a["bias"]

    def predict(self, matrix: np.ndarray) -> dict[str, np.ndarray]:
        scores = self.scores(matrix)
        a = self.arrays
        if "reference_mean" in a:
            scores = (scores - a["reference_mean"]) / a["reference_std"]
            scores *= a["slope"]
        if "scale" in a:
            scores = scores * a["scale"] + a["offset"]
        if self.kind == "single_label":
            probs = softmax(scores)
        elif self.kind == "multi_label":
            probs = sigmoid(scores)
        elif "reference_mean" in a:
            probs = sigmoid(scores)
        else:
            probs = np.clip(scores, 0, 1).astype(np.float32)
        return {label: probs[:, i] for i, label in enumerate(self.labels)}

    def save(self, path: Path) -> None:
        metadata = {
            "schema": 1,
            "embedder": EMBEDDER,
            "label_set": self.label_set,
            "kind": self.kind,
            "labels": self.labels,
            "method": self.method,
        }
        atomic_npz(path, metadata=np.array(json.dumps(metadata)), **self.arrays)


def load_tagger(path: Path, entry_id: str = "") -> Tagger:
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["metadata"]))
        arrays = {k: data[k].copy() for k in data.files if k != "metadata"}
    if meta.get("schema") != 1 or meta.get("embedder") != EMBEDDER:
        raise ValueError(f"unsupported tagger metadata in {path.name}")
    if meta.get("kind") not in {"single_label", "multi_label", "regression"}:
        raise ValueError("invalid tagger kind")
    n = len(meta["labels"])
    if not n or len(set(meta["labels"])) != n:
        raise ValueError("invalid tagger labels")
    if meta["method"] == "zeroshot":
        required = {"text_vectors": (n, 512)}
    elif meta["method"] == "head":
        dim = 512
        required = {"bias": (n,)}
        if "hidden_weight" in arrays:
            if arrays["hidden_weight"].ndim != 2:
                raise ValueError("invalid hidden weights")
            dim = arrays["hidden_weight"].shape[1]
            required.update(hidden_weight=(512, dim), hidden_bias=(dim,))
        required["weight"] = (dim, n)
    else:
        raise ValueError("invalid tagger method")
    for key, shape in required.items():
        if key not in arrays or arrays[key].shape != shape:
            raise ValueError(f"invalid {key} shape in {path.name}; expected {shape}")
    for key, arr in arrays.items():
        if key.startswith("prompt_"):
            continue
        if not np.issubdtype(arr.dtype, np.number) or not np.isfinite(arr).all():
            raise ValueError(f"invalid parameter {key}")
    if "reference_std" in arrays and (arrays["reference_std"] <= 0).any():
        raise ValueError("reference standard deviations must be positive")
    if meta["kind"] == "regression" and meta["labels"] != ["value"]:
        raise ValueError("regression requires one label: value")
    for key in ("scale", "offset", "reference_mean", "reference_std", "slope"):
        if key in arrays and arrays[key].shape not in {(), (n,), (1,)}:
            raise ValueError(f"invalid {key} shape")
    return Tagger(meta["label_set"], meta["kind"], meta["labels"], entry_id, meta["method"], arrays)


class TaggingStage:
    needs_audio = False

    def __init__(self, tagger: Tagger) -> None:
        self.tagger = tagger
        self.name = f"tag:{tagger.label_set}"
        self.version = tagger.entry_id

    def is_current(self, repo: CatalogRepository, track_id: int) -> bool:
        rows = repo.get_tag_probs(track_id, head=self.tagger.label_set)
        return {r.label for r in rows} == set(self.tagger.labels) and all(
            r.model_version == self.version and r.method == self.tagger.method for r in rows
        )

    def run(self, repo: CatalogRepository, track_id: int, audio: object = None) -> None:
        vector = repo.get_embedding(track_id, EMBEDDER)
        if vector is None:
            raise ValueError(f"track {track_id} has no {EMBEDDER} embedding; run mcrar embed first")
        probs = self.tagger.predict(vector[None, :])
        repo.set_tag_probs(
            track_id,
            head=self.tagger.label_set,
            method=self.tagger.method,
            model_version=self.version,
            probs={k: float(v[0]) for k, v in probs.items()},
        )
