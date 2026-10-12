"""Prompt ensembling and label-free reference normalisation for portable zero-shot taggers."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import numpy as np

from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.embedders import Embedder
from mcrar.ml.tagging.runtime import Tagger
from mcrar.ml.tagging.training import calibrate

PROMPTS = Path(__file__).parent / "prompts"


def prompt_vectors(embedder: Embedder, path: Path, labels: list[str]) -> dict[str, np.ndarray]:
    if embedder.model_id != EMBEDDER or embedder.dim != 512:
        raise ValueError(f"zero-shot prompts require {EMBEDDER}")
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    texts, owners = [], []
    for i, label in enumerate(labels):
        for synonym in config["labels"][label]:
            for template in config["templates"]:
                texts.append(template.format(label=synonym))
                owners.append(i)
    if not texts or set(owners) != set(range(len(labels))):
        raise ValueError("every label needs prompt templates and synonyms")
    vectors = embedder.embed_text(texts)
    # Do NOT normalise the mean: x @ mean(v) is the requested mean cosine, including the
    # relative disagreement among synonyms/templates.
    means = np.stack([vectors[np.array(owners) == i].mean(axis=0) for i in range(len(labels))])
    return {
        "text_vectors": means.astype(np.float32),
        "prompt_vectors": vectors.astype(np.float32),
        "prompt_texts": np.array(texts),
        "prompt_owners": np.array(owners, dtype=np.int64),
        "prompt_sha256": np.array(hashlib.sha256(path.read_bytes()).hexdigest()),
    }


def unsupervised(
    label_set: str,
    kind: str,
    labels: list[str],
    vectors: dict,
    reference: np.ndarray,
    *,
    slope: float = 1,
) -> Tagger:
    """No targets argument: use only unlabelled FMA training embeddings."""
    if len(reference) < 2 or slope <= 0:
        raise ValueError("reference embeddings and a positive fixed slope are required")
    scores = reference @ vectors["text_vectors"].T
    arrays = {
        **vectors,
        "reference_mean": scores.mean(axis=0).astype(np.float32),
        "reference_std": np.maximum(scores.std(axis=0), 1e-6).astype(np.float32),
        "slope": np.array(slope, dtype=np.float32),
    }
    return Tagger(label_set, kind, labels, "", "zeroshot", arrays)


def calibrated(
    label_set: str,
    kind: str,
    labels: list[str],
    vectors: dict,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
) -> Tagger:
    tagger = Tagger(label_set, kind, labels, "", "zeroshot", vectors)
    return calibrate(tagger, validation_x, validation_y)
