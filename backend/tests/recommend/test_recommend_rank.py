"""The ranking maths: terms, weights, breakdown sums, ties and the per-artist cap."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mcrar.config import SearchWeights
from mcrar.recommend.rank import (
    Candidate,
    bpm_term,
    effective_weights,
    energy_term,
    minmax,
    rank_candidates,
)

W = SearchWeights()


def test_minmax_scales_to_the_unit_interval() -> None:
    assert minmax([0.2, 0.6, 1.0]).tolist() == pytest.approx([0.0, 0.5, 1.0])
    assert minmax([-1.0, 0.0]).tolist() == [0.0, 1.0]


def test_minmax_of_one_value_or_ties_is_one() -> None:
    assert minmax([0.37]).tolist() == [1.0]
    assert minmax([0.5, 0.5, 0.5]).tolist() == [1.0, 1.0, 1.0]
    assert minmax([]).tolist() == []


def test_bpm_term_formula_at_known_points() -> None:
    assert bpm_term(120, 0.9, 120) == 1.0
    assert bpm_term(135, 0.9, 120) == pytest.approx(math.exp(-1))
    assert bpm_term(105, 0.9, 120) == pytest.approx(math.exp(-1))
    assert bpm_term(150, 0.9, 120) == pytest.approx(math.exp(-4))
    assert bpm_term(127.5, 0.9, 120) == pytest.approx(math.exp(-0.25))
    assert bpm_term(None, 0.9, 120) == 0.0


def test_bpm_term_octave_awareness_only_at_low_confidence() -> None:
    assert bpm_term(70, 0.3, 140) == 1.0  # probably 140 counted as 70
    assert bpm_term(280, 0.1, 140) == 1.0  # or the other way round
    assert bpm_term(70, None, 140) == 1.0  # unknown confidence counts as low
    assert bpm_term(70, 0.5, 140) == pytest.approx(math.exp(-((70 / 15) ** 2)))  # not < 0.5
    assert bpm_term(70, 0.9, 140) == pytest.approx(math.exp(-((70 / 15) ** 2)))
    assert bpm_term(100, 0.3, 140) == pytest.approx(
        math.exp(-((40 / 15) ** 2))
    )  # best of 50/100/200


def test_energy_term_formula_at_known_points() -> None:
    assert energy_term(0.3, 0.3) == 1.0
    assert energy_term(0.31, 0.3) == pytest.approx(0.99)
    assert energy_term(0.4, 0.8) == pytest.approx(0.6)
    assert energy_term(1.0, 0.0) == 0.0
    assert energy_term(None, 0.3) == 0.0


def test_default_weights_are_the_documented_ones() -> None:
    assert (W.semantic, W.tags, W.bpm, W.energy) == (0.6, 0.2, 0.1, 0.1)


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        (["semantic", "tags", "bpm", "energy"], (0.6, 0.2, 0.1, 0.1)),
        (["semantic"], (1.0, 0.0, 0.0, 0.0)),
        (["semantic", "bpm"], (0.6 / 0.7, 0.0, 0.1 / 0.7, 0.0)),
        (["tags", "energy"], (0.0, 0.2 / 0.3, 0.0, 0.1 / 0.3)),
        (["bpm"], (0.0, 0.0, 1.0, 0.0)),
        ([], (0.0, 0.0, 0.0, 0.0)),
    ],
)
def test_inactive_terms_are_dropped_and_the_rest_renormalised(
    active: list[str], expected: tuple[float, ...]
) -> None:
    got = effective_weights(W, active)
    assert tuple(got.values()) == pytest.approx(expected)
    assert list(got) == ["semantic", "tags", "bpm", "energy"]
    assert sum(got.values()) == pytest.approx(1.0 if active else 0.0)


def test_active_terms_that_all_weigh_zero_share_equally() -> None:
    only_semantic = SearchWeights(semantic=1.0, tags=0.0, bpm=0.0, energy=0.0)
    got = effective_weights(only_semantic, ["bpm", "energy"])
    assert got == {"semantic": 0.0, "tags": 0.0, "bpm": 0.5, "energy": 0.5}


def candidates(n: int = 12, seed: int = 0) -> list[Candidate]:
    rng = np.random.default_rng(seed)
    artists = ["A", "B", "C", None]
    return [
        Candidate(
            track_id=i + 1,
            artist=artists[i % len(artists)],
            cosine=float(rng.uniform(-0.2, 0.9)),
            bpm=float(rng.uniform(50, 180)),
            bpm_confidence=float(rng.uniform(0, 1)),
            energy=float(rng.uniform(0, 1)),
            tags=tuple(float(x) for x in rng.uniform(0, 1, size=2)),
        )
        for i in range(n)
    ]


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize(
    ("semantic", "tags", "bpm", "energy"),
    [
        (True, True, 100.0, 0.5),
        (True, False, None, None),
        (False, True, None, 0.3),
        (True, False, 80.0, None),
        (False, False, 120.0, 0.8),
        (False, False, None, None),
    ],
)
def test_contributions_sum_to_the_score(
    seed: int, semantic: bool, tags: bool, bpm: float | None, energy: float | None
) -> None:
    cands = candidates(seed=seed)
    ranked = rank_candidates(
        cands, weights=W, semantic=semantic, tags=tags, bpm_target=bpm, energy_target=energy
    )
    assert len(ranked) == len(cands)
    any_active = semantic or tags or bpm is not None or energy is not None
    for r in ranked:
        contributions = [t.contribution for t in r.breakdown.terms.values()]
        assert sum(contributions) == pytest.approx(r.score)
        assert r.score == r.breakdown.score
        assert 0.0 <= r.score <= 1.0 + 1e-9
        weights = [t.weight for t in r.breakdown.terms.values()]
        assert sum(weights) == pytest.approx(1.0 if any_active else 0.0)
        for term in r.breakdown.terms.values():
            assert term.contribution == pytest.approx(term.weight * (term.raw or 0.0))
            assert (term.raw is None) == (term.weight == 0.0)  # inactive: no raw, no weight
    assert [r.score for r in ranked] == sorted((r.score for r in ranked), reverse=True)


def test_breakdown_reports_raw_weight_and_contribution_per_term() -> None:
    cands = [
        Candidate(1, cosine=0.9, bpm=100, bpm_confidence=0.9, energy=0.5, tags=(1.0, 0.0)),
        Candidate(2, cosine=0.5, bpm=130, bpm_confidence=0.9, energy=0.9, tags=(0.0, 0.0)),
    ]
    first, second = rank_candidates(
        cands, weights=W, semantic=True, tags=True, bpm_target=100.0, energy_target=0.5
    )
    assert first.track_id == 1 and second.track_id == 2
    t = first.breakdown.terms
    assert t["semantic"].raw == 1.0 and t["semantic"].weight == pytest.approx(0.6)
    assert t["tags"].raw == 0.5  # mean of the requested labels
    assert t["bpm"].raw == 1.0 and t["energy"].raw == 1.0
    assert first.score == pytest.approx(0.6 + 0.2 * 0.5 + 0.1 + 0.1)
    s = second.breakdown.terms
    assert s["semantic"].raw == 0.0 and s["tags"].raw == 0.0
    assert s["bpm"].raw == pytest.approx(math.exp(-4))
    assert s["energy"].raw == pytest.approx(0.6)
    assert first.breakdown.to_dict()["tags"] == {"raw": 0.5, "weight": 0.2, "contribution": 0.1}


def test_a_track_without_data_for_an_active_term_scores_zero_on_it() -> None:
    ranked = rank_candidates(
        [Candidate(1, bpm=None, energy=None), Candidate(2, bpm=100, energy=0.5)],
        weights=W,
        semantic=False,
        tags=False,
        bpm_target=100.0,
        energy_target=0.5,
    )
    assert [r.track_id for r in ranked] == [2, 1]
    assert ranked[1].score == 0.0


def test_a_single_candidate_gets_the_full_semantic_term() -> None:
    (only,) = rank_candidates([Candidate(7, cosine=0.123)], weights=W, semantic=True, tags=False)
    assert only.breakdown.terms["semantic"].raw == 1.0 and only.score == pytest.approx(1.0)


def test_ties_break_by_track_id() -> None:
    cands = [Candidate(i, cosine=0.5) for i in (9, 3, 7, 1)]
    ranked = rank_candidates(cands, weights=W, semantic=True, tags=False)
    assert [r.track_id for r in ranked] == [1, 3, 7, 9]


def test_with_no_active_term_every_score_is_zero_and_order_is_by_id() -> None:
    ranked = rank_candidates(
        [Candidate(5), Candidate(2), Candidate(9)], weights=W, semantic=False, tags=False
    )
    assert [(r.track_id, r.score) for r in ranked] == [(2, 0.0), (5, 0.0), (9, 0.0)]


def test_float_noise_does_not_break_a_tie() -> None:
    noisy = [Candidate(2, tags=(0.3 + 1e-14,)), Candidate(1, tags=(0.3,))]
    ranked = rank_candidates(noisy, weights=W, semantic=False, tags=True)
    assert [r.track_id for r in ranked] == [1, 2]


def test_artist_cap_demotes_over_cap_tracks_behind_every_in_cap_track() -> None:
    cands = [
        Candidate(1, "A", cosine=0.9),
        Candidate(2, "A", cosine=0.8),
        Candidate(3, "A", cosine=0.7),
        Candidate(4, "B", cosine=0.6),
        Candidate(5, "A", cosine=0.5),
        Candidate(6, "C", cosine=0.4),
    ]
    ranked = rank_candidates(cands, weights=W, semantic=True, tags=False, max_per_artist=2)
    assert [r.track_id for r in ranked] == [1, 2, 4, 6, 3, 5]  # A's extras keep their order
    uncapped = rank_candidates(cands, weights=W, semantic=True, tags=False)
    assert [r.track_id for r in uncapped] == [1, 2, 3, 4, 5, 6]
    one = rank_candidates(cands, weights=W, semantic=True, tags=False, max_per_artist=1)
    assert [r.track_id for r in one] == [1, 4, 6, 2, 3, 5]
    for r in ranked:  # demoting does not change a track's score
        assert r.score == next(u.score for u in uncapped if u.track_id == r.track_id)


def test_artist_cap_ignores_case_and_spaces_and_never_caps_missing_artists() -> None:
    cands = [
        Candidate(1, "Ada", cosine=0.9),
        Candidate(2, " ada ", cosine=0.8),
        Candidate(3, "ADA", cosine=0.7),
        Candidate(4, None, cosine=0.6),
        Candidate(5, "", cosine=0.5),
        Candidate(6, None, cosine=0.4),
    ]
    ranked = rank_candidates(cands, weights=W, semantic=True, tags=False, max_per_artist=1)
    assert [r.track_id for r in ranked] == [1, 4, 5, 6, 2, 3]


def test_ties_break_by_risk_first_then_track_id() -> None:
    cands = [
        Candidate(1, risk="unknown"),
        Candidate(2, risk="red"),
        Candidate(3, risk="green"),
        Candidate(4, risk="amber"),
        Candidate(5, risk="green"),
        Candidate(6, risk="amber"),
    ]
    ranked = rank_candidates(cands, weights=W, semantic=False, tags=False)  # all scores 0
    assert [r.track_id for r in ranked] == [3, 5, 4, 6, 2, 1]
    scored = rank_candidates(
        [Candidate(1, cosine=0.5, risk="red"), Candidate(2, cosine=0.5, risk="green")],
        weights=W,
        semantic=True,
        tags=False,
    )
    assert [r.track_id for r in scored] == [2, 1]
    # A better score still beats a better licence.
    better = rank_candidates(
        [Candidate(1, tags=(0.9,), risk="red"), Candidate(2, tags=(0.1,), risk="green")],
        weights=W,
        semantic=False,
        tags=True,
    )
    assert [r.track_id for r in better] == [1, 2]
