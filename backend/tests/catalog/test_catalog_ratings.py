"""Ratings: the v1 to v2 migration and the repository methods."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcrar.catalog import MIGRATIONS, CatalogRepository, TrackRecord, connect, open_path
from mcrar.catalog.db import schema_version


def _tracks(repo: CatalogRepository, n: int = 3) -> list[int]:
    return [
        repo.upsert_track(TrackRecord(source="local", source_id=str(i), title=f"t{i}"))
        for i in range(1, n + 1)
    ]


def test_a_v1_database_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / "old" / "catalog.db"
    conn = connect(path)
    try:
        conn.executescript(f"BEGIN;\n{MIGRATIONS[0]}\nPRAGMA user_version = 1;\nCOMMIT;")
        conn.execute(
            "INSERT INTO tracks (source, source_id, title, created_at, updated_at) "
            "VALUES ('local', 'a', 'Old Track', 't', 't')"
        )
        assert schema_version(conn) == 1
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'ratings'").fetchall()
    finally:
        conn.close()

    assert len(MIGRATIONS) >= 2
    with open_path(path) as repo:
        assert schema_version(repo._conn) == len(MIGRATIONS)
        track = repo.get_track_by_source("local", "a")
        assert track is not None and track.title == "Old Track"  # data intact
        assert repo.iter_ratings() == []
        repo.set_rating("text:x", track.id, 2)
        assert repo.ratings_for("text:x", [track.id]) == {track.id: 2}


def test_set_rating_upserts_and_keeps_created_at(repo: CatalogRepository) -> None:
    t1, _, _ = _tracks(repo)
    first = repo.set_rating("text:a", t1, 1, query_text="A", filters_json='{"vocal":"vocal"}')
    again = repo.set_rating("text:a", t1, 2, query_text="A!", filters_json="{}")
    assert (first.rating, again.rating) == (1, 2)
    assert again.created_at == first.created_at and again.updated_at > first.updated_at
    assert (again.query_text, again.filters_json) == ("A!", "{}")
    assert [r.rating for r in repo.iter_ratings()] == [2]  # one row, not two


def test_the_same_track_has_one_rating_per_query(repo: CatalogRepository) -> None:
    t1, t2, _ = _tracks(repo)
    repo.set_rating("text:a", t1, 2)
    repo.set_rating("text:b", t1, 0)
    repo.set_rating("text:a", t2, 1)
    assert repo.ratings_for("text:a", [t1, t2, 999]) == {t1: 2, t2: 1}
    assert repo.ratings_for("text:b", [t1, t2]) == {t1: 0}
    assert repo.ratings_for("text:c", [t1]) == {}
    assert repo.ratings_for("text:a", []) == {}
    assert [(r.query_key, r.track_id) for r in repo.iter_ratings()] == [
        ("text:a", t1),
        ("text:a", t2),
        ("text:b", t1),
    ]


def test_set_rating_checks_its_arguments(repo: CatalogRepository) -> None:
    (t1, *_) = _tracks(repo)
    with pytest.raises(LookupError):
        repo.set_rating("text:a", t1 + 100, 1)
    for bad in (3, -1, True):
        with pytest.raises(ValueError, match="rating must be"):
            repo.set_rating("text:a", t1, bad)
    with pytest.raises(ValueError, match="query_key"):
        repo.set_rating("", t1, 1)
    assert repo.iter_ratings() == []


def test_delete_rating(repo: CatalogRepository) -> None:
    t1, t2, _ = _tracks(repo)
    repo.set_rating("text:a", t1, 1)
    repo.set_rating("text:a", t2, 1)
    assert repo.delete_rating("text:a", t1) is True
    assert repo.delete_rating("text:a", t1) is False
    assert repo.ratings_for("text:a", [t1, t2]) == {t2: 1}


def test_ratings_go_with_their_track(repo: CatalogRepository) -> None:
    t1, t2, _ = _tracks(repo)
    repo.set_rating("text:a", t1, 1)
    repo.set_rating("text:a", t2, 2)
    assert repo.delete_track(t1) is True
    assert [r.track_id for r in repo.iter_ratings()] == [t2]


def test_rating_queries_count_and_report_the_latest_text_and_filters(
    repo: CatalogRepository,
) -> None:
    t1, t2, t3 = _tracks(repo)
    repo.set_rating("text:a", t1, 1, query_text="A", filters_json="{}")
    repo.set_rating("text:a", t2, 1, query_text="a  ", filters_json='{"vocal":"vocal"}')
    repo.set_rating("filters:x", t3, 0, filters_json='{"vocal":"vocal"}')
    assert repo.rating_queries() == [
        ("filters:x", None, '{"vocal":"vocal"}', 1),
        ("text:a", "a  ", '{"vocal":"vocal"}', 2),  # the most recently changed row wins
    ]


def test_list_ratings_pages_newest_first(repo: CatalogRepository) -> None:
    t1, t2, t3 = _tracks(repo)
    for t in (t1, t2, t3):
        repo.set_rating("text:a", t, 1)
    repo.set_rating("text:a", t1, 2)  # now the newest
    page, total = repo.list_ratings(limit=2, offset=0)
    assert (total, [r.track_id for r in page]) == (3, [t1, t3])
    rest, _ = repo.list_ratings(limit=2, offset=2)
    assert [r.track_id for r in rest] == [t2]
