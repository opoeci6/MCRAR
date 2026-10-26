"""SQLite connection setup and versioned migrations (``PRAGMA user_version``)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcrar.catalog.repository import CatalogRepository
    from mcrar.config import Settings

CATALOG_FILENAME = "catalog.db"
BUSY_TIMEOUT_MS = 5000

_V1 = """
CREATE TABLE tracks (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT,
    artist TEXT,
    album TEXT,
    duration_s REAL,
    release_date TEXT,
    source_url TEXT,
    stream_url TEXT,
    download_url TEXT,
    audiodownload_allowed INTEGER CHECK (audiodownload_allowed IN (0, 1)),
    image_url TEXT,
    local_path TEXT,
    license_url TEXT,
    license_code TEXT,
    license_family TEXT,
    risk TEXT NOT NULL DEFAULT 'unknown'
        CHECK (risk IN ('green', 'amber', 'red', 'unknown')),
    commercial_ok INTEGER CHECK (commercial_ok IN (0, 1)),
    derivatives_ok INTEGER CHECK (derivatives_ok IN (0, 1)),
    share_alike INTEGER CHECK (share_alike IN (0, 1)),
    attribution_required INTEGER CHECK (attribution_required IN (0, 1)),
    attribution_text TEXT,
    commercial_license_url TEXT,
    vocal_instrumental TEXT CHECK (vocal_instrumental IN ('vocal', 'instrumental')),
    source_tags TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX idx_tracks_risk ON tracks (risk);
CREATE INDEX idx_tracks_source ON tracks (source);
CREATE INDEX idx_tracks_vocal_instrumental ON tracks (vocal_instrumental);

CREATE TABLE features (
    track_id INTEGER PRIMARY KEY REFERENCES tracks (id) ON DELETE CASCADE,
    bpm REAL,
    bpm_raw REAL,
    bpm_confidence REAL,
    key TEXT,
    mode TEXT,
    key_confidence REAL,
    loudness_lufs REAL,
    rms_db REAL,
    energy REAL,
    sample_rate INTEGER,
    channels INTEGER,
    analysis_version TEXT NOT NULL,
    analyzed_at TEXT NOT NULL
);
CREATE INDEX idx_features_bpm ON features (bpm);

CREATE TABLE tag_probs (
    track_id INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    head TEXT NOT NULL,
    label TEXT NOT NULL,
    prob REAL NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('zeroshot', 'head')),
    model_version TEXT,
    PRIMARY KEY (track_id, head, label)
);
CREATE INDEX idx_tag_probs_head_label_prob ON tag_probs (head, label, prob);

CREATE TABLE embeddings (
    track_id INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    dim INTEGER NOT NULL CHECK (dim > 0),
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (track_id, model_id)
);

CREATE TABLE ingest_log (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    track_id INTEGER REFERENCES tracks (id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'skipped')),
    message TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id, stage)
);
CREATE INDEX idx_ingest_log_status_stage ON ingest_log (status, stage);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE shortlist_items (
    project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    track_id INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    note TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY (project_id, track_id)
);
CREATE INDEX idx_shortlist_items_track ON shortlist_items (track_id);
"""

# Ratings of results per query: query_key is built by mcrar.recommend.ratings.query_key, the
# stored text and filters let the query be run again. Rows go with their track.
_V2 = """
CREATE TABLE ratings (
    query_key TEXT NOT NULL,
    query_text TEXT,
    filters_json TEXT NOT NULL DEFAULT '{}',
    track_id INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating IN (0, 1, 2)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (query_key, track_id)
);
CREATE INDEX idx_ratings_track ON ratings (track_id);
"""

# Jamendo sent HTML-escaped names ("Jazyus &amp; EdSeGaMe") that were stored as is. One level of
# decoding, with &amp; last so that "&amp;lt;" becomes "&lt;" and not "<". New data is decoded at
# parse time (mcrar.sources.jamendo.parse_track). In SQL, '''' is one single quote.
_V3 = """
UPDATE tracks SET
    title = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(title,
        '&quot;', '"'), '&#39;', ''''), '&#039;', ''''), '&apos;', ''''), '&lt;', '<'),
        '&gt;', '>'), '&amp;', '&'),
    artist = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(artist,
        '&quot;', '"'), '&#39;', ''''), '&#039;', ''''), '&apos;', ''''), '&lt;', '<'),
        '&gt;', '>'), '&amp;', '&'),
    album = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(album,
        '&quot;', '"'), '&#39;', ''''), '&#039;', ''''), '&apos;', ''''), '&lt;', '<'),
        '&gt;', '>'), '&amp;', '&')
WHERE title LIKE '%&%' OR artist LIKE '%&%' OR album LIKE '%&%';
"""


def _replace_chain(column: str, pairs: tuple[tuple[str, str], ...]) -> str:
    sql = column
    for old, new in pairs:
        sql = f"REPLACE({sql}, '{old}', '{new.replace(chr(39), chr(39) * 2)}')"
    return sql


# v3 missed the stored credit line (built from the escaped names at ingest) and named accents
# such as "&eacute;". The credit line gets the full one-level decoding (&amp; last); the names,
# already decoded by v3, get only the accents, so nothing is decoded twice. Frozen: never change.
_V4_ACCENTS: tuple[tuple[str, str], ...] = tuple(
    (f"&{name};", char)
    for name, char in (
        ("aacute", "á"),
        ("agrave", "à"),
        ("acirc", "â"),
        ("auml", "ä"),
        ("atilde", "ã"),
        ("eacute", "é"),
        ("egrave", "è"),
        ("ecirc", "ê"),
        ("euml", "ë"),
        ("iacute", "í"),
        ("igrave", "ì"),
        ("icirc", "î"),
        ("iuml", "ï"),
        ("oacute", "ó"),
        ("ograve", "ò"),
        ("ocirc", "ô"),
        ("ouml", "ö"),
        ("otilde", "õ"),
        ("uacute", "ú"),
        ("ugrave", "ù"),
        ("ucirc", "û"),
        ("uuml", "ü"),
        ("ccedil", "ç"),
        ("ntilde", "ñ"),
        ("szlig", "ß"),
        ("Eacute", "É"),
        ("Agrave", "À"),
        ("Ccedil", "Ç"),
        ("Ntilde", "Ñ"),
        ("Ouml", "Ö"),
        ("Uuml", "Ü"),
        ("Auml", "Ä"),
    )
)
_V4_FULL = (
    *_V4_ACCENTS,
    ("&quot;", '"'),
    ("&#39;", "'"),
    ("&#039;", "'"),
    ("&apos;", "'"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&amp;", "&"),
)
_V4_NAME_COLUMNS = ("title", "artist", "album")
_V4 = (
    "UPDATE tracks SET\n"
    + "".join(f"    {c} = {_replace_chain(c, _V4_ACCENTS)},\n" for c in _V4_NAME_COLUMNS)
    + f"    attribution_text = {_replace_chain('attribution_text', _V4_FULL)}\n"
    + "WHERE "
    + " OR ".join(f"{c} LIKE '%&%;%'" for c in (*_V4_NAME_COLUMNS, "attribution_text"))
    + ";\n"
)

# Hand labels of game scenes (M9) and the labelling pool. ``scene_labels`` holds one row per
# track and labeller: ``scenes_json`` is a JSON list of scene ids (an empty list with status
# 'labelled' means "no scene fits"; a 'skipped' row carries no scenes or intensity). The pool is
# the ordered list of tracks to label, split into part A, part B and 'both' (labelled by both
# people so their agreement can be measured). Rows go with their track.
_V5 = """
CREATE TABLE scene_labels (
    track_id INTEGER NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
    labeller TEXT NOT NULL,
    scenes_json TEXT NOT NULL DEFAULT '[]',
    intensity TEXT CHECK (intensity IN ('low', 'mid', 'high')),
    status TEXT NOT NULL CHECK (status IN ('labelled', 'skipped')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (track_id, labeller)
);
CREATE INDEX idx_scene_labels_labeller ON scene_labels (labeller);

CREATE TABLE label_pool (
    track_id INTEGER PRIMARY KEY REFERENCES tracks (id) ON DELETE CASCADE,
    position INTEGER NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    part TEXT NOT NULL CHECK (part IN ('A', 'B', 'both'))
);
"""

# Append only; never edit a released script. Schema version == len(applied scripts).
MIGRATIONS: tuple[str, ...] = (_V1, _V2, _V3, _V4, _V5)


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (creating parent dirs) a WAL-mode connection with foreign keys enforced.

    The connection is in autocommit mode (``isolation_level=None``); the repository manages
    transactions explicitly. It may be shared across threads, so the repository serialises use.
    """
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order; idempotent. Returns the resulting schema version."""
    current = schema_version(conn)
    if current > len(MIGRATIONS):
        raise RuntimeError(
            f"Catalog schema version {current} is newer than this code supports "
            f"({len(MIGRATIONS)}); upgrade MCRAR."
        )
    for version in range(current + 1, len(MIGRATIONS) + 1):
        script = MIGRATIONS[version - 1]
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return schema_version(conn)


def open_path(path: str | Path) -> CatalogRepository:
    """Connect to ``path``, migrate, and wrap in a repository."""
    from mcrar.catalog.repository import CatalogRepository

    conn = connect(path)
    try:
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return CatalogRepository(conn)


def open_catalog(settings: Settings) -> CatalogRepository:
    """Open the catalog at ``settings.data_dir / "catalog.db"``."""
    return open_path(settings.data_dir / CATALOG_FILENAME)
