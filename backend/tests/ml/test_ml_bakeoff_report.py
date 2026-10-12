"""The recommendation rule and the Markdown report, on synthetic results."""

from __future__ import annotations

import pytest

from mcrar.ml.bakeoff import common
from mcrar.ml.bakeoff.common import BakeoffError
from mcrar.ml.bakeoff.report import RATINGS_COVERAGE_MIN, build_report, recommend, render_report

CLAP, GLAP, MUQ = "clap@195c3a3", "glap@79b1301", "muq-mulan@2e01c79"
COMMERCIAL = {CLAP: True, GLAP: True, MUQ: False}


def sdd_result(r10: dict[str, float], pairs: dict[tuple[str, str], tuple[float, float, float]]):
    """Synthetic sdd-eval output; ``pairs[(a, b)] = (diff, lo, hi)`` for R@10."""
    results = {
        m: {
            "t2a": {
                "n_captions": 100,
                "n_tracks": 80,
                "R@1": v / 4,
                "R@5": v / 2,
                "R@10": v,
                "median_rank": 7.0,
                "mrr": v / 3,
                "R@10_ci": [v - 0.05, v + 0.05],
                "mrr_ci": [v / 3 - 0.02, v / 3 + 0.02],
            },
            "a2t": {"n_tracks": 80, "R@10": v - 0.1},
        }
        for m, v in r10.items()
    }
    pairwise = [
        {
            "a": a,
            "b": b,
            "metric": "R@10",
            "diff": d,
            "ci": [lo, hi],
            "significant": lo > 0 or hi < 0,
        }
        for (a, b), (d, lo, hi) in pairs.items()
    ]
    return {
        "kind": "sdd",
        "subset": "validated",
        "n_captions": 100,
        "n_tracks": 80,
        "n_resamples": 1000,
        "seed": 0,
        "results": results,
        "pairwise": pairwise,
        "models_info": {
            m: {"key": m.split("@")[0], "license": "X", "commercial_ok": ok}
            for m, ok in COMMERCIAL.items()
        },
    }


def ratings_result(mean: dict[str, float], pairs, coverage: float):
    return {
        "kind": "ratings",
        "k": 3,
        "n_queries": 15,
        "coverage": {
            "pool_items": 100,
            "pool_rated": round(coverage * 100),
            "pool_fraction": coverage,
            "min_model_fraction": coverage,
        },
        "results": {
            m: {
                "mean_rating": v,
                "ndcg": 0.5,
                "share_relevant": 0.5,
                "coverage": coverage,
                "n_queries_scored": 15,
            }
            for m, v in mean.items()
        },
        "pairwise": [
            {
                "a": a,
                "b": b,
                "metric": "mean_rating",
                "n_queries": 15,
                "diff": d,
                "ci": [lo, hi],
                "significant": lo > 0 or hi < 0,
            }
            for (a, b), (d, lo, hi) in pairs.items()
        ],
    }


# -- the rule -------------------------------------------------------------------------------------


def test_the_best_permissive_model_is_the_default() -> None:
    sdd = sdd_result(
        {CLAP: 0.30, GLAP: 0.45, MUQ: 0.40},
        {(GLAP, CLAP): (0.15, 0.08, 0.22), (MUQ, GLAP): (-0.05, -0.12, 0.02)},
    )
    rec = recommend(COMMERCIAL, sdd, None)
    assert rec["evidence"] == "sdd"
    assert rec["default"] == GLAP
    assert rec["flagged"] is None  # MuQ is lower here anyway


def test_a_noncommercial_model_that_wins_only_within_noise_is_not_flagged() -> None:
    sdd = sdd_result(
        {CLAP: 0.30, GLAP: 0.40, MUQ: 0.43},
        {(MUQ, GLAP): (0.03, -0.03, 0.09), (GLAP, CLAP): (0.10, 0.04, 0.16)},
    )
    rec = recommend(COMMERCIAL, sdd, None)
    assert rec["default"] == GLAP and rec["flagged"] is None


def test_a_significantly_better_noncommercial_model_is_flagged_but_not_the_default() -> None:
    sdd = sdd_result(
        {CLAP: 0.30, GLAP: 0.40, MUQ: 0.55},
        {(MUQ, GLAP): (0.15, 0.08, 0.22), (GLAP, CLAP): (0.10, 0.04, 0.16)},
    )
    rec = recommend(COMMERCIAL, sdd, None)
    assert rec["default"] == GLAP
    assert rec["flagged"] == {"model": MUQ, "diff": 0.15, "ci": [0.08, 0.22]}


def test_the_pairwise_table_may_be_stored_either_way_round() -> None:
    sdd = sdd_result({CLAP: 0.30, MUQ: 0.55}, {(CLAP, MUQ): (-0.25, -0.31, -0.19)})
    rec = recommend(COMMERCIAL, sdd, None)
    assert rec["flagged"] == {"model": MUQ, "diff": 0.25, "ci": [0.19, 0.31]}


def test_no_comparison_in_the_results_means_no_flag() -> None:
    sdd = sdd_result({CLAP: 0.30, MUQ: 0.55}, {})
    assert recommend(COMMERCIAL, sdd, None)["flagged"] is None


def test_without_a_permissive_model_there_is_no_default() -> None:
    rec = recommend(COMMERCIAL, sdd_result({MUQ: 0.5}, {}), None)
    assert rec["default"] is None
    assert any("permissive" in n for n in rec["notes"])


def test_ratings_override_the_sdd_verdict_when_covered() -> None:
    sdd = sdd_result({CLAP: 0.50, GLAP: 0.30}, {(CLAP, GLAP): (0.2, 0.1, 0.3)})
    ratings = ratings_result({CLAP: 0.8, GLAP: 1.4}, {(GLAP, CLAP): (0.6, 0.2, 1.0)}, coverage=0.9)
    rec = recommend(COMMERCIAL, sdd, ratings)
    assert rec["evidence"] == "ratings"
    assert rec["default"] == GLAP
    assert rec["sdd_default"] == CLAP
    assert any("overrode" in n for n in rec["notes"])


def test_ratings_with_low_coverage_do_not_override() -> None:
    sdd = sdd_result({CLAP: 0.50, GLAP: 0.30}, {})
    ratings = ratings_result({CLAP: 0.8, GLAP: 1.4}, {}, coverage=0.79)
    rec = recommend(COMMERCIAL, sdd, ratings)
    assert rec["evidence"] == "sdd" and rec["default"] == CLAP
    assert any("79%" in n for n in rec["notes"])
    exactly = recommend(COMMERCIAL, sdd, ratings_result({CLAP: 0.8, GLAP: 1.4}, {}, 0.8))
    assert exactly["evidence"] == "ratings" and exactly["default"] == GLAP
    assert RATINGS_COVERAGE_MIN == 0.8


def test_ratings_can_flag_a_noncommercial_model_with_their_own_interval() -> None:
    ratings = ratings_result(
        {CLAP: 0.8, GLAP: 1.0, MUQ: 1.6},
        {(MUQ, GLAP): (0.6, 0.3, 0.9), (GLAP, CLAP): (0.2, -0.1, 0.5)},
        coverage=0.95,
    )
    rec = recommend(COMMERCIAL, None, ratings)
    assert rec["evidence"] == "ratings" and rec["default"] == GLAP
    assert rec["flagged"]["model"] == MUQ


def test_nothing_to_go_on() -> None:
    rec = recommend(COMMERCIAL, None, None)
    assert rec["evidence"] is None and rec["default"] is None


# -- the document ---------------------------------------------------------------------------------


def test_report_states_the_rule_and_the_verdict() -> None:
    sdd = sdd_result(
        {CLAP: 0.30, GLAP: 0.40, MUQ: 0.55},
        {(MUQ, GLAP): (0.15, 0.08, 0.22), (GLAP, CLAP): (0.10, 0.04, 0.16)},
    )
    text = render_report(sdd=sdd, sources={"sdd": "sdd_x.json"})
    assert text.startswith("# Embedder bake-off")
    assert "## Recommendation" in text and "Rule" in text and "80%" in text
    assert f"**Default model: `{GLAP}`**" in text
    assert f"`{MUQ}` is best overall but non-commercial" in text
    assert "## Models and licences" in text and "NON-COMMERCIAL" in text
    assert "R@10 (95% CI)" in text and "0.400 [0.350, 0.450]" in text
    assert "`sdd_x.json`" in text
    assert "Not run yet: `mcrar bakeoff tag-eval`" in text
    assert "Not rated yet" in text and "Not run yet: `mcrar models benchmark" in text
    assert text.endswith("\n") and "\r" not in text


def test_report_renders_every_section() -> None:
    sdd = sdd_result({CLAP: 0.3, GLAP: 0.4}, {(GLAP, CLAP): (0.1, 0.04, 0.16)})
    tags = {
        "kind": "tags",
        "note": "Relevance comes from the uploader's Jamendo genre tags (noisy).",
        "min_tracks": 15,
        "n_tracks": 500,
        "tags": [{"tag": "rock", "n_relevant": 90, "prevalence": 0.18}],
        "results": {
            CLAP: {"macro_AP": 0.41, "macro_P@10": 0.5},
            GLAP: {"macro_AP": 0.52, "macro_P@10": 0.6},
        },
    }
    ratings = ratings_result({CLAP: 0.8, GLAP: 1.4}, {(GLAP, CLAP): (0.6, 0.2, 1.0)}, 0.9)
    bench = {
        "kind": "benchmark",
        "seconds": 60.0,
        "rows": [
            {
                "model_id": CLAP,
                "device": "cuda",
                "dtype": "fp16",
                "load_s": 4.2,
                "peak_vram_mb": 900.0,
                "resident_vram_mb": 700.0,
                "audio_s_per_s": 55.0,
                "texts_per_s": 80.0,
                "dim": 512,
            }
        ],
    }
    text = render_report(sdd=sdd, tags=tags, ratings=ratings, benchmark=bench)
    for expected in (
        "## Genre tags",
        "uploader's Jamendo genre tags",
        "rock (90)",
        "0.410",
        "## Blind ratings",
        "Mean rating@3",
        "90%",
        "## Speed and memory",
        "Peak VRAM MB",
        "| 900 |",
        "based on the user's ratings",
    ):
        assert expected in text, expected


def test_report_with_no_results_says_so() -> None:
    text = render_report()
    assert "nothing to recommend" in text


def test_build_report_uses_the_newest_file_of_each_kind(tmp_path) -> None:
    old = sdd_result({CLAP: 0.1, GLAP: 0.2}, {})
    new = sdd_result({CLAP: 0.6, GLAP: 0.5}, {})
    common.write_json(tmp_path / "sdd_20260101T000000Z.json", old)
    common.write_json(tmp_path / "sdd_20260202T000000Z.json", new)
    common.write_json(tmp_path / "candidates_20260303T000000Z.private.json", {"q01": {}})
    text, used = build_report(tmp_path)
    assert used == {"sdd": "sdd_20260202T000000Z.json"}
    assert f"**Default model: `{CLAP}`**" in text


def test_build_report_without_results_is_an_error(tmp_path) -> None:
    with pytest.raises(BakeoffError, match="no results"):
        build_report(tmp_path)
    with pytest.raises(BakeoffError):
        build_report(tmp_path / "missing")
