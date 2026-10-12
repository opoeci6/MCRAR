"""Test-split metrics and item bootstrap CIs; recompute nonlinear metrics in each sample."""

from __future__ import annotations

import numpy as np

from mcrar.ml.bakeoff.metrics import _indices, _interval, bootstrap_mean_ci


def ece(y: np.ndarray, probs: np.ndarray, kind: str, bins: int = 15) -> float:
    if kind == "regression":
        return float(np.abs(y - probs).mean())
    if kind == "single_label":
        confidence = probs.max(axis=1)
        correct = (probs.argmax(axis=1) == y).astype(float)
    else:
        confidence, correct = probs.ravel(), y.ravel()
    result = 0.0
    for i in range(bins):
        selected = (confidence >= i / bins) & (
            (confidence < (i + 1) / bins) if i + 1 < bins else confidence <= 1
        )
        if selected.any():
            result += selected.mean() * abs(correct[selected].mean() - confidence[selected].mean())
    return float(result)


def _auc(y: np.ndarray, scores: np.ndarray, *, pr: bool) -> float:
    # Group score ties before integrating so identical probabilities cannot gain from row order.
    order = np.argsort(-scores, kind="stable")
    target, ranked = y[order], scores[order]
    ends = np.r_[np.flatnonzero(np.diff(ranked)), len(ranked) - 1]
    tp = np.cumsum(target)[ends]
    fp = ends + 1 - tp
    positive, negative = y.sum(), len(y) - y.sum()
    if not positive:
        return 0.0 if pr else float("nan")
    if not pr and not negative:
        return float("nan")
    if pr:
        recall = np.r_[0, tp / positive]
        return float(np.sum(np.diff(recall) * tp / (tp + fp)))
    return float(np.trapezoid(np.r_[0, tp / positive], np.r_[0, fp / negative]))


def scores(y: np.ndarray, probs: np.ndarray, kind: str) -> dict:
    if len(y) == 0 or not np.isfinite(probs).all():
        raise ValueError("metrics require non-empty finite predictions")
    if kind == "single_label":
        pred = probs.argmax(axis=1)
        f1 = []
        for i in range(probs.shape[1]):
            tp = ((pred == i) & (y == i)).sum()
            denominator = (pred == i).sum() + (y == i).sum()
            f1.append(2 * tp / denominator if denominator else 0)
        top = np.argsort(-probs, axis=1, kind="stable")[:, : min(3, probs.shape[1])]
        return {
            "primary": "macro_f1",
            "macro_f1": float(np.mean(f1)),
            "accuracy": float((pred == y).mean()),
            "top3_accuracy": float((top == y[:, None]).any(axis=1).mean()),
        }
    if kind == "multi_label":
        pr = [_auc(y[:, i], probs[:, i], pr=True) for i in range(probs.shape[1])]
        roc = [_auc(y[:, i], probs[:, i], pr=False) for i in range(probs.shape[1])]
        return {
            "primary": "macro_pr_auc",
            "macro_pr_auc": float(np.nanmean(pr)),
            "macro_roc_auc": float(np.nanmean(roc)),
            "pr_auc_labels": int(np.isfinite(pr).sum()),
            "roc_auc_labels": int(np.isfinite(roc).sum()),
        }
    target, p = y.ravel(), probs.ravel()
    variance = np.sum((target - target.mean()) ** 2)
    r2 = 1 - np.sum((target - p) ** 2) / variance if variance > 0 else float("nan")
    r = float(np.corrcoef(target, p)[0, 1]) if np.std(target) > 0 and np.std(p) > 0 else None
    return {
        "primary": "r2",
        "r2": float(r2),
        "pearson_r": r,
        "mae": float(np.abs(target - p).mean()),
    }


def evaluate(
    y: np.ndarray,
    probs: np.ndarray,
    kind: str,
    *,
    ids: np.ndarray | None = None,
    n_resamples: int = 1000,
    seed: int = 0,
) -> dict:
    result = {"split": "test", "n": len(y), **scores(y, probs, kind)}
    primary = result["primary"]
    if not np.isfinite(result[primary]):
        raise ValueError("primary metric is undefined on this split")
    values = np.array(
        [scores(y[idx], probs[idx], kind)[primary] for idx in _indices(len(y), n_resamples, seed)]
    )
    values = values[np.isfinite(values)]
    if not len(values):
        raise ValueError("no valid bootstrap resamples")
    result["primary_ci95"] = list(_interval(values, 0.95))
    result.update(
        bootstrap_seed=seed, bootstrap_resamples=n_resamples, bootstrap_valid_resamples=len(values)
    )
    if kind != "regression":
        result["ece"] = ece(y, probs, kind)
    if kind == "single_label":
        ci = bootstrap_mean_ci(
            (probs.argmax(axis=1) == y).astype(float), n_resamples=n_resamples, seed=seed
        )
        result["accuracy_ci95"] = [ci.lo, ci.hi]
    if kind == "regression" and ids is not None:
        mask = (ids >= 2001) & (ids <= 2058)
        result["subset_2015_test"] = (
            {"n": int(mask.sum()), **scores(y[mask], probs[mask], kind)} if mask.any() else {"n": 0}
        )
        subset = result["subset_2015_test"]
        if isinstance(subset.get("r2"), float) and not np.isfinite(subset["r2"]):
            subset["r2"] = None
    return result
