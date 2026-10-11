from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mcrar.audio.analyze import ANALYSIS_VERSION, AudioFeatures
from mcrar.catalog import CatalogRepository, StoredTrack, TrackRecord, open_path


def _rec(source_id: str = "1", source: str = "jamendo", **kw: Any) -> TrackRecord:
    return TrackRecord(source=source, source_id=source_id, **kw)


def _features(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = AudioFeatures(
        bpm=120.0,
        bpm_raw=60.0,
        bpm_confidence=0.8,
        key="C",
        mode="major",
        key_confidence=0.7,
        loudness_lufs=-14.2,
        rms_db=-18.0,
        energy=0.5,
        duration_s=180.0,
        sample_rate=44100,
        channels=2,
    ).to_dict()
    base.update(kw)
    return base


# -- tracks ---------------------------------------------------------------------------------


def test_upsert_insert_then_update_keeps_created_at(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec("7", title="old"))
    first = repo.get_track(tid)
    assert first is not None
    assert first.title == "old"
    assert first.created_at == first.updated_at

    tid2 = repo.upsert_track(_rec("7", title="new", artist="A"))
    assert tid2 == tid
    second = repo.get_track(tid)
    assert second is not None
    assert (second.title, second.artist) == ("new", "A")
    assert second.created_at == first.created_at
    assert second.updated_at > first.updated_at
    assert len(list(repo.iter_tracks())) == 1


def test_upsert_overwrites_with_none(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec("1", album="x"))
    repo.upsert_track(_rec("1"))
    track = repo.get_track(tid)
    assert track is not None
    assert track.album is None


def test_same_source_id_in_different_sources_are_distinct(repo: CatalogRepository) -> None:
    a = repo.upsert_track(_rec("1", source="jamendo"))
    b = repo.upsert_track(_rec("1", source="local"))
    assert a != b
    assert repo.get_track_by_source("local", "1") == repo.get_track(b)
    assert repo.get_track_by_source("jamendo", "nope") is None
    assert repo.get_track(9999) is None


def test_timestamps_are_iso_utc(repo: CatalogRepository) -> None:
    track = repo.get_track(repo.upsert_track(_rec()))
    assert track is not None
    assert track.created_at.endswith("+00:00")
    assert track.created_at.startswith("2026-01-01T")


def test_full_round_trip_of_every_column(repo: CatalogRepository) -> None:
    rec = TrackRecord(
        source="jamendo",
        source_id="123",
        title="群青",
        artist="YOASOBI ♪",
        album="THE BOOK",
        duration_s=257.5,
        release_date="2020-10-01",
        source_url="https://example.test/track/123",
        stream_url="https://example.test/stream/123",
        download_url="https://example.test/dl/123",
        audiodownload_allowed=True,
        image_url="https://example.test/i.jpg",
        local_path=None,
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_code="CC-BY-4.0",
        license_family="cc-by",
        risk="green",
        commercial_ok=True,
        derivatives_ok=False,
        share_alike=False,
        attribution_required=True,
        attribution_text='"群青" by YOASOBI',
        commercial_license_url="https://example.test/license",
        vocal_instrumental="vocal",
        source_tags={"genres": ["pop", "ロック"], "speed": "high", "n": 3, "x": None},
    )
    tid = repo.upsert_track(rec)
    got = repo.get_track(tid)
    assert isinstance(got, StoredTrack)
    assert got.id == tid
    for name in rec.__dataclass_fields__:
        assert getattr(got, name) == getattr(rec, name), name
    assert got.audiodownload_allowed is True
    assert got.derivatives_ok is False


def test_bool_columns_map_none_true_false(repo: CatalogRepository) -> None:
    names = [
        "audiodownload_allowed",
        "commercial_ok",
        "derivatives_ok",
        "share_alike",
        "attribution_required",
    ]
    for i, value in enumerate([None, True, False]):
        tid = repo.upsert_track(_rec(str(i), **dict.fromkeys(names, value)))
        track = repo.get_track(tid)
        assert track is not None
        for name in names:
            assert getattr(track, name) is value, (name, value)


def test_local_track_and_defaults(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec("f1", source="local", local_path="C:/music/a.wav"))
    track = repo.get_track(tid)
    assert track is not None
    assert track.local_path == "C:/music/a.wav"
    assert track.risk == "unknown"
    assert track.source_tags is None


@pytest.mark.parametrize(
    "kw",
    [{"risk": "purple"}, {"vocal_instrumental": "both"}, {"source": ""}],
)
def test_invalid_track_values_raise_value_error(repo: CatalogRepository, kw: dict) -> None:
    with pytest.raises(ValueError):
        repo.upsert_track(_rec("1", **kw))


def test_iter_tracks_filters_by_source_and_orders_by_id(repo: CatalogRepository) -> None:
    ids = [
        repo.upsert_track(_rec("b", source="jamendo")),
        repo.upsert_track(_rec("a", source="local")),
        repo.upsert_track(_rec("c", source="jamendo")),
    ]
    assert [t.id for t in repo.iter_tracks()] == ids
    assert [t.id for t in repo.iter_tracks("jamendo")] == [ids[0], ids[2]]
    assert list(repo.iter_tracks("freesound")) == []


# -- features -------------------------------------------------------------------------------


def test_features_round_trip_and_version(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    assert repo.get_features(tid) is None
    assert repo.features_version(tid) is None

    feats = _features()
    repo.set_features(tid, feats)
    got = repo.get_features(tid)
    assert got is not None
    for name, value in feats.items():
        if name == "duration_s":
            assert name not in got
        else:
            assert got[name] == value, name
    assert got["analyzed_at"].startswith("2026-")
    assert repo.features_version(tid) == ANALYSIS_VERSION


def test_features_upsert_replaces_and_accepts_nulls(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    repo.set_features(tid, _features())
    repo.set_features(
        tid,
        _features(bpm=None, bpm_raw=None, key=None, mode=None, loudness_lufs=None)
        | {"analysis_version": "audio-v2"},
    )
    got = repo.get_features(tid)
    assert got is not None
    assert got["bpm"] is None
    assert got["key"] is None
    assert got["analysis_version"] == "audio-v2"
    assert repo.features_version(tid) == "audio-v2"


def test_features_validation(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    with pytest.raises(ValueError, match="unknown"):
        repo.set_features(tid, {**_features(), "bogus": 1})
    with pytest.raises(ValueError, match="analysis_version"):
        repo.set_features(tid, {"bpm": 100.0})
    with pytest.raises(LookupError):
        repo.set_features(tid + 100, _features())


# -- tag probs ------------------------------------------------------------------------------


def test_tag_probs_replace_only_the_given_head(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    repo.set_tag_probs(tid, "mood", "zeroshot", "clap-1", {"happy": 0.9, "sad": 0.1, "calm": 0.4})
    repo.set_tag_probs(tid, "genre", "head", "g-1", {"rock": 0.7})
    assert [(t.label, t.prob) for t in repo.get_tag_probs(tid, "mood")] == [
        ("happy", 0.9),
        ("calm", 0.4),
        ("sad", 0.1),
    ]

    repo.set_tag_probs(tid, "mood", "head", "m-2", {"epic": 0.5})
    mood = repo.get_tag_probs(tid, "mood")
    assert [(t.label, t.method, t.model_version) for t in mood] == [("epic", "head", "m-2")]
    assert [t.head for t in repo.get_tag_probs(tid)] == ["genre", "mood"]

    repo.set_tag_probs(tid, "mood", "head", "m-2", {})
    assert repo.get_tag_probs(tid, "mood") == []
    assert len(repo.get_tag_probs(tid)) == 1


def test_tag_probs_validation(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    with pytest.raises(ValueError, match="method"):
        repo.set_tag_probs(tid, "mood", "guess", None, {"a": 0.5})
    with pytest.raises(ValueError):
        repo.set_tag_probs(tid, "mood", "head", None, {"a": 1.5})
    with pytest.raises(ValueError):
        repo.set_tag_probs(tid, "mood", "head", None, {"a": float("nan")})
    with pytest.raises(LookupError):
        repo.set_tag_probs(tid + 1, "mood", "head", None, {"a": 0.5})


def test_invalid_tag_write_keeps_previous_rows(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    repo.set_tag_probs(tid, "mood", "head", "v1", {"a": 0.5})
    with pytest.raises(ValueError):
        repo.set_tag_probs(tid, "mood", "head", "v2", {"b": 0.2, "c": 7.0})
    assert [t.label for t in repo.get_tag_probs(tid, "mood")] == ["a"]


# -- embeddings -----------------------------------------------------------------------------


def test_embedding_round_trip_dtype(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    assert repo.get_embedding(tid, "m") is None
    repo.set_embedding(tid, "m", [0.25, -1.5, 3.0])
    got = repo.get_embedding(tid, "m")
    assert got is not None
    assert got.dtype == np.float32
    assert got.tolist() == [0.25, -1.5, 3.0]
    repo.set_embedding(tid, "m", np.array([1, 2, 3], dtype=np.float64))
    again = repo.get_embedding(tid, "m")
    assert again is not None
    assert again.tolist() == [1.0, 2.0, 3.0]


def test_embedding_dim_mismatch_and_per_model_dims(repo: CatalogRepository) -> None:
    a = repo.upsert_track(_rec("a"))
    b = repo.upsert_track(_rec("b"))
    repo.set_embedding(a, "m", np.ones(4))
    with pytest.raises(ValueError, match="dim"):
        repo.set_embedding(b, "m", np.ones(5))
    with pytest.raises(ValueError, match="dim"):
        repo.set_embedding(a, "m", np.ones(5))
    repo.set_embedding(b, "other", np.ones(5))  # different model, different dim is fine
    assert repo.get_embedding(b, "m") is None


@pytest.mark.parametrize(
    "bad",
    [[1.0, float("nan")], [float("inf"), 1.0], [-np.inf, 0.0], np.ones((2, 2)), [], 3.0],
)
def test_embedding_rejects_bad_vectors(repo: CatalogRepository, bad: object) -> None:
    tid = repo.upsert_track(_rec())
    with pytest.raises(ValueError):
        repo.set_embedding(tid, "m", bad)
    assert repo.get_embedding(tid, "m") is None


def test_embedding_for_missing_track_raises_lookup_error(repo: CatalogRepository) -> None:
    with pytest.raises(LookupError):
        repo.set_embedding(42, "m", np.ones(3))


def test_load_embeddings_order_and_dtype(repo: CatalogRepository) -> None:
    ids = [repo.upsert_track(_rec(str(i))) for i in range(4)]
    for tid in (ids[2], ids[0], ids[3]):  # insertion order differs from id order
        repo.set_embedding(tid, "m", np.full(3, float(tid)))
    repo.set_embedding(ids[1], "other", np.ones(2))
    out_ids, matrix = repo.load_embeddings("m")
    assert out_ids.dtype == np.int64
    assert matrix.dtype == np.float32
    assert out_ids.tolist() == [ids[0], ids[2], ids[3]]
    assert matrix.shape == (3, 3)
    assert matrix[:, 0].tolist() == [float(ids[0]), float(ids[2]), float(ids[3])]


def test_load_embeddings_empty(repo: CatalogRepository) -> None:
    ids, matrix = repo.load_embeddings("nothing")
    assert ids.dtype == np.int64
    assert matrix.dtype == np.float32
    assert ids.shape == (0,)
    assert matrix.shape[0] == 0


# -- ingest log -----------------------------------------------------------------------------


def test_ingest_attempts_increment_and_status_updates(repo: CatalogRepository) -> None:
    assert repo.get_ingest_status("jamendo", "1", "fetch") is None
    repo.log_ingest("jamendo", "1", "fetch", "failed", "HTTP 503")
    first = repo.get_ingest_status("jamendo", "1", "fetch")
    assert first is not None
    assert (first.status, first.message, first.attempts) == ("failed", "HTTP 503", 1)

    repo.log_ingest("jamendo", "1", "fetch", "failed", "HTTP 503")
    repo.log_ingest("jamendo", "1", "fetch", "ok")
    last = repo.get_ingest_status("jamendo", "1", "fetch")
    assert last is not None
    assert (last.status, last.message, last.attempts) == ("ok", None, 3)
    assert last.updated_at > first.updated_at
    assert repo.failed_items() == []


def test_ingest_failure_without_track_then_link_track(repo: CatalogRepository) -> None:
    repo.log_ingest("jamendo", "9", "metadata", "failed", "bad json")
    entry = repo.get_ingest_status("jamendo", "9", "metadata")
    assert entry is not None
    assert entry.track_id is None

    tid = repo.upsert_track(_rec("9"))
    repo.log_ingest("jamendo", "9", "metadata", "ok", track_id=tid)
    entry = repo.get_ingest_status("jamendo", "9", "metadata")
    assert entry is not None
    assert entry.track_id == tid
    repo.log_ingest("jamendo", "9", "metadata", "skipped")  # keeps the link
    entry = repo.get_ingest_status("jamendo", "9", "metadata")
    assert entry is not None
    assert (entry.track_id, entry.attempts) == (tid, 3)


def test_failed_items_filters_by_stage(repo: CatalogRepository) -> None:
    repo.log_ingest("jamendo", "1", "download", "failed", "timeout")
    repo.log_ingest("jamendo", "2", "analyze", "failed", "decode")
    repo.log_ingest("jamendo", "3", "analyze", "ok")
    repo.log_ingest("local", "4", "analyze", "skipped")
    assert {(f.source_id, f.stage) for f in repo.failed_items()} == {
        ("1", "download"),
        ("2", "analyze"),
    }
    assert [f.source_id for f in repo.failed_items("analyze")] == ["2"]
    assert repo.failed_items("embed") == []


def test_ingest_validation_and_message_truncation(repo: CatalogRepository) -> None:
    with pytest.raises(ValueError, match="status"):
        repo.log_ingest("jamendo", "1", "fetch", "weird")
    with pytest.raises(LookupError):
        repo.log_ingest("jamendo", "1", "fetch", "ok", track_id=123)
    repo.log_ingest("jamendo", "1", "fetch", "failed", "x" * 5000)
    entry = repo.get_ingest_status("jamendo", "1", "fetch")
    assert entry is not None
    assert entry.message is not None
    assert len(entry.message) <= 500


# -- delete / cascade -----------------------------------------------------------------------


def test_delete_track_cascades(repo: CatalogRepository) -> None:
    keep = repo.upsert_track(_rec("keep"))
    gone = repo.upsert_track(_rec("gone"))
    project = repo.create_project("game")
    for tid in (keep, gone):
        repo.set_features(tid, _features())
        repo.set_tag_probs(tid, "mood", "head", "v", {"a": 0.5})
        repo.set_embedding(tid, "m", np.ones(3))
        repo.add_to_shortlist(project, tid)
    repo.log_ingest("jamendo", "gone", "analyze", "ok", track_id=gone)

    assert repo.delete_track(gone) is True
    assert repo.delete_track(gone) is False
    assert repo.get_track(gone) is None
    assert repo.get_features(gone) is None
    assert repo.get_tag_probs(gone) == []
    assert repo.get_embedding(gone, "m") is None
    assert [t.id for t in repo.shortlist(project)] == [keep]
    assert repo.get_ingest_status("jamendo", "gone", "analyze") is None
    # the other track is untouched
    assert repo.get_features(keep) is not None
    assert len(repo.get_tag_probs(keep)) == 1
    assert repo.get_embedding(keep, "m") is not None


# -- stats ----------------------------------------------------------------------------------


def test_stats_empty(repo: CatalogRepository) -> None:
    assert repo.stats() == {
        "tracks": 0,
        "tracks_by_source": {},
        "tracks_by_risk": {},
        "features": {"tracks_with_features": 0, "coverage": 0.0},
        "embeddings_by_model": {},
        "ingest_failures_by_stage": {},
    }


def test_stats_counts(repo: CatalogRepository) -> None:
    a = repo.upsert_track(_rec("a", risk="green"))
    b = repo.upsert_track(_rec("b", risk="green"))
    c = repo.upsert_track(_rec("c", source="local", risk="red"))
    repo.upsert_track(_rec("d"))
    repo.set_features(a, _features())
    repo.set_features(c, _features())
    repo.set_embedding(a, "m1", np.ones(2))
    repo.set_embedding(b, "m1", np.ones(2))
    repo.set_embedding(a, "m2", np.ones(3))
    repo.log_ingest("jamendo", "x", "download", "failed", "boom")
    repo.log_ingest("jamendo", "y", "download", "failed", "boom")
    repo.log_ingest("jamendo", "z", "analyze", "failed", "boom")
    repo.log_ingest("jamendo", "w", "analyze", "ok")

    assert repo.stats() == {
        "tracks": 4,
        "tracks_by_source": {"jamendo": 3, "local": 1},
        "tracks_by_risk": {"green": 2, "red": 1, "unknown": 1},
        "features": {"tracks_with_features": 2, "coverage": 0.5},
        "embeddings_by_model": {"m1": 2, "m2": 1},
        "ingest_failures_by_stage": {"download": 2, "analyze": 1},
    }


# -- projects / shortlist -------------------------------------------------------------------


def test_projects_and_shortlist(repo: CatalogRepository) -> None:
    t1 = repo.upsert_track(_rec("1", title="one"))
    t2 = repo.upsert_track(_rec("2", title="two"))
    p1 = repo.create_project("Platformer")
    p2 = repo.create_project("Racing")
    assert [(p.id, p.name) for p in repo.list_projects()] == [(p1, "Platformer"), (p2, "Racing")]
    with pytest.raises(ValueError, match="exists"):
        repo.create_project("Racing")
    with pytest.raises(ValueError):
        repo.create_project("  ")

    repo.add_to_shortlist(p1, t2, note="boss theme")
    repo.add_to_shortlist(p1, t1)
    repo.add_to_shortlist(p1, t2, note="boss theme v2")  # idempotent
    repo.add_to_shortlist(p2, t1)
    assert [t.title for t in repo.shortlist(p1)] == ["two", "one"]
    assert [t.id for t in repo.shortlist(p2)] == [t1]

    assert repo.remove_from_shortlist(p1, t2) is True
    assert repo.remove_from_shortlist(p1, t2) is False
    assert [t.id for t in repo.shortlist(p1)] == [t1]
    assert repo.shortlist(9999) == []


def test_shortlist_unknown_ids_raise_lookup_error(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    pid = repo.create_project("p")
    with pytest.raises(LookupError):
        repo.add_to_shortlist(pid + 1, tid)
    with pytest.raises(LookupError):
        repo.add_to_shortlist(pid, tid + 1)


def test_deleting_project_cascades_shortlist_not_tracks(repo: CatalogRepository) -> None:
    tid = repo.upsert_track(_rec())
    pid = repo.create_project("p")
    repo.add_to_shortlist(pid, tid)
    repo._conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
    assert repo.shortlist(pid) == []
    assert repo.get_track(tid) is not None


def test_context_manager_closes(tmp_path: Path) -> None:
    with open_path(tmp_path / "c.db") as repo:
        repo.create_project("p")
    with pytest.raises(Exception):  # noqa: B017 - operating on a closed sqlite connection
        repo.list_projects()
