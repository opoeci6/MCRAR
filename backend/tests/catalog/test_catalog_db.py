from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mcrar.catalog import MIGRATIONS, connect, migrate, open_catalog, open_path, schema_version
from mcrar.config import get_settings

EXPECTED_TABLES = {
    "tracks",
    "features",
    "tag_probs",
    "embeddings",
    "ingest_log",
    "projects",
    "shortlist_items",
    "ratings",
}


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows} - {"sqlite_sequence"}


def test_connect_creates_parent_and_sets_pragmas(tmp_path: Path) -> None:
    conn = connect(tmp_path / "a" / "b" / "catalog.db")
    try:
        assert (tmp_path / "a" / "b").is_dir()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_migrate_is_idempotent_and_sets_user_version(tmp_path: Path) -> None:
    conn = connect(tmp_path / "catalog.db")
    try:
        assert schema_version(conn) == 0
        assert migrate(conn) == len(MIGRATIONS)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert _tables(conn) == EXPECTED_TABLES
        conn.execute("INSERT INTO projects (name, created_at) VALUES ('p', 't')")
        assert migrate(conn) == len(MIGRATIONS)
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    finally:
        conn.close()


def test_migrate_rejects_newer_schema(tmp_path: Path) -> None:
    conn = connect(tmp_path / "catalog.db")
    try:
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
        with pytest.raises(RuntimeError, match="newer"):
            migrate(conn)
    finally:
        conn.close()


def test_failed_migration_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mcrar.catalog import db

    conn = connect(tmp_path / "catalog.db")
    try:
        monkeypatch.setattr(db, "MIGRATIONS", (*MIGRATIONS, "CREATE TABLE x (a); BOGUS SQL;"))
        migrate_target = len(MIGRATIONS) + 1
        with pytest.raises(sqlite3.Error):
            db.migrate(conn)
        assert not conn.in_transaction
        assert schema_version(conn) == migrate_target - 1
        assert "x" not in _tables(conn)
    finally:
        conn.close()


def test_reopen_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "catalog.db"
    with open_path(path) as repo:
        pid = repo.create_project("keep")
    with open_path(path) as repo:
        assert [p.id for p in repo.list_projects()] == [pid]


def test_open_catalog_uses_settings_data_dir(tmp_path: Path) -> None:
    settings = get_settings(data_dir=tmp_path / "d")
    with open_catalog(settings):
        pass
    assert (tmp_path / "d" / "catalog.db").is_file()
