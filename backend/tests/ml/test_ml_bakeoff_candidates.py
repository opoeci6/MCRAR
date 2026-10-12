"""The blind candidate pool and the scoring of the user's ratings."""

from __future__ import annotations

import json

import numpy as np
import pytest

from mcrar.catalog import CatalogRepository, TrackRecord
from mcrar.ml.bakeoff import candidates as cand
from mcrar.ml.bakeoff.common import BakeoffError
from mcrar.ml.bakeoff.queries import DEFAULT_QUERIES, load_queries, query_ids

IDS = np.array([10, 11, 12, 13, 14])
TRACKS = {
    "A": np.array([[1, 0], [0.8, 0.6], [0, 1], [-1, 0], [0.5, 0.5]], dtype=np.float32),
    "B": np.array([[0, 1], [1, 0], [0.6, 0.8], [0, -1], [0.9, 0.1]], dtype=np.float32),
}
# query 0 points along x, query 1 along y
QUERIES = {name: np.array([[1, 0], [0, 1]], dtype=np.float32) for name in TRACKS}
ITEMS = {int(i): {"track_id": int(i), "title": f"title {i}"} for i in IDS}
TEXTS = ["first query", "second query"]


def build(per_model: int = 3, preferred: set[int] | None = None, models=("A", "B")):
    return cand.build_candidates(
        TEXTS,
        list(models),
        IDS,
        {m: TRACKS[m] for m in models},
        {m: QUERIES[m] for m in models},
        ITEMS,
        preferred or set(),
        per_model,
    )


# -- queries --------------------------------------------------------------------------------------


def test_default_queries_are_the_fifteen_scenes() -> None:
    assert len(DEFAULT_QUERIES) == 15 and len(set(DEFAULT_QUERIES)) == 15
    assert DEFAULT_QUERIES[0] == "tense stealth level, no vocals"
    assert load_queries(None) == list(DEFAULT_QUERIES)
    assert query_ids(3) == ["q01", "q02", "q03"]
    assert query_ids(100)[0] == "q001"


def test_load_queries_from_a_file_skips_blank_lines(tmp_path) -> None:
    path = tmp_path / "q.txt"
    path.write_text("﻿one\n\n  two  \n", encoding="utf-8")
    assert load_queries(path) == ["one", "two"]
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(BakeoffError, match="no queries"):
        load_queries(path)
    with pytest.raises(BakeoffError, match="cannot read"):
        load_queries(tmp_path / "missing.txt")


# -- building the pool ----------------------------------------------------------------------------


def test_pool_is_deduplicated_and_the_private_map_points_back() -> None:
    pooled, private = build()
    assert [q["id"] for q in pooled] == ["q01", "q02"]
    assert [q["text"] for q in pooled] == TEXTS
    first = {i["track_id"] for i in pooled[0]["items"]}
    assert first == {10, 11, 12, 14}  # A: 10, 11, 14; B: 11, 14, 12
    assert len(pooled[0]["items"]) == len(first)  # 11 and 14 were proposed twice, listed once
    assert private["q01"] == {
        "10": [{"model": "A", "rank": 1}],
        "11": [{"model": "A", "rank": 2}, {"model": "B", "rank": 1}],
        "12": [{"model": "B", "rank": 3}],
        "14": [{"model": "A", "rank": 3}, {"model": "B", "rank": 2}],
    }
    second = {i["track_id"] for i in pooled[1]["items"]}
    assert second == {10, 11, 12, 14}  # A: 12, 14, 11; B: 10, 12, 14
    assert {int(t) for t in private["q02"]} == second
    assert private["q02"]["12"] == [{"model": "A", "rank": 1}, {"model": "B", "rank": 2}]


def test_private_map_keys_follow_the_blind_order() -> None:
    pooled, private = build()
    for q in pooled:
        assert [str(i["track_id"]) for i in q["items"]] == list(private[q["id"]])


def test_blind_order_is_deterministic_and_does_not_depend_on_the_models() -> None:
    first, _ = build()
    again, _ = build()
    assert first == again
    reversed_models, _ = build(models=("B", "A"))
    assert [q["items"] for q in first] == [q["items"] for q in reversed_models]
    for q in first:
        keys = [cand.blind_key(q["text"], i["track_id"]) for i in q["items"]]
        assert keys == sorted(keys)


def test_blind_order_differs_between_queries() -> None:
    assert cand.blind_key("a", 1) != cand.blind_key("b", 1)
    assert cand.blind_key("a", 1) != cand.blind_key("a", 2)


def test_public_items_never_reveal_which_model_proposed_them() -> None:
    pooled, _ = build()
    text = json.dumps(pooled)
    assert '"A"' not in text and '"B"' not in text
    for q in pooled:
        for item in q["items"]:
            assert not {"model", "models", "rank", "ranks"} & set(item)


def test_per_model_limits_each_models_share() -> None:
    pooled, private = build(per_model=1)
    assert {i["track_id"] for i in pooled[0]["items"]} == {10, 11}
    assert all(len(p) == 1 for p in private["q01"].values())
    with pytest.raises(ValueError):
        build(per_model=0)


def test_downloadable_tracks_are_preferred_without_hiding_the_rest() -> None:
    _, private = build(per_model=2, preferred={12, 13})
    # by score alone 12 and 13 would not be near the top of query 1; downloadable ones lead
    assert private["q01"] == {
        "12": [{"model": "A", "rank": 1}, {"model": "B", "rank": 1}],
        "13": [{"model": "A", "rank": 2}, {"model": "B", "rank": 2}],
    }
    # with one downloadable track, the other places go to each model's best remaining track
    _, private = build(per_model=2, preferred={13})
    assert {int(t) for t in private["q01"]} == {13, 10, 11}
    assert private["q01"]["10"] == [{"model": "A", "rank": 2}]
    assert private["q01"]["11"] == [{"model": "B", "rank": 2}]


def test_rank_pool_orders_by_score_with_preferred_first() -> None:
    scores = np.array([0.1, 0.9, 0.5, 0.9])
    ids = np.array([5, 6, 7, 8])
    assert cand.rank_pool(ids, scores, set()) == [6, 8, 7, 5]  # ties: smaller id first
    assert cand.rank_pool(ids, scores, {5, 7}) == [7, 5, 6, 8]


# -- items and eligibility -----------------------------------------------------------------------


def _track(repo: CatalogRepository, n: int, **kwargs) -> int:
    fields = {"source": "jamendo", "source_id": str(n), "title": f"T{n}", "risk": "green"}
    return repo.upsert_track(TrackRecord(**(fields | kwargs)))


def test_eligible_tracks_need_embeddings_for_all_models_and_a_source_url(repo) -> None:
    with_url = _track(repo, 1, source_url="https://example.test/1")
    without_url = _track(repo, 2)
    not_embedded = _track(repo, 3, source_url="https://example.test/3")
    found = cand.eligible_tracks(repo, np.array([with_url, without_url]))
    assert [t.id for t in found] == [with_url]
    assert not_embedded not in [t.id for t in found]


def test_item_for_rounds_and_leaves_out_the_model(repo) -> None:
    track_id = _track(
        repo,
        1,
        artist="Someone",
        source_url="https://example.test/1",
        license_code="CC BY 3.0",
        risk="amber",
        duration_s=123.456,
        source_tags={"genres": ["ambient"], "vartags": ["calm", "dark"], "instruments": ["x"]},
    )
    track = repo.get_track(track_id)
    item = cand.item_for(
        track, {"bpm": 120.4, "key": "C", "mode": "minor", "energy": 0.4567, "other": 1}
    )
    assert item == {
        "track_id": track_id,
        "title": "T1",
        "artist": "Someone",
        "source_url": "https://example.test/1",
        "risk": "amber",
        "license_code": "CC BY 3.0",
        "bpm": 120,
        "key": "C",
        "mode": "minor",
        "energy": 0.46,
        "genres": ["ambient"],
        "vartags": ["calm", "dark"],
        "duration_s": 123.5,
    }
    bare = cand.item_for(repo.get_track(_track(repo, 2)), None)
    assert bare["bpm"] is None and bare["energy"] is None and bare["genres"] == []


# -- ratings --------------------------------------------------------------------------------------


def test_parse_ratings_validates_and_keeps_the_last_duplicate() -> None:
    data = {
        "ratings": [
            {"query_id": "q01", "track_id": 1, "score": 0},
            {"query_id": "q01", "track_id": "1", "score": 2},
        ]
    }
    assert cand.parse_ratings(data) == {("q01", 1): 2}
    for bad in (
        [],
        {},
        {"ratings": [{"query_id": "q01", "track_id": 1}]},
        {"ratings": [{"query_id": "q01", "track_id": 1, "score": 3}]},
        {"ratings": [{"query_id": "q01", "track_id": 1, "score": True}]},
        {"ratings": [{"query_id": "q01", "track_id": "x", "score": 1}]},
    ):
        with pytest.raises(BakeoffError):
            cand.parse_ratings(bad)


POOL = {
    "models": ["A", "B"],
    "per_model": 2,
    "queries": [
        {"id": "q01", "text": "one", "items": [{"track_id": 1}, {"track_id": 2}, {"track_id": 3}]},
        {"id": "q02", "text": "two", "items": [{"track_id": 4}, {"track_id": 5}, {"track_id": 6}]},
    ],
}
PRIVATE = {
    "q01": {
        "1": [{"model": "A", "rank": 1}],
        "2": [{"model": "A", "rank": 2}, {"model": "B", "rank": 2}],
        "3": [{"model": "B", "rank": 1}],
    },
    "q02": {
        "4": [{"model": "A", "rank": 1}, {"model": "B", "rank": 2}],
        "5": [{"model": "A", "rank": 2}],
        "6": [{"model": "B", "rank": 1}],
    },
}
RATINGS = {
    ("q01", 1): 2,
    ("q01", 2): 1,
    ("q01", 3): 0,
    ("q02", 4): 2,
    ("q02", 5): 0,
    ("q02", 6): 1,
}
IDEAL_2 = 2 + 1 / np.log2(3)  # ideal DCG@2 when the pool holds a 2 and a 1


def test_score_ratings_known_answer() -> None:
    out = cand.score_ratings(POOL, PRIVATE, RATINGS, k=2, n_resamples=50)
    a, b = out["results"]["A"], out["results"]["B"]
    # A: q01 ranks [1, 2] -> gains [2, 1] (ideal); q02 ranks [4, 5] -> gains [2, 0]
    assert a["per_query"]["q01"]["mean_rating"] == 1.5
    assert a["per_query"]["q01"]["ndcg"] == 1.0
    assert a["per_query"]["q02"]["ndcg"] == pytest.approx(2 / IDEAL_2, abs=1e-4)
    assert a["mean_rating"] == 1.25 and a["share_relevant"] == 0.75
    assert a["ndcg"] == pytest.approx((1 + 2 / IDEAL_2) / 2, abs=1e-4)
    # B: q01 ranks [3, 2] -> gains [0, 1]; q02 ranks [6, 4] -> gains [1, 2]
    assert b["per_query"]["q01"]["share_relevant"] == 0.5
    assert b["mean_rating"] == 1.0 and b["share_relevant"] == 0.75
    assert b["ndcg"] == pytest.approx(
        ((1 / np.log2(3)) / IDEAL_2 + (1 + 2 / np.log2(3)) / IDEAL_2) / 2, abs=1e-4
    )
    assert out["coverage"]["pool_fraction"] == 1.0 and out["coverage"]["min_model_fraction"] == 1.0
    pair = out["pairwise"][0]
    assert (pair["a"], pair["b"], pair["metric"], pair["n_queries"]) == ("A", "B", "mean_rating", 2)
    assert pair["diff"] == 0.25


def test_score_ratings_k1_uses_only_each_models_first_choice() -> None:
    out = cand.score_ratings(POOL, PRIVATE, RATINGS, k=1, n_resamples=20)
    assert out["results"]["A"]["mean_rating"] == 2.0  # tracks 1 and 4
    assert out["results"]["B"]["mean_rating"] == pytest.approx(0.5)  # tracks 3 and 6


def test_score_ratings_excludes_unrated_items_and_reports_coverage() -> None:
    partial = {pair: s for pair, s in RATINGS.items() if pair not in {("q01", 3), ("q02", 5)}}
    partial[("q01", 99)] = 2  # not in the pool
    partial[("q09", 1)] = 1  # not a query
    out = cand.score_ratings(POOL, PRIVATE, partial, k=2, n_resamples=20)
    cov = out["coverage"]
    assert (cov["pool_items"], cov["pool_rated"]) == (6, 4)
    assert cov["pool_fraction"] == pytest.approx(0.6667, abs=1e-4)
    assert cov["unknown_ratings_ignored"] == 2
    a, b = out["results"]["A"], out["results"]["B"]
    assert (a["n_items"], a["n_rated"], a["n_unrated"]) == (4, 3, 1)
    assert a["coverage"] == 0.75 and b["coverage"] == 0.75
    assert a["per_query"]["q02"]["n_unrated"] == 1
    assert a["per_query"]["q02"]["mean_rating"] == 2.0  # only track 4 was rated
    assert cov["min_model_fraction"] == 0.75


def test_score_ratings_with_a_query_nobody_rated_scores_the_others() -> None:
    only_q01 = {pair: s for pair, s in RATINGS.items() if pair[0] == "q01"}
    out = cand.score_ratings(POOL, PRIVATE, only_q01, k=2, n_resamples=20)
    a = out["results"]["A"]
    assert a["n_queries_scored"] == 1 and a["mean_rating"] == 1.5
    assert a["per_query"]["q02"]["mean_rating"] is None and a["per_query"]["q02"]["ndcg"] is None
    assert out["pairwise"][0]["n_queries"] == 1


def test_score_ratings_rejects_k_above_per_model() -> None:
    with pytest.raises(BakeoffError, match="per_model"):
        cand.score_ratings(POOL, PRIVATE, RATINGS, k=3)
