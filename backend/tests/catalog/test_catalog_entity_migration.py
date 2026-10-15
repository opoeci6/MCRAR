"""Migration v3: HTML entities in stored track names are decoded once."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mcrar.catalog import MIGRATIONS, connect, open_path
from mcrar.catalog.db import schema_version

_ROWS = [
    ("1", "Jazyus &amp; EdSeGaMe", "Rock &amp; Roll", "Tom &amp; Jerry&#39;s"),
    ("2", "Say &quot;hi&quot;", "A &lt;b&gt; C", "It&apos;s&#039;s"),
    ("3", "&amp;lt;tag&amp;gt;", "&amp;amp;", None),
    ("4", "Plain Title", "Plain Artist", "Plain Album"),
    ("5", "Fish & Chips", "R&B Crew", "AT&T"),  # already decoded: untouched
    ("6", "Only title &amp; more", None, None),
]


def _name_columns(conn: sqlite3.Connection, source_id: str) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT title, artist, album FROM tracks WHERE source_id = ?", (source_id,)
    ).fetchone()
    return tuple(row)


def test_a_v2_database_gets_its_names_decoded(tmp_path: Path) -> None:
    path = tmp_path / "old" / "catalog.db"
    conn = connect(path)
    try:
        conn.executescript(
            f"BEGIN;\n{MIGRATIONS[0]}\n{MIGRATIONS[1]}\nPRAGMA user_version = 2;\nCOMMIT;"
        )
        for source_id, title, artist, album in _ROWS:
            conn.execute(
                "INSERT INTO tracks "
                "(source, source_id, title, artist, album, created_at, updated_at)"
                " VALUES ('jamendo', ?, ?, ?, ?, 'created', 'updated')",
                (source_id, title, artist, album),
            )
        assert schema_version(conn) == 2
    finally:
        conn.close()

    assert len(MIGRATIONS) >= 3
    with open_path(path) as repo:
        conn = repo._conn
        assert schema_version(conn) == len(MIGRATIONS)
        assert _name_columns(conn, "1") == ("Jazyus & EdSeGaMe", "Rock & Roll", "Tom & Jerry's")
        assert _name_columns(conn, "2") == ('Say "hi"', "A <b> C", "It's's")
        # one level only: &amp; is decoded last
        assert _name_columns(conn, "3") == ("&lt;tag&gt;", "&amp;", None)
        assert _name_columns(conn, "4") == ("Plain Title", "Plain Artist", "Plain Album")
        assert _name_columns(conn, "5") == ("Fish & Chips", "R&B Crew", "AT&T")
        assert _name_columns(conn, "6") == ("Only title & more", None, None)
        # nothing else changes
        stamps = conn.execute("SELECT DISTINCT created_at, updated_at FROM tracks").fetchall()
        assert [tuple(s) for s in stamps] == [("created", "updated")]
        assert conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == len(_ROWS)
