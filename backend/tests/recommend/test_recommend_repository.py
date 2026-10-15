"""Repository additions for search: hard filters, batch readers, embedding stats."""

from __future__ import annotations

import pytest
from recommend_support import MODEL_ID, SPECS, axis, build_catalog

from mcrar.catalog import CatalogRepository, TrackRecord


def names(repo: CatalogRepository, ids: dict[str, int], found: list[int]) -> set[str]:
    by_id = {v: k for k, v in ids.items()}
    return {by_id[i] for i in found}


def test_no_filter_returns_every_track_in_id_order(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    found = repo.filter_track_ids()
    assert found == sorted(ids.values())
    assert len(found) == len(SPECS)


@pytest.mark.parametrize(
    ("max_risk", "allowed"),
    [
        ("green", {"green"}),
        ("amber", {"green", "amber"}),
        ("red", {"green", "amber", "red"}),
        ("unknown", {"green", "amber", "red", "unknown"}),
    ],
)
def test_max_risk(
    repo: CatalogRepository, ids: dict[str, int], max_risk: str, allowed: set[str]
) -> None:
    found = repo.filter_track_ids(max_risk=max_risk)
    risks = {repo.get_track(i).risk for i in found}  # type: ignore[union-attr]
    assert risks == allowed


def test_red_never_passes_amber_and_unknown_is_worse_than_red(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    amber = names(repo, ids, repo.filter_track_ids(max_risk="amber"))
    assert "Red Alert" not in amber and "Metal Gods" not in amber
    red = names(repo, ids, repo.filter_track_ids(max_risk="red"))
    assert {"Red Alert", "Metal Gods"} <= red
    assert "Mystery Box" not in red and "Local Ambient" not in red  # unknown risk


def test_bad_max_risk_or_vocal_is_rejected(repo: CatalogRepository) -> None:
    with pytest.raises(ValueError, match="max_risk"):
        repo.filter_track_ids(max_risk="purple")
    with pytest.raises(ValueError, match="vocal"):
        repo.filter_track_ids(vocal="choir")


def test_vocal_filter_excludes_known_mismatches_but_keeps_unknown(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    instrumental = names(repo, ids, repo.filter_track_ids(vocal="instrumental"))
    vocal = names(repo, ids, repo.filter_track_ids(vocal="vocal"))
    assert "Shadow Walk" in instrumental and "Sunny Day" in vocal
    assert "Sunny Day" not in instrumental and "Shadow Walk" not in vocal  # known mismatches
    # Tracks with no flag (local files never have one) pass either filter.
    assert {"Mystery Box", "Local Ambient"} <= instrumental & vocal
    assert instrumental & vocal == {"Mystery Box", "Local Ambient"}
    local = names(repo, ids, repo.filter_track_ids(vocal="instrumental", sources=["local"]))
    assert local == {"Chip Hero", "Local Ambient"}


def test_duration_bounds(repo: CatalogRepository, ids: dict[str, int]) -> None:
    short = names(repo, ids, repo.filter_track_ids(duration_max_s=120))
    assert short == {"Shadow Walk", "Mystery Box", "Chip Hero", "Unembedded Tune", "Local Ambient"}
    long = names(repo, ids, repo.filter_track_ids(duration_min_s=330))
    assert long == {"Ambient Pad", "Misty Lake", "Local Ambient"}
    between = names(repo, ids, repo.filter_track_ids(duration_min_s=100, duration_max_s=120))
    assert between == {"Shadow Walk", "Unembedded Tune", "Local Ambient"}
    # Local Ambient has no duration: unknown passes every duration bound.


def test_bpm_range_and_tracks_without_features(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    found = names(repo, ids, repo.filter_track_ids(bpm_min=90, bpm_max=100))
    assert found == {
        "Shadow Walk",
        "Quiet Vents",
        "Night Heist",
        "Glory March",
        "Smooth Cafe",
        "Unembedded Tune",
    }
    assert "Local Ambient" not in found  # no features
    assert "Local Ambient" in names(
        repo, ids, repo.filter_track_ids()
    )  # but fine without a bpm filter
    assert "Boss Fight" in names(repo, ids, repo.filter_track_ids(bpm_min=150))
    assert "Lullaby" in names(repo, ids, repo.filter_track_ids(bpm_max=60))


def test_bpm_octave_tolerance_only_applies_at_low_confidence(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    # Mystery Box: 70 BPM at confidence 0.3 -> may really be 140. Misty Lake: 65 at exactly 0.5.
    fast = names(repo, ids, repo.filter_track_ids(bpm_min=130, bpm_max=150))
    assert "Mystery Box" in fast  # 70 * 2 = 140
    slow = names(repo, ids, repo.filter_track_ids(bpm_min=30, bpm_max=40))
    assert "Mystery Box" in slow  # 70 / 2 = 35
    assert "Misty Lake" not in names(repo, ids, repo.filter_track_ids(bpm_min=125, bpm_max=135))
    # A confident tempo is never doubled or halved: Shadow Walk is 90 (confidence 0.9).
    assert "Shadow Walk" not in names(repo, ids, repo.filter_track_ids(bpm_min=170, bpm_max=190))
    assert "Shadow Walk" not in names(repo, ids, repo.filter_track_ids(bpm_min=40, bpm_max=50))
    off = repo.filter_track_ids(bpm_min=130, bpm_max=150, bpm_octave_tolerance=False)
    assert "Mystery Box" not in names(repo, ids, off)


def test_sources(repo: CatalogRepository, ids: dict[str, int]) -> None:
    local = names(repo, ids, repo.filter_track_ids(sources=["local"]))
    assert local == {"Chip Hero", "Local Ambient"}
    both = repo.filter_track_ids(sources=("local", "jamendo"))
    assert both == repo.filter_track_ids()
    assert repo.filter_track_ids(sources=[]) == []
    assert repo.filter_track_ids(sources=["nowhere"]) == []


def test_filters_combine_with_and(repo: CatalogRepository, ids: dict[str, int]) -> None:
    found = repo.filter_track_ids(
        max_risk="green", vocal="instrumental", bpm_max=100, duration_max_s=150
    )
    assert names(repo, ids, found) == {"Shadow Walk", "Quiet Vents", "Unembedded Tune"}


def test_get_tracks_is_one_batch_and_skips_unknown_ids(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    wanted = [ids["Lullaby"], ids["Epic Quest"], 99999]
    got = repo.get_tracks(wanted)
    assert set(got) == {ids["Lullaby"], ids["Epic Quest"]}
    assert got[ids["Epic Quest"]].download_url is not None
    assert repo.get_tracks([]) == {}
    everything = repo.get_tracks(range(1, 2000))  # more ids than one query holds
    assert len(everything) == len(SPECS)


def test_get_features_many_matches_get_features(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    many = repo.get_features_many(ids.values())
    assert ids["Local Ambient"] not in many  # never analysed
    for track_id, features in many.items():
        assert features == repo.get_features(track_id)
    assert repo.get_features_many([]) == {}


def test_get_tag_probs_many(repo: CatalogRepository, ids: dict[str, int]) -> None:
    a, b = ids["Smooth Cafe"], ids["Garage Band"]
    repo.set_tag_probs(a, "genre", "head", "genre-mlp@1", {"jazz": 0.9, "rock": 0.1})
    repo.set_tag_probs(a, "moodtheme", "head", "mood@1", {"calm": 0.7})
    repo.set_tag_probs(b, "genre", "zeroshot", "genre-zs@1", {"rock": 0.8})
    everything = repo.get_tag_probs_many([a, b, ids["Lullaby"]])
    assert set(everything) == {a, b}
    assert everything[a] == repo.get_tag_probs(a)
    genre_only = repo.get_tag_probs_many([a, b], heads=["genre"])
    assert [t.label for t in genre_only[a]] == ["jazz", "rock"]  # probability descending
    assert {t.head for rows in genre_only.values() for t in rows} == {"genre"}
    assert repo.get_tag_probs_many([a], heads=[]) == {}
    assert repo.get_tag_probs_many([]) == {}


def test_tag_prob_moments_count_tracks_and_sum_per_label(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    a, b, c = ids["Smooth Cafe"], ids["Garage Band"], ids["Lullaby"]
    repo.set_tag_probs(a, "genre", "head", "g@1", {"jazz": 0.5, "rock": 0.25})
    repo.set_tag_probs(b, "genre", "head", "g@1", {"jazz": 0.5})
    repo.set_tag_probs(c, "genre", "head", "g@2", {"rock": 1.0})
    repo.set_tag_probs(a, "moodtheme", "head", "m@1", {"calm": 0.75})
    assert repo.tag_prob_moments("genre", "g@1") == (
        2,
        {"jazz": (1.0, 0.5), "rock": (0.25, 0.0625)},
    )
    assert repo.tag_prob_moments("genre", "g@2") == (1, {"rock": (1.0, 1.0)})
    assert repo.tag_prob_moments("genre", "g@3") == (0, {})  # no such version
    everything = repo.tag_prob_moments("genre")  # None: every row, whatever the version
    assert everything == (3, {"jazz": (1.0, 0.5), "rock": (1.25, 1.0625)})
    assert repo.tag_prob_moments("moodtheme") == (1, {"calm": (0.75, 0.5625)})
    assert repo.tag_prob_moments("tempo") == (0, {})


def test_tag_probs_signature_changes_with_the_rows_of_the_head(
    repo: CatalogRepository, ids: dict[str, int]
) -> None:
    a, b = ids["Smooth Cafe"], ids["Garage Band"]
    empty = repo.tag_probs_signature("genre")
    assert empty == (0, None, 0.0)
    repo.set_tag_probs(a, "genre", "head", "g@1", {"jazz": 0.5})
    added = repo.tag_probs_signature("genre")
    assert added != empty and added[0] == 1
    repo.set_tag_probs(a, "genre", "head", "g@1", {"jazz": 0.75})  # replaced, same count
    replaced = repo.tag_probs_signature("genre")
    assert replaced != added and replaced[0] == 1
    repo.set_tag_probs(b, "moodtheme", "head", "m@1", {"calm": 0.75})  # another head
    assert repo.tag_probs_signature("genre") == replaced
    repo.set_tag_probs(b, "genre", "head", "g@1", {"rock": 0.25})  # another track's rows
    assert repo.tag_probs_signature("genre")[0] == 2
    repo.delete_track(b)
    assert repo.tag_probs_signature("genre") == replaced
    repo.delete_track(a)  # cascades to its tag rows
    assert repo.tag_probs_signature("genre") == (0, None, 0.0)


def test_embedding_stats_changes_when_embeddings_change(repo: CatalogRepository) -> None:
    assert repo.embedding_stats(MODEL_ID) == (0, None)
    ids = build_catalog(repo)
    count, latest = repo.embedding_stats(MODEL_ID)
    assert count == len(SPECS) - 1 and latest is not None
    repo.set_embedding(ids["Unembedded Tune"], MODEL_ID, axis("stealth"))
    count2, latest2 = repo.embedding_stats(MODEL_ID)
    assert count2 == count + 1 and latest2 >= latest  # type: ignore[operator]
    repo.set_embedding(ids["Unembedded Tune"], MODEL_ID, axis("calm"))  # replaced in place
    assert repo.embedding_stats(MODEL_ID)[1] != latest2
    assert repo.embedding_stats("other@1") == (0, None)


def test_a_track_with_no_artist_or_features_round_trips(repo: CatalogRepository) -> None:
    track_id = repo.upsert_track(TrackRecord(source="local", source_id="x", risk="green"))
    assert repo.get_tracks([track_id])[track_id].artist is None
    assert repo.filter_track_ids(max_risk="green") == [track_id]
    assert repo.filter_track_ids(bpm_min=1) == []
