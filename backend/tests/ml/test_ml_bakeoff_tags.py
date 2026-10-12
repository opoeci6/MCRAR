"""Tag evaluation: the track set shared by all models, the min-tracks filter, AP and P@10."""

from __future__ import annotations

import numpy as np
import pytest

from mcrar.ml.bakeoff import tags


def test_track_genres_normalises_and_tolerates_missing_tags() -> None:
    assert tags.track_genres({"genres": ["Rock", " jazz ", ""]}) == {"rock", "jazz"}
    assert tags.track_genres({"genres": None}) == set()
    assert tags.track_genres({}) == set()
    assert tags.track_genres(None) == set()


def test_query_text() -> None:
    assert tags.query_text("darkambient") == "darkambient music"


def test_select_tags_applies_min_tracks_to_the_given_tracks_only() -> None:
    genres = {i: {"rock"} for i in range(20)}
    genres |= {i: {"jazz"} for i in range(20, 30)} | {i: {"folk", "rock"} for i in range(30, 45)}
    all_ids = np.arange(45)
    assert tags.select_tags(genres, all_ids, 15) == [("folk", 15), ("rock", 35)]
    assert tags.select_tags(genres, all_ids, 10) == [("folk", 15), ("jazz", 10), ("rock", 35)]
    # restricting the track set (the tracks every model embedded) can drop a tag
    assert tags.select_tags(genres, np.arange(0, 25), 10) == [("rock", 20)]
    assert tags.select_tags(genres, np.arange(0, 25), 21) == []


def test_select_tags_drops_a_tag_every_track_has() -> None:
    genres = {i: {"all"} for i in range(20)}
    assert tags.select_tags(genres, np.arange(20), 5) == []


def test_evaluate_tags_scores_a_perfect_and_a_blind_model() -> None:
    ids = np.arange(40)
    genres = {i: {"rock"} if i < 20 else {"jazz"} for i in ids}
    chosen = [("jazz", 20), ("rock", 20)]
    perfect_tracks = np.where((ids < 20)[:, None], [[1.0, 0.0]], [[0.0, 1.0]]).astype(np.float32)
    queries = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32)  # jazz, rock
    blind_tracks = np.ones((40, 2), dtype=np.float32)  # every track scores the same
    out = tags.evaluate_tags(
        chosen,
        ids,
        genres,
        {"good": perfect_tracks, "blind": blind_tracks},
        {"good": queries, "blind": queries},
    )
    good, blind = out["results"]["good"], out["results"]["blind"]
    assert good["macro_AP"] == 1.0 and good["macro_P@10"] == 1.0
    assert good["per_tag"]["rock"] == {"AP": 1.0, "P@10": 1.0}
    # ties keep the catalog order, so "rock" (first 20 tracks) looks perfect and "jazz" does not:
    # the blind model must be clearly worse than the good one
    assert blind["macro_AP"] < good["macro_AP"]
    assert out["n_tracks"] == 40
    assert out["tags"][0] == {
        "tag": "jazz",
        "query": "jazz music",
        "n_relevant": 20,
        "prevalence": 0.5,
    }
    assert "uploader" in out["note"] and "noisy" in out["note"]


def test_evaluate_tags_macro_average_is_the_mean_of_the_tags() -> None:
    ids = np.arange(20)
    genres = {i: {"a"} if i < 5 else {"b"} for i in ids}
    chosen = [("a", 5), ("b", 15)]
    vectors = np.eye(20, 4, dtype=np.float32) + 0.1
    queries = np.array([[1.0, 0, 0, 0], [0, 0, 1.0, 0]], dtype=np.float32)
    out = tags.evaluate_tags(chosen, ids, genres, {"m": vectors}, {"m": queries})
    per_tag = out["results"]["m"]["per_tag"]
    assert out["results"]["m"]["macro_AP"] == pytest.approx(
        (per_tag["a"]["AP"] + per_tag["b"]["AP"]) / 2, abs=1e-4
    )
