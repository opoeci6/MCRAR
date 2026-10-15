"""Projects and shortlists: lookup, rename, delete cascade and shortlist entries."""

from __future__ import annotations

import pytest

from mcrar.catalog import CatalogRepository, TrackRecord


def _tracks(repo: CatalogRepository, n: int = 3) -> list[int]:
    return [
        repo.upsert_track(TrackRecord(source="local", source_id=str(i), title=f"t{i}"))
        for i in range(1, n + 1)
    ]


def test_get_project(repo: CatalogRepository) -> None:
    pid = repo.create_project("Platformer")
    project = repo.get_project(pid)
    assert project is not None and (project.id, project.name) == (pid, "Platformer")
    assert repo.get_project(pid + 1) is None


def test_rename_project(repo: CatalogRepository) -> None:
    a = repo.create_project("A")
    repo.create_project("B")
    repo.rename_project(a, "A2")
    assert [p.name for p in repo.list_projects()] == ["A2", "B"]
    repo.rename_project(a, "A2")  # the same name is not a duplicate of itself
    with pytest.raises(ValueError, match="already exists"):
        repo.rename_project(a, "B")
    with pytest.raises(ValueError, match="non-empty"):
        repo.rename_project(a, "  ")
    with pytest.raises(LookupError):
        repo.rename_project(a + 100, "C")
    renamed = repo.get_project(a)
    assert renamed is not None and renamed.name == "A2"


def test_delete_project_cascades_the_shortlist_only(repo: CatalogRepository) -> None:
    t1, t2, _ = _tracks(repo)
    a, b = repo.create_project("A"), repo.create_project("B")
    repo.add_to_shortlist(a, t1)
    repo.add_to_shortlist(a, t2)
    repo.add_to_shortlist(b, t1)
    assert repo.delete_project(a) is True
    assert repo.delete_project(a) is False
    assert repo.get_project(a) is None
    assert [t.id for t in repo.shortlist(b)] == [t1]
    assert repo.get_track(t1) is not None and repo.get_track(t2) is not None
    with pytest.raises(LookupError):
        repo.shortlist_entries(a)


def test_shortlist_entries_carry_note_and_time_in_order(repo: CatalogRepository) -> None:
    t1, t2, t3 = _tracks(repo)
    pid = repo.create_project("p")
    repo.add_to_shortlist(pid, t3, note="last id, first added")
    repo.add_to_shortlist(pid, t1)
    repo.add_to_shortlist(pid, t2, note="boss")
    repo.add_to_shortlist(pid, t2, note="boss v2")  # a note update keeps the original added_at
    entries = repo.shortlist_entries(pid)
    assert [e.track.id for e in entries] == [t3, t1, t2]
    assert [e.note for e in entries] == ["last id, first added", None, "boss v2"]
    assert entries[0].added_at < entries[1].added_at < entries[2].added_at
    assert [t.id for t in repo.shortlist(pid)] == [t3, t1, t2]


def test_shortlist_entries_tie_on_added_at_is_ordered_by_track_id(
    repo: CatalogRepository,
) -> None:
    t1, t2, _ = _tracks(repo)
    pid = repo.create_project("p")
    repo.add_to_shortlist(pid, t2)
    repo.add_to_shortlist(pid, t1)
    repo._conn.execute("UPDATE shortlist_items SET added_at = 'same'")
    assert [e.track.id for e in repo.shortlist_entries(pid)] == [t1, t2]


def test_shortlist_entries_empty_and_unknown(repo: CatalogRepository) -> None:
    pid = repo.create_project("p")
    assert repo.shortlist_entries(pid) == []
    with pytest.raises(LookupError):
        repo.shortlist_entries(pid + 1)


def test_shortlist_counts(repo: CatalogRepository) -> None:
    t1, t2, _ = _tracks(repo)
    a, b, c = (repo.create_project(n) for n in "abc")
    repo.add_to_shortlist(a, t1)
    repo.add_to_shortlist(a, t2)
    repo.add_to_shortlist(b, t1)
    assert repo.shortlist_counts() == {a: 2, b: 1}
    assert c not in repo.shortlist_counts()
