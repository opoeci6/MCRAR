"""Bake-off metrics on handmade rank and score arrays (pure numpy)."""

from __future__ import annotations

import numpy as np
import pytest

from mcrar.ml.bakeoff import metrics

# -- ranks ---------------------------------------------------------------------------------------


def test_target_ranks() -> None:
    scores = np.array([[0.9, 0.1, 0.5], [0.2, 0.8, 0.3]])
    assert metrics.target_ranks(scores, [0, 2]).tolist() == [1, 2]
    assert metrics.target_ranks(scores, [1, 0]).tolist() == [3, 3]


def test_target_ranks_count_ties_against_the_target() -> None:
    scores = np.array([[1.0, 1.0, 0.0]])
    assert metrics.target_ranks(scores, [0]).tolist() == [2]
    assert metrics.target_ranks(np.zeros((1, 5)), [3]).tolist() == [5]  # all equal: worst rank


def test_target_ranks_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError):
        metrics.target_ranks(np.zeros((2, 3)), [0])


def test_first_hit_ranks_takes_the_best_relevant_item() -> None:
    scores = np.array([[0.9, 0.8, 0.7, 0.6]])
    relevant = np.array([[False, False, True, True]])
    assert metrics.first_hit_ranks(scores, relevant).tolist() == [3]
    both = np.array([[True, False, False, True]])
    assert metrics.first_hit_ranks(scores, both).tolist() == [1]


def test_first_hit_ranks_ties_rank_the_other_items_first() -> None:
    scores = np.array([[0.5, 0.5, 0.5]])
    relevant = np.array([[True, False, False]])
    assert metrics.first_hit_ranks(scores, relevant).tolist() == [3]


def test_first_hit_ranks_needs_a_relevant_item_per_row() -> None:
    with pytest.raises(ValueError):
        metrics.first_hit_ranks(np.zeros((1, 3)), np.zeros((1, 3), dtype=bool))


def test_recall_median_and_mrr() -> None:
    ranks = np.array([1, 2, 5, 20])
    assert metrics.recall_at_k(ranks, 1) == 0.25
    assert metrics.recall_at_k(ranks, 5) == 0.75
    assert metrics.recall_at_k(ranks, 10) == 0.75
    assert metrics.recall_at_k(ranks, 20) == 1.0
    assert metrics.median_rank(ranks) == 3.5
    assert metrics.mean_reciprocal_rank(ranks) == pytest.approx((1 + 0.5 + 0.2 + 0.05) / 4)


def test_rank_metrics_reject_empty_input() -> None:
    for fn in (metrics.median_rank, metrics.mean_reciprocal_rank):
        with pytest.raises(ValueError):
            fn(np.array([]))
    with pytest.raises(ValueError):
        metrics.recall_at_k(np.array([]), 10)


# -- ranked lists ---------------------------------------------------------------------------------


def test_average_precision() -> None:
    scores = np.array([0.9, 0.8, 0.7, 0.6])
    assert metrics.average_precision(scores, np.array([True, False, True, False])) == pytest.approx(
        (1 / 1 + 2 / 3) / 2
    )
    assert metrics.average_precision(scores, np.array([True, True, False, False])) == 1.0
    assert metrics.average_precision(scores, np.array([False, False, False, True])) == 0.25
    assert metrics.average_precision(scores, np.zeros(4, dtype=bool)) == 0.0


def test_average_precision_ignores_input_order() -> None:
    scores = np.array([0.6, 0.7, 0.8, 0.9])
    relevant = np.array([False, True, False, True])
    assert metrics.average_precision(scores, relevant) == pytest.approx((1 + 2 / 3) / 2)


def test_precision_at_k() -> None:
    scores = np.array([0.9, 0.8, 0.7, 0.6])
    relevant = np.array([True, False, True, False])
    assert metrics.precision_at_k(scores, relevant, 2) == 0.5
    assert metrics.precision_at_k(scores, relevant, 3) == pytest.approx(2 / 3)
    assert metrics.precision_at_k(scores, relevant, 10) == 0.5  # fewer items than k: over 4
    with pytest.raises(ValueError):
        metrics.precision_at_k(scores, relevant, 0)


def test_ndcg_matches_a_hand_computation() -> None:
    ranked = [2, 0, 1]
    pool = [2, 1, 0, 0]
    dcg = 2 / np.log2(2) + 0 + 1 / np.log2(4)
    ideal = 2 / np.log2(2) + 1 / np.log2(3)
    assert metrics.ndcg_at_k(ranked, pool, 3) == pytest.approx(dcg / ideal)


def test_ndcg_of_the_ideal_ranking_is_one() -> None:
    assert metrics.ndcg_at_k([2, 2, 1], [1, 2, 0, 2, 0], 3) == pytest.approx(1.0)


def test_ndcg_with_a_zero_ideal_is_zero_not_nan() -> None:
    assert metrics.ndcg_at_k([0, 0, 0], [0, 0, 0, 0], 3) == 0.0
    assert metrics.ndcg_at_k([], [], 3) == 0.0


def test_ndcg_truncates_at_k_and_accepts_short_lists() -> None:
    assert metrics.ndcg_at_k([2, 2, 2, 2], [2, 2, 2, 2], 2) == pytest.approx(1.0)
    short = metrics.ndcg_at_k([2], [2, 2, 2], 3)  # one item rated, the pool has more
    assert 0.0 < short < 1.0
    with pytest.raises(ValueError):
        metrics.ndcg_at_k([1], [1], 0)


# -- bootstrap ------------------------------------------------------------------------------------


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    values = np.random.default_rng(1).random(200)
    first = metrics.bootstrap_mean_ci(values, seed=7)
    again = metrics.bootstrap_mean_ci(values, seed=7)
    other = metrics.bootstrap_mean_ci(values, seed=8)
    assert first == again
    assert (first.lo, first.hi) != (other.lo, other.hi)
    assert first.mean == pytest.approx(values.mean())
    assert first.lo < first.mean < first.hi


def test_bootstrap_of_a_constant_is_a_point() -> None:
    ci = metrics.bootstrap_mean_ci(np.full(30, 0.4))
    assert (
        ci.mean == pytest.approx(0.4)
        and ci.lo == pytest.approx(0.4)
        and ci.hi == pytest.approx(0.4)
    )


def test_bootstrap_rejects_empty_samples() -> None:
    with pytest.raises(ValueError):
        metrics.bootstrap_mean_ci([])


def test_paired_bootstrap_sign_when_one_model_is_strictly_better() -> None:
    rng = np.random.default_rng(0)
    worse = (rng.random(300) < 0.3).astype(float)
    better = np.maximum(worse, (rng.random(300) < 0.3).astype(float))  # never worse per caption
    ab = metrics.paired_bootstrap_diff(better, worse)
    ba = metrics.paired_bootstrap_diff(worse, better)
    assert ab.diff > 0 and ab.lo > 0 and ab.excludes_zero
    assert ba.diff < 0 and ba.hi < 0 and ba.excludes_zero
    assert ab.diff == pytest.approx(-ba.diff)


def test_paired_bootstrap_of_equal_models_includes_zero() -> None:
    values = np.random.default_rng(2).random(100)
    same = metrics.paired_bootstrap_diff(values, values)
    assert same.diff == 0.0 and not same.excludes_zero
    noise = np.random.default_rng(3)
    a, b = noise.random(100), noise.random(100)
    assert not metrics.paired_bootstrap_diff(a, b).excludes_zero


def test_paired_bootstrap_is_deterministic_and_checks_shapes() -> None:
    a, b = np.arange(50.0), np.arange(50.0)[::-1]
    assert metrics.paired_bootstrap_diff(a, b, seed=3) == metrics.paired_bootstrap_diff(
        a, b, seed=3
    )
    with pytest.raises(ValueError):
        metrics.paired_bootstrap_diff([1.0, 2.0], [1.0])
