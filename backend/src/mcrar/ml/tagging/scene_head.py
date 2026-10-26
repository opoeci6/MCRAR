"""The scene entries side by side, and the optional trained head (M9).

The ``scene`` set has zero-shot entries (``zeroshot-catalog`` and ``zeroshot-catalog-centered``, see
:mod:`mcrar.ml.tagging.scenes`) and, once there are hand labels, a ``logreg-hybrid`` head:

- For a scene with at least 5 labelled positives and 5 negatives, its column is a balanced
  logistic regression on the CLAP vectors (:func:`~mcrar.ml.tagging.training.train_logreg`).
- Every other scene keeps the zero-shot column of the best-scoring zero-shot entry. A zero-shot
  score is linear in the (unit) CLAP vector before the sigmoid, ``slope * (x @ t - mean) / std``,
  so it is written as the weight ``slope * t / std`` and the bias ``-slope * mean / std`` of the
  head: the hybrid head reproduces those probabilities (:func:`linear_equivalent`).

Scoring is by cross-validation on the labelled tracks that have a CLAP embedding: precision@k
and average precision per scene, averaged over the scenes with at least 5 positives
(``mean_p_at_10`` is the registry's primary metric for hand labels). Zero-shot entries need no
fitting, so their scores are just their predictions. :func:`train_scene_head` records the metrics
of every scene entry in the registry, adds the head, and selects the best by ``mean_p_at_10``
(ties: the simpler entry, see :func:`mcrar.ml.tagging.registry.select_entry`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from mcrar.catalog import CatalogRepository
from mcrar.config import Settings
from mcrar.ml.bakeoff.metrics import average_precision, precision_at_k
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.tagging.registry import (
    HAND_LABELS_PRIMARY,
    HAND_LABELS_SPLIT,
    entry_id,
    read_registry,
    select_entry,
    write_registry,
)
from mcrar.ml.tagging.runtime import Tagger, load_tagger
from mcrar.ml.tagging.scene_labels import MergedLabels, merge_labels
from mcrar.recommend.vocab import SCENE

HEAD_VARIANT = "logreg-hybrid"
MIN_POSITIVES = 5  # a scene with fewer positives is not scored, and its head column is zero-shot
MIN_NEGATIVES = 5
TRAIN_K = 10
DATA_LICENSE = "hand labels by the owner and a collaborator on the catalog's tracks"


# -- the entries -------------------------------------------------------------------------------


def scene_registry(settings: Settings) -> dict:
    """The tagging registry; a clear ``ValueError`` when there is none yet."""
    if not (settings.models_dir / "registry.json").is_file():
        raise ValueError("there is no scene tagger yet; run: mcrar scenes build")
    return read_registry(settings)


def scene_spec(registry: dict) -> dict:
    spec = registry["label_sets"].get(SCENE)
    if spec is None:
        raise ValueError("there is no scene tagger yet; run: mcrar scenes build")
    return spec


def zeroshot_entries(settings: Settings) -> list[tuple[dict, Tagger]]:
    """The registry's zero-shot scene entries with their taggers, the lowest centering first."""
    spec = scene_spec(scene_registry(settings))
    found = [
        (entry, load_tagger(settings.models_dir / entry["file"], entry["id"]))
        for entry in spec["entries"]
        if entry["method"] == "zeroshot"
    ]
    if not found:
        raise ValueError("there is no zero-shot scene entry; run: mcrar scenes build")
    return sorted(
        found, key=lambda pair: (float(pair[0].get("centering", 0.0)), pair[0]["variant"])
    )


def probability_matrix(tagger: Tagger, x: np.ndarray) -> np.ndarray:
    """``[track, label]`` probabilities in the tagger's label order."""
    probs = tagger.predict(x)
    return np.column_stack([probs[label] for label in tagger.labels]).astype(np.float64)


def linear_equivalent(tagger: Tagger) -> tuple[np.ndarray, np.ndarray]:
    """The ``(weight, bias)`` of a head that gives a zero-shot tagger's probabilities: the logit
    ``scale * (slope * (x @ t - mean) / std) + offset`` is linear in ``x``."""
    a = tagger.arrays
    if tagger.method != "zeroshot" or tagger.kind != "multi_label" or "text_vectors" not in a:
        raise ValueError("only a multi-label zero-shot tagger has a linear equivalent")
    n = len(tagger.labels)
    weight = a["text_vectors"].T.astype(np.float64)  # (512, n)
    bias = np.zeros(n)
    if "reference_mean" in a:
        std = np.broadcast_to(a["reference_std"], (n,)).astype(np.float64)
        factor = np.broadcast_to(a["slope"], (n,)).astype(np.float64) / std
        weight = weight * factor
        bias = -np.broadcast_to(a["reference_mean"], (n,)).astype(np.float64) * factor
    if "scale" in a:
        scale = np.broadcast_to(a["scale"], (n,)).astype(np.float64)
        weight = weight * scale
        bias = bias * scale + np.broadcast_to(a["offset"], (n,)).astype(np.float64)
    return weight, bias


def fit_hybrid(
    x: np.ndarray, y: np.ndarray, fallback: Tagger, *, seed: int = 0
) -> tuple[Tagger, list[str]]:
    """The hybrid head fitted on ``x`` (unit CLAP vectors) and ``y`` (bool ``[track, scene]``).

    Returns the head and the scenes whose column was trained; the others copy ``fallback``.
    """
    from mcrar.ml.tagging.training import make_tagger, train_logreg

    labels = list(fallback.labels)
    positives = y.sum(axis=0)
    trained = [
        i
        for i in range(len(labels))
        if positives[i] >= MIN_POSITIVES and len(y) - positives[i] >= MIN_NEGATIVES
    ]
    weight, bias = linear_equivalent(fallback)
    if trained:
        fitted = train_logreg(
            SCENE,
            "multi_label",
            [labels[i] for i in trained],
            x,
            y[:, trained].astype(int),
            seed=seed,
        )
        weight[:, trained] = fitted.arrays["weight"]
        bias[trained] = fitted.arrays["bias"]
    head = make_tagger(SCENE, "multi_label", labels, {"weight": weight, "bias": bias})
    return head, [labels[i] for i in trained]


# -- the labelled data -------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelledData:
    """The merged hand labels of the tracks that have a CLAP embedding: ``x`` is
    ``[track, 512]``, ``truth`` bool ``[track, scene]`` (the same order as ``labels``)."""

    merged: MergedLabels
    x: np.ndarray

    @property
    def truth(self) -> np.ndarray:
        return self.merged.scenes

    @property
    def labels(self) -> list[str]:
        return self.merged.labels


def labelled_data(repo: CatalogRepository, scene_ids: list[str]) -> LabelledData:
    """Merge every label in the catalog (see :func:`merge_labels`) and keep the tracks with a
    CLAP embedding. Labels survive a rebuilt pool, so all labelled tracks count."""
    merged = merge_labels(repo.iter_scene_labels(), scene_ids)
    ids, matrix = repo.load_embeddings(EMBEDDER)
    row = {int(t): i for i, t in enumerate(ids)}
    keep = [i for i, t in enumerate(merged.track_ids) if int(t) in row]
    kept = MergedLabels(
        merged.track_ids[keep],
        merged.labels,
        merged.scenes[keep],
        merged.intensity[keep],
        merged.labellers[keep],
    )
    x = matrix[[row[int(t)] for t in kept.track_ids]] if keep else np.empty((0, 512), np.float32)
    return LabelledData(kept, x.astype(np.float32))


# -- scoring -----------------------------------------------------------------------------------


def entry_metrics(
    scores: np.ndarray, truth: np.ndarray, labels: list[str], k: int
) -> dict[str, object]:
    """Per-scene precision@k and AP of ``scores`` against ``truth``, and their mean over the
    scenes with at least :data:`MIN_POSITIVES` positives (``None`` for the others: too few)."""
    per_scene: dict[str, dict] = {}
    for i, label in enumerate(labels):
        positives = int(truth[:, i].sum())
        enough = positives >= MIN_POSITIVES
        per_scene[label] = {
            "positives": positives,
            "p_at_k": precision_at_k(scores[:, i], truth[:, i], k) if enough else None,
            "ap": average_precision(scores[:, i], truth[:, i]) if enough else None,
        }
    values = [s["p_at_k"] for s in per_scene.values() if s["p_at_k"] is not None]
    return {
        "per_scene": per_scene,
        "mean_p_at_k": float(np.mean(values)) if values else None,
        "scenes_scored": len(values),
    }


def cross_validated_head_scores(
    x: np.ndarray, y: np.ndarray, fallback: Tagger, *, folds: int = 5, seed: int = 0
) -> np.ndarray:
    """Out-of-fold probabilities of the hybrid head: each track is scored by a head that did not
    see it (K-fold with this seed)."""
    from sklearn.model_selection import KFold

    if len(x) < 2:
        raise ValueError("need at least 2 labelled tracks to cross-validate")
    out = np.zeros((len(x), len(fallback.labels)))
    splits = KFold(n_splits=max(2, min(folds, len(x))), shuffle=True, random_state=seed)
    for train, test in splits.split(x):
        head, _ = fit_hybrid(x[train], y[train], fallback, seed=seed)
        out[test] = probability_matrix(head, x[test])
    return out


def best_zeroshot(
    scored: dict[str, dict], entries: list[tuple[dict, Tagger]]
) -> tuple[dict, Tagger]:
    """The zero-shot entry with the highest mean P@k (``scored``: variant -> :func:`entry_metrics`);
    ties and unscored entries go to the lower centering."""

    def key(pair: tuple[dict, Tagger]) -> tuple[float, float]:
        mean = scored[pair[0]["variant"]]["mean_p_at_k"]
        return (-1.0 if mean is None else mean, -float(pair[0].get("centering", 0.0)))

    return max(entries, key=key)


# -- training ----------------------------------------------------------------------------------


def _registry_metrics(scored: dict, *, n_tracks: int, folds: int, seed: int) -> dict:
    return {
        "split": HAND_LABELS_SPLIT,
        "primary": HAND_LABELS_PRIMARY,
        HAND_LABELS_PRIMARY: scored["mean_p_at_k"],
        "per_scene": {
            label: {"positives": s["positives"], "p_at_10": s["p_at_k"], "ap": s["ap"]}
            for label, s in scored["per_scene"].items()
        },
        "n_tracks": n_tracks,
        "folds": folds,
        "seed": seed,
    }


def train_scene_head(
    settings: Settings, repo: CatalogRepository, *, folds: int = 5, seed: int = 0
) -> dict:
    """Fit the hybrid head on the hand labels, score every scene entry by cross-validation,
    record the metrics in the registry, and select the best entry.

    Returns ``{"head": entry, "scores": {variant: mean P@10}, "selected": id, "previous": id,
    "head_won": bool, "fallback": variant, "trained": [scenes], "n_tracks": n}``. The zero-shot
    entries' files are unchanged, so their ids stay.
    """
    registry = scene_registry(settings)
    spec = scene_spec(registry)
    zeroshots = zeroshot_entries(settings)
    labels = list(spec["labels"])
    data = labelled_data(repo, labels)
    if len(data.merged) == 0:
        raise ValueError("there are no hand labels (of tracks with a CLAP embedding) yet")

    zero_scored = {
        entry["variant"]: entry_metrics(
            probability_matrix(tagger, data.x), data.truth, labels, TRAIN_K
        )
        for entry, tagger in zeroshots
    }
    fallback_entry, fallback = best_zeroshot(zero_scored, zeroshots)
    oof = cross_validated_head_scores(data.x, data.truth, fallback, folds=folds, seed=seed)
    head_scored = entry_metrics(oof, data.truth, labels, TRAIN_K)
    if head_scored["mean_p_at_k"] is None:
        raise ValueError(
            f"no scene has {MIN_POSITIVES} labelled positives yet ({len(data.merged)} labelled "
            "tracks); label more tracks first"
        )
    head, trained = fit_hybrid(data.x, data.truth, fallback, seed=seed)

    heads = settings.models_dir / "heads"
    heads.mkdir(parents=True, exist_ok=True)
    temporary = heads / f".{SCENE}-{HEAD_VARIANT}.npz"
    head.save(temporary)
    identity = entry_id(SCENE, HEAD_VARIANT, temporary)
    temporary.replace(heads / f"{identity}.npz")
    n = len(data.merged)
    labellers = sorted(
        {lab.labeller for lab in repo.iter_scene_labels() if lab.status == "labelled"}
    )
    head_entry = {
        "id": identity,
        "method": "head",
        "variant": HEAD_VARIANT,
        "file": f"heads/{identity}.npz",
        "seed": seed,
        "metrics": _registry_metrics(head_scored, n_tracks=n, folds=folds, seed=seed),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "commercial_ok": True,
        "data_license": DATA_LICENSE,
        "train_data": f"{n} hand-labelled catalog tracks (labellers: {', '.join(labellers)})",
        "trained_labels": trained,
        "zeroshot_labels": [s for s in labels if s not in trained],
        "fallback_entry": fallback_entry["id"],
        "embedding": {"model": EMBEDDER},
    }
    previous = select_entry(spec)
    for entry in spec["entries"]:  # the registry's own dicts (zeroshots holds another copy)
        if entry["method"] == "zeroshot" and entry["variant"] in zero_scored:
            entry["metrics"] = _registry_metrics(
                zero_scored[entry["variant"]], n_tracks=n, folds=folds, seed=seed
            )
    spec["entries"] = [e for e in spec["entries"] if e["variant"] != HEAD_VARIANT] + [head_entry]
    chosen = select_entry(spec)
    assert chosen is not None
    registry.setdefault("selected", {})[SCENE] = chosen["id"]
    write_registry(settings, registry)
    return {
        "head": head_entry,
        "scores": {
            **{v: s["mean_p_at_k"] for v, s in zero_scored.items()},
            HEAD_VARIANT: head_scored["mean_p_at_k"],
        },
        "selected": chosen["id"],
        "previous": previous["id"] if previous else None,
        "head_won": chosen["id"] == identity,
        "fallback": fallback_entry["variant"],
        "trained": trained,
        "n_tracks": n,
    }
