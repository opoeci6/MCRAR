"""The ``license_set_by_user`` column: the v5 to v6 migration and ``set_track_license``."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcrar.catalog import MIGRATIONS, CatalogRepository, TrackRecord, connect, open_path
from mcrar.catalog.db import schema_version
from mcrar.licensing import parse_license
from mcrar.licensing.model import unknown_license


def test_a_v5_database_upgrades_with_the_flag_off(tmp_path: Path) -> None:
    path = tmp_path / "old" / "catalog.db"
    conn = connect(path)
    try:
        for version in range(5):
            conn.executescript(
                f"BEGIN;\n{MIGRATIONS[version]}\nPRAGMA user_version = {version + 1};\nCOMMIT;"
            )
        conn.execute(
            "INSERT INTO tracks (source, source_id, title, risk, license_code, created_at, "
            "updated_at) VALUES ('local', 'a', 'Old Track', 'green', 'CC0', 't', 't')"
        )
        assert schema_version(conn) == 5
        columns = [r[1] for r in conn.execute("PRAGMA table_info(tracks)")]
        assert "license_set_by_user" not in columns
    finally:
        conn.close()

    assert len(MIGRATIONS) >= 6
    with open_path(path) as repo:
        assert schema_version(repo._conn) == len(MIGRATIONS)
        track = repo.get_track_by_source("local", "a")
        assert track is not None and track.title == "Old Track"  # data intact
        assert track.license_code == "CC0" and track.license_set_by_user is False
        with pytest.raises(Exception, match="CHECK"):
            repo._conn.execute("UPDATE tracks SET license_set_by_user = 2")


def test_upsert_writes_and_reads_the_flag(repo: CatalogRepository) -> None:
    track_id = repo.upsert_track(
        TrackRecord(source="local", source_id="a", title="A", license_set_by_user=True)
    )
    stored = repo.get_track(track_id)
    assert stored is not None and stored.license_set_by_user is True
    repo.upsert_track(TrackRecord(source="local", source_id="a", title="A"))
    stored = repo.get_track(track_id)
    assert stored is not None and stored.license_set_by_user is False  # the record decides


def test_set_track_license_replaces_the_licence_columns(repo: CatalogRepository) -> None:
    track_id = repo.upsert_track(
        TrackRecord(
            source="local",
            source_id="a",
            title="A",
            commercial_license_url="https://shop.example/a",
            local_path="/x/a.wav",
        )
    )
    before = repo.get_track(track_id)
    assert before is not None
    info = parse_license("CC-BY-NC-4.0")
    repo.set_track_license(track_id, info, "A credit line", set_by_user=True)
    after = repo.get_track(track_id)
    assert after is not None
    assert (after.license_code, after.license_url, after.license_family) == (
        info.code,
        info.url,
        "cc-by-nc",
    )
    assert (after.risk, after.commercial_ok, after.derivatives_ok) == ("red", False, True)
    assert (after.share_alike, after.attribution_required) == (False, True)
    assert after.attribution_text == "A credit line" and after.license_set_by_user is True
    assert after.updated_at > before.updated_at and after.created_at == before.created_at
    # what is not the licence stays
    assert after.commercial_license_url == "https://shop.example/a"
    assert after.local_path == "/x/a.wav" and after.title == "A"

    repo.set_track_license(track_id, unknown_license(), "Unknown credit", set_by_user=False)
    again = repo.get_track(track_id)
    assert again is not None and again.license_set_by_user is False
    assert (again.risk, again.commercial_ok, again.license_url) == ("unknown", None, None)


def test_set_track_license_of_an_unknown_track_is_a_lookup_error(repo: CatalogRepository) -> None:
    with pytest.raises(LookupError):
        repo.set_track_license(999, unknown_license(), "x", set_by_user=False)
