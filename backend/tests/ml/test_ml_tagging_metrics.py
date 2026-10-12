"""Metrics handle tied scores correctly and bootstrap nonlinear test metrics over items."""

from __future__ import annotations

import numpy as np
import pytest

from mcrar.ml.tagging.metrics import evaluate, scores


def test_multilabel_ties_match_sklearn() -> None:
    from sklearn.metrics import average_precision_score, roc_auc_score

    y = np.array([[1, 0], [0, 1], [1, 0], [0, 1]])
    p = np.array([[0.5, 0.2], [0.5, 0.8], [0.8, 0.2], [0.1, 0.8]])
    m = scores(y, p, "multi_label")
    assert m["macro_pr_auc"] == pytest.approx(average_precision_score(y, p, average="macro"))
    assert m["macro_roc_auc"] == pytest.approx(roc_auc_score(y, p, average="macro"))


def test_primary_bootstrap_is_reproducible_and_regression_subset_is_test_only() -> None:
    y = np.arange(20) % 2
    p = np.eye(2)[y] * 0.8 + 0.1
    a = evaluate(y, p, "single_label", n_resamples=30)
    assert a == evaluate(y, p, "single_label", n_resamples=30)
    assert a["macro_f1"] == 1 and a["primary_ci95"] == [1, 1]
    regression = evaluate(
        y[:, None], y[:, None] * 0.8 + 0.1, "regression", ids=np.arange(1990, 2010), n_resamples=30
    )
    assert regression["subset_2015_test"]["n"] == 9
