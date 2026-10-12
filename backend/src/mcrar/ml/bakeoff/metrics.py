"""Retrieval and ranking metrics plus bootstrap confidence intervals. Pure numpy.

Ranks are 1-based. Ties are counted against the item being ranked (pessimistic), so a model
that returns identical scores for everything cannot look good.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

RECALL_KS = (1, 5, 10)


# -- ranks -------------------------------------------------------------------------------------


def target_ranks(scores: np.ndarray, targets: Sequence[int] | np.ndarray) -> np.ndarray:
    """Rank of column ``targets[i]`` among the columns of row ``i`` of ``scores`` (higher wins)."""
    s = np.asarray(scores)
    t = np.asarray(targets, dtype=np.int64)
    if s.ndim != 2 or t.shape != (s.shape[0],):
        raise ValueError(f"scores {s.shape} and targets {t.shape} do not match")
    own = s[np.arange(s.shape[0]), t][:, None]
    return (s > own).sum(axis=1) + (s == own).sum(axis=1)  # ties count; own score is in the tie


def first_hit_ranks(scores: np.ndarray, relevant: np.ndarray) -> np.ndarray:
    """Per row, the rank of the best-scored relevant column (non-relevant columns tied with it
    rank above it). Every row needs at least one relevant column."""
    s = np.asarray(scores)
    rel = np.asarray(relevant, dtype=bool)
    if s.shape != rel.shape or s.ndim != 2:
        raise ValueError(f"scores {s.shape} and relevant {rel.shape} do not match")
    if not rel.any(axis=1).all():
        raise ValueError("every row needs at least one relevant column")
    best = np.where(rel, s, -np.inf).max(axis=1, keepdims=True)
    return 1 + ((s >= best) & ~rel).sum(axis=1)


def recall_at_k(ranks: np.ndarray, k: int) -> float:
    r = np.asarray(ranks)
    if r.size == 0:
        raise ValueError("no ranks")
    return float((r <= k).mean())


def median_rank(ranks: np.ndarray) -> float:
    r = np.asarray(ranks)
    if r.size == 0:
        raise ValueError("no ranks")
    return float(np.median(r))


def reciprocal_ranks(ranks: np.ndarray) -> np.ndarray:
    return 1.0 / np.asarray(ranks, dtype=np.float64)


def mean_reciprocal_rank(ranks: np.ndarray) -> float:
    r = np.asarray(ranks)
    if r.size == 0:
        raise ValueError("no ranks")
    return float(reciprocal_ranks(r).mean())


# -- ranked-list metrics -------------------------------------------------------------------------


def _order(scores: np.ndarray) -> np.ndarray:
    """Indices by descending score; equal scores keep their original order."""
    s = np.asarray(scores, dtype=np.float64)
    return np.lexsort((np.arange(s.size), -s))


def average_precision(scores: np.ndarray, relevant: np.ndarray) -> float:
    """AP of one query: the mean of precision@i over the positions i holding a relevant item.
    0.0 when nothing is relevant."""
    rel = np.asarray(relevant, dtype=bool)
    if rel.shape != np.shape(scores) or rel.ndim != 1:
        raise ValueError("scores and relevant must be 1-D and the same length")
    n_rel = int(rel.sum())
    if n_rel == 0:
        return 0.0
    hits = rel[_order(scores)]
    precision = np.cumsum(hits) / np.arange(1, hits.size + 1)
    return float(precision[hits].sum() / n_rel)


def precision_at_k(scores: np.ndarray, relevant: np.ndarray, k: int) -> float:
    rel = np.asarray(relevant, dtype=bool)
    if rel.shape != np.shape(scores) or rel.ndim != 1:
        raise ValueError("scores and relevant must be 1-D and the same length")
    if k <= 0:
        raise ValueError("k must be positive")
    top = rel[_order(scores)][:k]
    return float(top.sum() / max(top.size, 1))


def dcg(gains: Sequence[float] | np.ndarray, k: int) -> float:
    g = np.asarray(gains, dtype=np.float64)[:k]
    return float((g / np.log2(np.arange(2, g.size + 2))).sum())


def ndcg_at_k(
    ranked_gains: Sequence[float] | np.ndarray,
    pool_gains: Sequence[float] | np.ndarray,
    k: int,
) -> float:
    """nDCG@k with the gain equal to the rating (linear).

    ``ranked_gains`` are a model's gains in rank order; ``pool_gains`` are the gains of every
    rated item the ideal ranking may draw from. When the ideal DCG is 0 (nothing in the pool
    earned a positive gain) the result is 0.0, the same for every model.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    ideal = dcg(np.sort(np.asarray(pool_gains, dtype=np.float64))[::-1], k)
    if ideal <= 0.0:
        return 0.0
    return dcg(ranked_gains, k) / ideal


# -- bootstrap -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MeanCI:
    mean: float
    lo: float
    hi: float


@dataclass(frozen=True)
class DiffCI:
    """Mean paired difference (a - b) and its bootstrap interval."""

    diff: float
    lo: float
    hi: float

    @property
    def excludes_zero(self) -> bool:
        return self.lo > 0.0 or self.hi < 0.0


def _indices(n: int, n_resamples: int, seed: int) -> np.ndarray:
    if n <= 0:
        raise ValueError("cannot bootstrap an empty sample")
    if n_resamples <= 0:
        raise ValueError("n_resamples must be positive")
    return np.random.default_rng(seed).integers(0, n, size=(n_resamples, n))


def _interval(samples: np.ndarray, confidence: float) -> tuple[float, float]:
    tail = (1.0 - confidence) / 2.0 * 100.0
    lo, hi = np.percentile(samples, [tail, 100.0 - tail])
    return float(lo), float(hi)


def bootstrap_mean_ci(
    values: Sequence[float] | np.ndarray,
    *,
    n_resamples: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
) -> MeanCI:
    """Percentile bootstrap interval of the mean (resampling the items with replacement)."""
    v = np.asarray(values, dtype=np.float64)
    idx = _indices(v.size, n_resamples, seed)
    lo, hi = _interval(v[idx].mean(axis=1), confidence)
    return MeanCI(float(v.mean()), lo, hi)


def paired_bootstrap_diff(
    a: Sequence[float] | np.ndarray,
    b: Sequence[float] | np.ndarray,
    *,
    n_resamples: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
) -> DiffCI:
    """Interval of ``mean(a) - mean(b)``; ``a[i]`` and ``b[i]`` must describe the same item, and
    both samples are resampled with the same indices."""
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    if va.shape != vb.shape or va.ndim != 1:
        raise ValueError(f"paired samples must be 1-D and equally long, got {va.shape}, {vb.shape}")
    idx = _indices(va.size, n_resamples, seed)
    lo, hi = _interval((va - vb)[idx].mean(axis=1), confidence)
    return DiffCI(float((va - vb).mean()), lo, hi)
