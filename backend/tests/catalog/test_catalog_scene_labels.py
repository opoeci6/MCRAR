"""Scene labels and the labelling pool: the v4 to v5 migration and the repository methods."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcrar.catalog import (
    MIGRATIONS,
    CatalogRepository,
    PoolEntry,
    TrackRecord,
    connect,
    open_path,
)
from mcrar.catalog.db import schema_version


def _tracks(repo: CatalogRepository, n: int = 6) -> list[int]:
    return [
        repo.upsert_track(TrackRecord(source="jamendo", source_id=str(i), title=f"t{i}"))
        for i in range(1, n + 1)
    ]


def test_a_v4_database_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / "old" / "catalog.db"
    conn = connect(path)
    try:
        for version in range(4):
            conn.executescript(
                f"BEGIN;\n{MIGRATIONS[version]}\nPRAGMA user_version = {version + 1};\nCOMMIT;"
            )
        conn.execute(
            "INSERT INTO tracks (source, source_id, title, created_at, updated_at) "
            "VALUES ('local', 'a', 'Old Track', 't', 't')"
        )
        assert schema_version(conn) == 4
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'scene_labels'"
        ).fetchall()
    finally:
        conn.close()

    assert len(MIGRATIONS) >= 5
    with open_path(path) as repo:
        assert schema_version(repo._conn) == len(MIGRATIONS)
        track = repo.get_track_by_source("local", "a")
        assert track is not None and track.title == "Old Track"  # data intact
        assert repo.iter_scene_labels() == [] and repo.label_pool() == []
        label = repo.set_scene_label(track.id, "me", ["combat"], "high", "labelled")
        assert label.scenes == ("combat",) and label.intensity == "high"


def test_set_scene_label_upserts_and_keeps_created_at(repo: CatalogRepository) -> None:
    t1, t2 = _tracks(repo, 2)
    first = repo.set_scene_label(t1, "  Ana ", ["combat", "boss", "combat"], "high", "labelled")
    assert first.labeller == "Ana" and first.scenes == ("combat", "boss")  # trimmed, deduplicated
    again = repo.set_scene_label(t1, "Ana", [], None, "labelled")  # "no scene fits"
    assert again.scenes == () and again.status == "labelled" and again.intensity is None
    assert again.created_at == first.created_at and again.updated_at > first.updated_at
    assert repo.get_scene_label(t1, "Ana") == again
    assert repo.get_scene_label(t1, "Ben") is None and repo.get_scene_label(t2, "Ana") is None
    # another labeller's label of the same track is independent
    repo.set_scene_label(t1, "Ben", ["horror"], "low", "labelled")
    assert [(x.labeller, x.scenes) for x in repo.iter_scene_labels()] == [
        ("Ana", ()),
        ("Ben", ("horror",)),
    ]
    assert [x.labeller for x in repo.iter_scene_labels("Ben")] == ["Ben"]
    assert repo.labellers() == ["Ana", "Ben"]


def test_a_skipped_label_keeps_no_scenes_or_intensity(repo: CatalogRepository) -> None:
    (t1,) = _tracks(repo, 1)
    label = repo.set_scene_label(t1, "Ana", ["combat"], "high", "skipped")
    assert (label.status, label.scenes, label.intensity) == ("skipped", (), None)


def test_set_scene_label_checks_its_arguments(repo: CatalogRepository) -> None:
    (t1,) = _tracks(repo, 1)
    for labeller in ("", "   ", "x" * 41, "bad\x00name", "tab\tname", 5):
        with pytest.raises(ValueError, match="labeller"):
            repo.set_scene_label(t1, labeller, [], None, "labelled")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="intensity"):
        repo.set_scene_label(t1, "a", [], "loud", "labelled")
    with pytest.raises(ValueError, match="status"):
        repo.set_scene_label(t1, "a", [], None, "done")
    with pytest.raises(LookupError, match="no track with id 999"):
        repo.set_scene_label(999, "a", [], None, "labelled")
    assert repo.iter_scene_labels() == []


def test_merge_keeps_the_newer_label(repo: CatalogRepository) -> None:
    (t1,) = _tracks(repo, 1)
    assert repo.merge_scene_label(t1, "Ana", ["combat"], "low", "labelled", "2026-03-01T10:00:00Z")
    stored = repo.get_scene_label(t1, "Ana")
    assert stored is not None and stored.updated_at.startswith("2026-03-01T10:00:00")
    # older and equal imports lose, a newer one wins and keeps created_at
    assert not repo.merge_scene_label(t1, "Ana", ["boss"], None, "labelled", "2026-02-01T10:00:00Z")
    assert not repo.merge_scene_label(t1, "Ana", ["boss"], None, "labelled", "2026-03-01T10:00:00Z")
    assert repo.merge_scene_label(
        t1, "Ana", ["boss"], "mid", "labelled", "2026-04-01T09:00:00+00:00"
    )
    after = repo.get_scene_label(t1, "Ana")
    assert after is not None and after.scenes == ("boss",) and after.intensity == "mid"
    assert after.created_at == stored.created_at and after.updated_at.startswith("2026-04-01T09")
    # a time without an offset is UTC; an offset is converted
    assert not repo.merge_scene_label(t1, "Ana", [], None, "skipped", "2026-04-01T10:00:00+02:00")
    with pytest.raises(ValueError):
        repo.merge_scene_label(t1, "Ana", [], None, "skipped", "yesterday")


def test_delete_scene_label_and_cascade(repo: CatalogRepository) -> None:
    t1, t2 = _tracks(repo, 2)
    repo.set_scene_label(t1, "Ana", ["boss"], None, "labelled")
    repo.set_scene_label(t2, "Ana", ["boss"], None, "labelled")
    assert repo.delete_scene_label(t1, "Ana") is True
    assert repo.delete_scene_label(t1, "Ana") is False
    repo.replace_label_pool([PoolEntry(t2, 1, "random", "A")])
    assert repo.delete_track(t2)  # rows go with their track
    assert repo.iter_scene_labels() == [] and repo.label_pool() == []


def test_replace_label_pool_orders_filters_and_validates(repo: CatalogRepository) -> None:
    ids = _tracks(repo, 5)
    pool = [
        PoolEntry(ids[0], 3, "top:boss:v", "A"),
        PoolEntry(ids[1], 1, "random", "both"),
        PoolEntry(ids[2], 2, "random", "B"),
        PoolEntry(ids[3], 5, "random", "A"),
        PoolEntry(ids[4], 4, "random", "both"),
    ]
    assert repo.replace_label_pool(pool) == 5
    assert [e.position for e in repo.label_pool()] == [1, 2, 3, 4, 5]
    assert [e.part for e in repo.label_pool("A")] == ["both", "A", "both", "A"]  # A + both
    assert [e.part for e in repo.label_pool("B")] == ["both", "B", "both"]
    assert [e.position for e in repo.label_pool("all")] == [1, 2, 3, 4, 5]
    assert [e.position for e in repo.label_pool("both")] == [1, 4]
    with pytest.raises(ValueError, match="part"):
        repo.label_pool("C")
    # replacing is all or nothing
    with pytest.raises(ValueError, match="part"):
        repo.replace_label_pool([PoolEntry(ids[0], 1, "r", "Z")])
    with pytest.raises(LookupError):
        repo.replace_label_pool([PoolEntry(999, 1, "r", "A")])
    assert len(repo.label_pool()) == 5
    assert repo.replace_label_pool([PoolEntry(ids[0], 1, "random", "B")]) == 1
    assert [e.track_id for e in repo.label_pool()] == [ids[0]]


def test_next_pool_track_follows_the_order_and_the_part(repo: CatalogRepository) -> None:
    ids = _tracks(repo, 6)
    parts = ["A", "B", "both", "A", "B", "both"]
    repo.replace_label_pool(
        [PoolEntry(t, i + 1, "random", p) for i, (t, p) in enumerate(zip(ids, parts, strict=True))]
    )

    def next_positions(labeller: str, part: str, after: int | None = None) -> int | None:
        entry = repo.next_pool_track(labeller, part, after)
        return entry.position if entry else None

    assert next_positions("Ana", "all") == 1
    assert next_positions("Ana", "A") == 1
    assert next_positions("Ana", "B") == 2
    assert next_positions("Ana", "all", after=1) == 2
    assert next_positions("Ana", "A", after=1) == 3  # A skips part B's tracks, includes both
    assert next_positions("Ana", "B", after=2) == 3
    assert next_positions("Ana", "A", after=6) is None

    repo.set_scene_label(ids[0], "Ana", ["combat"], None, "labelled")  # position 1
    repo.set_scene_label(ids[2], "Ana", [], None, "skipped")  # position 3: skipped counts as done
    assert next_positions("Ana", "A") == 4
    assert next_positions("Ana", "B") == 2
    assert next_positions("Ana", "B", after=2) == 5
    assert next_positions("Ben", "A") == 1  # another labeller starts from the top
    assert next_positions("Ana", "all", after=3) == 4
    for track in ids:
        repo.set_scene_label(track, "Ana", [], None, "labelled")
    assert next_positions("Ana", "all") is None


def test_label_progress_counts_per_part_for_pool_tracks_only(repo: CatalogRepository) -> None:
    ids = _tracks(repo, 6)
    parts = ["A", "A", "B", "both", "both", "A"]
    repo.replace_label_pool(
        [
            PoolEntry(t, i + 1, "random", p)
            for i, (t, p) in enumerate(zip(ids[:5], parts, strict=False))
        ]
    )
    assert repo.label_progress("Ana") == {
        "A": {"total": 2, "labelled": 0, "skipped": 0},
        "B": {"total": 1, "labelled": 0, "skipped": 0},
        "both": {"total": 2, "labelled": 0, "skipped": 0},
    }
    repo.set_scene_label(ids[0], "Ana", ["boss"], None, "labelled")
    repo.set_scene_label(ids[1], "Ana", [], None, "skipped")
    repo.set_scene_label(ids[3], "Ana", [], None, "labelled")
    repo.set_scene_label(ids[3], "Ben", [], None, "labelled")
    repo.set_scene_label(ids[5], "Ana", [], None, "labelled")  # not in the pool: not counted
    progress = repo.label_progress("Ana")
    assert progress["A"] == {"total": 2, "labelled": 1, "skipped": 1}
    assert progress["B"] == {"total": 1, "labelled": 0, "skipped": 0}
    assert progress["both"] == {"total": 2, "labelled": 1, "skipped": 0}
    assert repo.label_progress("Ben")["both"]["labelled"] == 1
