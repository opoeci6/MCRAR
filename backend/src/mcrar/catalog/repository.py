"""The catalog repository: the only module that contains SQL.

Callers see plain dataclasses, dicts, numpy arrays and builtin exceptions, never sqlite types,
so the storage engine can later move to Postgres + pgvector behind the same interface.
Every public write method runs in its own transaction.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any, Self

import numpy as np

from mcrar.licensing.model import RISK_ORDER, risk_at_most

RISKS = ("green", "amber", "red", "unknown")
VOCAL_INSTRUMENTAL = ("vocal", "instrumental")
TAG_METHODS = ("zeroshot", "head")
INGEST_STATUSES = ("ok", "failed", "skipped")
MAX_MESSAGE_CHARS = 500

# Columns of the features table that come from AudioFeatures (duration_s lives on tracks).
FEATURE_COLUMNS = (
    "bpm",
    "bpm_raw",
    "bpm_confidence",
    "key",
    "mode",
    "key_confidence",
    "loudness_lufs",
    "rms_db",
    "energy",
    "sample_rate",
    "channels",
    "analysis_version",
)
_IGNORED_FEATURE_KEYS = frozenset({"duration_s"})

Clock = Callable[[], datetime]

BATCH = 500  # ids per query when reading many rows (stays under SQLite's variable limit)
BPM_LOW_CONFIDENCE = 0.5  # below this the tempo may be off by an octave (half or double)


@dataclass(frozen=True, kw_only=True)
class TrackRecord:
    """Track metadata as written by ingest (mirrors the ``tracks`` columns)."""

    source: str
    source_id: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration_s: float | None = None
    release_date: str | None = None
    source_url: str | None = None
    stream_url: str | None = None
    download_url: str | None = None
    audiodownload_allowed: bool | None = None
    image_url: str | None = None
    local_path: str | None = None
    license_url: str | None = None
    license_code: str | None = None
    license_family: str | None = None
    risk: str = "unknown"
    commercial_ok: bool | None = None
    derivatives_ok: bool | None = None
    share_alike: bool | None = None
    attribution_required: bool | None = None
    attribution_text: str | None = None
    commercial_license_url: str | None = None
    vocal_instrumental: str | None = None
    source_tags: dict[str, Any] | None = None


@dataclass(frozen=True, kw_only=True)
class StoredTrack(TrackRecord):
    id: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TagProb:
    track_id: int
    head: str
    label: str
    prob: float
    method: str
    model_version: str | None


@dataclass(frozen=True)
class IngestEntry:
    source: str
    source_id: str
    stage: str
    status: str
    message: str | None
    attempts: int
    track_id: int | None
    updated_at: str


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    created_at: str


@dataclass(frozen=True)
class ShortlistEntry:
    """One shortlisted track with the note and the time it was added."""

    track: StoredTrack
    note: str | None
    added_at: str


@dataclass(frozen=True)
class Rating:
    """How well one track fits one query (0 not a fit, 1 OK, 2 good fit).

    ``query_key`` identifies the query (see :mod:`mcrar.recommend.ratings`); ``query_text`` and
    ``filters_json`` are what was asked, kept so the query can be run again.
    """

    query_key: str
    query_text: str | None
    filters_json: str
    track_id: int
    rating: int
    created_at: str
    updated_at: str


RATING_VALUES = (0, 1, 2)
_RATING_COLUMNS = "query_key, query_text, filters_json, track_id, rating, created_at, updated_at"


@dataclass(frozen=True)
class SceneLabel:
    """One person's hand label of one track (M9).

    ``scenes`` are scene ids; status ``labelled`` with no scenes means "no scene fits". A
    ``skipped`` label has no scenes and no intensity. ``intensity`` is ``low``, ``mid``, ``high``
    or None (not given).
    """

    track_id: int
    labeller: str
    scenes: tuple[str, ...]
    intensity: str | None
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class PoolEntry:
    """One track of the labelling pool: its place in the order, why it is there and which part
    of the pool it belongs to (``A``, ``B`` or ``both``: labelled by both people)."""

    track_id: int
    position: int
    reason: str
    part: str


SCENE_INTENSITIES = ("low", "mid", "high")
LABEL_STATUSES = ("labelled", "skipped")
POOL_PARTS = ("A", "B", "both")
LABELLER_MAX_CHARS = 40
# which pool parts a labeller who works on one part sees (A and B each also cover ``both``)
_PART_FILTERS: dict[str, tuple[str, ...]] = {
    "all": POOL_PARTS,
    "A": ("A", "both"),
    "B": ("B", "both"),
    "both": ("both",),
}
_LABEL_COLUMNS = "track_id, labeller, scenes_json, intensity, status, created_at, updated_at"


def clean_labeller(name: object) -> str:
    """The labeller name trimmed; 1 to 40 characters without control characters."""
    if not isinstance(name, str):
        raise ValueError("labeller must be text")
    cleaned = name.strip()
    if not cleaned or len(cleaned) > LABELLER_MAX_CHARS:
        raise ValueError(f"labeller must be 1 to {LABELLER_MAX_CHARS} characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise ValueError("labeller must not contain control characters")
    return cleaned


def normalise_time(text: str) -> str:
    """An ISO 8601 time as the catalog stores times (UTC, microseconds); ``ValueError`` if it
    is not one. A time without an offset is taken as UTC."""
    return _iso(_parse_time(text))


def _parse_time(text: str) -> datetime:
    """An ISO 8601 time; one without an offset is taken as UTC."""
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _scene_label(row: sqlite3.Row) -> SceneLabel:
    return SceneLabel(
        track_id=int(row["track_id"]),
        labeller=row["labeller"],
        scenes=tuple(json.loads(row["scenes_json"])),
        intensity=row["intensity"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _label_fields(
    labeller: object, scenes: Iterable[str], intensity: str | None, status: str
) -> tuple[str, list[str], str | None]:
    """Check one label's fields; a skipped label keeps no scenes and no intensity."""
    name = clean_labeller(labeller)
    if status not in LABEL_STATUSES:
        raise ValueError(f"status must be one of {LABEL_STATUSES}, got {status!r}")
    if intensity is not None and intensity not in SCENE_INTENSITIES:
        raise ValueError(f"intensity must be one of {SCENE_INTENSITIES} or None, got {intensity!r}")
    listed = list(scenes)
    if any(not isinstance(s, str) or not s for s in listed):
        raise ValueError("scenes must be non-empty ids")
    if status == "skipped":
        return name, [], None
    return name, list(dict.fromkeys(listed)), intensity


def _part_values(part: str | None) -> tuple[str, ...]:
    values = _PART_FILTERS.get("all" if part is None else part)
    if values is None:
        raise ValueError(f"part must be one of {tuple(_PART_FILTERS)}, got {part!r}")
    return values


_TRACK_FIELDS = tuple(f.name for f in fields(TrackRecord))
_BOOL_FIELDS = frozenset(
    {
        "audiodownload_allowed",
        "commercial_ok",
        "derivatives_ok",
        "share_alike",
        "attribution_required",
    }
)
_TRACK_COLUMNS_SQL = ", ".join(("id", *_TRACK_FIELDS, "created_at", "updated_at"))
_UPSERT_TRACK_SQL = (
    f"INSERT INTO tracks ({', '.join(_TRACK_FIELDS)}, created_at, updated_at) "
    f"VALUES ({', '.join(':' + n for n in _TRACK_FIELDS)}, :now, :now) "
    "ON CONFLICT (source, source_id) DO UPDATE SET "
    + ", ".join(f"{n} = excluded.{n}" for n in _TRACK_FIELDS if n not in ("source", "source_id"))
    + ", updated_at = excluded.updated_at"
)
_UPSERT_FEATURES_SQL = (
    f"INSERT INTO features (track_id, {', '.join(FEATURE_COLUMNS)}, analyzed_at) "
    f"VALUES (:track_id, {', '.join(':' + n for n in FEATURE_COLUMNS)}, :analyzed_at) "
    "ON CONFLICT (track_id) DO UPDATE SET "
    + ", ".join(f"{n} = excluded.{n}" for n in (*FEATURE_COLUMNS, "analyzed_at"))
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _track_params(rec: TrackRecord) -> dict[str, Any]:
    if not rec.source or not rec.source_id:
        raise ValueError("source and source_id must be non-empty")
    if rec.risk not in RISKS:
        raise ValueError(f"risk must be one of {RISKS}, got {rec.risk!r}")
    if rec.vocal_instrumental is not None and rec.vocal_instrumental not in VOCAL_INSTRUMENTAL:
        raise ValueError(
            f"vocal_instrumental must be one of {VOCAL_INSTRUMENTAL} or None, "
            f"got {rec.vocal_instrumental!r}"
        )
    params: dict[str, Any] = {}
    for name in _TRACK_FIELDS:
        value = getattr(rec, name)
        if name in _BOOL_FIELDS:
            value = None if value is None else int(bool(value))
        elif name == "source_tags":
            value = None if value is None else json.dumps(value, ensure_ascii=False)
        params[name] = value
    return params


def _stored_track(row: sqlite3.Row) -> StoredTrack:
    data: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in _BOOL_FIELDS and value is not None:
            value = bool(value)
        elif key == "source_tags" and value is not None:
            value = json.loads(value)
        data[key] = value
    return StoredTrack(**data)


def _ingest_entry(row: sqlite3.Row) -> IngestEntry:
    return IngestEntry(
        source=row["source"],
        source_id=row["source_id"],
        stage=row["stage"],
        status=row["status"],
        message=row["message"],
        attempts=row["attempts"],
        track_id=row["track_id"],
        updated_at=row["updated_at"],
    )


def _chunks(ids: Iterable[int]) -> Iterator[list[int]]:
    unique = list(dict.fromkeys(int(i) for i in ids))
    for start in range(0, len(unique), BATCH):
        yield unique[start : start + BATCH]


def _in_range(value: float, low: float | None, high: float | None) -> bool:
    return (low is None or value >= low) and (high is None or value <= high)


def _bpm_passes(
    bpm: float, confidence: float | None, low: float | None, high: float | None, octaves: bool
) -> bool:
    if _in_range(bpm, low, high):
        return True
    if octaves and (confidence is None or confidence < BPM_LOW_CONFIDENCE):
        return _in_range(bpm * 2, low, high) or _in_range(bpm / 2, low, high)
    return False


def _validate_vector(vector: object) -> np.ndarray:
    arr = np.asarray(vector)
    if arr.ndim != 1:
        raise ValueError(f"embedding must be 1-D, got shape {arr.shape}")
    if arr.size == 0:
        raise ValueError("embedding must not be empty")
    if not (np.issubdtype(arr.dtype, np.floating) or np.issubdtype(arr.dtype, np.integer)):
        raise ValueError(f"embedding must be numeric, got dtype {arr.dtype}")
    arr = arr.astype("<f4")
    if not np.isfinite(arr).all():
        raise ValueError("embedding contains non-finite values")
    return arr


class CatalogRepository:
    """SQL-backed catalog access. Thread-safe (calls are serialised on one connection)."""

    def __init__(self, conn: sqlite3.Connection, *, clock: Clock = _utc_now) -> None:
        self._conn = conn
        self._clock = clock
        self._lock = threading.RLock()

    # -- lifecycle -------------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- internals -------------------------------------------------------------------------

    def _now(self) -> str:
        return _iso(self._clock())

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _query(self, sql: str, params: Mapping[str, Any] | tuple[Any, ...] = ()) -> list[Any]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @staticmethod
    def _require_track(conn: sqlite3.Connection, track_id: int) -> None:
        if conn.execute("SELECT 1 FROM tracks WHERE id = ?", (track_id,)).fetchone() is None:
            raise LookupError(f"no track with id {track_id}")

    # -- tracks ----------------------------------------------------------------------------

    def upsert_track(self, rec: TrackRecord) -> int:
        """Insert, or update the ``(source, source_id)`` row in place. Returns the track id."""
        params = _track_params(rec)
        params["now"] = self._now()
        with self._write() as conn:
            conn.execute(_UPSERT_TRACK_SQL, params)
            row = conn.execute(
                "SELECT id FROM tracks WHERE source = ? AND source_id = ?",
                (rec.source, rec.source_id),
            ).fetchone()
        return int(row["id"])

    def get_track(self, track_id: int) -> StoredTrack | None:
        rows = self._query(f"SELECT {_TRACK_COLUMNS_SQL} FROM tracks WHERE id = ?", (track_id,))
        return _stored_track(rows[0]) if rows else None

    def get_track_by_source(self, source: str, source_id: str) -> StoredTrack | None:
        rows = self._query(
            f"SELECT {_TRACK_COLUMNS_SQL} FROM tracks WHERE source = ? AND source_id = ?",
            (source, source_id),
        )
        return _stored_track(rows[0]) if rows else None

    def get_tracks(self, ids: Iterable[int]) -> dict[int, StoredTrack]:
        """The tracks with these ids, keyed by id (unknown ids are absent). One query per batch."""
        out: dict[int, StoredTrack] = {}
        for chunk in _chunks(ids):
            marks = ", ".join("?" * len(chunk))
            for row in self._query(
                f"SELECT {_TRACK_COLUMNS_SQL} FROM tracks WHERE id IN ({marks})", chunk
            ):
                out[int(row["id"])] = _stored_track(row)
        return out

    def filter_track_ids(
        self,
        *,
        max_risk: str = "unknown",
        vocal: str | None = None,
        bpm_min: float | None = None,
        bpm_max: float | None = None,
        bpm_octave_tolerance: bool = True,
        duration_min_s: float | None = None,
        duration_max_s: float | None = None,
        sources: Iterable[str] | None = None,
    ) -> list[int]:
        """Ids (ascending) of the tracks that pass every hard filter that is set.

        - ``max_risk``: the track's risk is no worse than this (``unknown`` is worse than red,
          so ``max_risk="unknown"`` filters nothing).
        - ``vocal``: ``vocal`` or ``instrumental``; tracks whose flag is unknown (local files
          have none) pass, only known mismatches are excluded.
        - ``bpm_min``/``bpm_max`` use ``features.bpm``. With ``bpm_octave_tolerance`` a track whose
          ``bpm_confidence`` is below 0.5 (or unknown) also passes when half or double its tempo
          is in range. Tracks without a BPM pass only when no BPM bound is set.
        - ``duration_*_s``: tracks with an unknown duration pass; known ones must be in range.
        - ``sources``: only these sources (an empty collection matches nothing).
        """
        if max_risk not in RISKS:
            raise ValueError(f"max_risk must be one of {RISKS}, got {max_risk!r}")
        if vocal is not None and vocal not in VOCAL_INSTRUMENTAL:
            raise ValueError(f"vocal must be one of {VOCAL_INSTRUMENTAL} or None, got {vocal!r}")
        where: list[str] = []
        params: list[Any] = []
        if max_risk != RISK_ORDER[-1]:
            allowed = [r for r in RISK_ORDER if risk_at_most(r, max_risk)]  # type: ignore[arg-type]
            where.append(f"t.risk IN ({', '.join('?' * len(allowed))})")
            params += allowed
        if vocal is not None:
            where.append("(t.vocal_instrumental = ? OR t.vocal_instrumental IS NULL)")
            params.append(vocal)
        if duration_min_s is not None:
            where.append("(t.duration_s >= ? OR t.duration_s IS NULL)")
            params.append(duration_min_s)
        if duration_max_s is not None:
            where.append("(t.duration_s <= ? OR t.duration_s IS NULL)")
            params.append(duration_max_s)
        if sources is not None:
            names = list(sources)
            where.append(f"t.source IN ({', '.join('?' * len(names))})" if names else "0")
            params += names
        sql = "SELECT t.id, f.bpm, f.bpm_confidence FROM tracks t LEFT JOIN features f "
        sql += "ON f.track_id = t.id"
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = self._query(sql + " ORDER BY t.id", params)
        if bpm_min is None and bpm_max is None:
            return [int(r["id"]) for r in rows]
        return [
            int(r["id"])
            for r in rows
            if r["bpm"] is not None
            and _bpm_passes(r["bpm"], r["bpm_confidence"], bpm_min, bpm_max, bpm_octave_tolerance)
        ]

    def iter_tracks(self, source: str | None = None) -> Iterator[StoredTrack]:
        """Yield tracks ordered by id, optionally only those of one ``source``."""
        if source is None:
            rows = self._query(f"SELECT {_TRACK_COLUMNS_SQL} FROM tracks ORDER BY id")
        else:
            rows = self._query(
                f"SELECT {_TRACK_COLUMNS_SQL} FROM tracks WHERE source = ? ORDER BY id",
                (source,),
            )
        for row in rows:
            yield _stored_track(row)

    def list_tracks(
        self,
        *,
        source: str | None = None,
        risk: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[StoredTrack], int]:
        """One page of tracks ordered by id, and how many tracks match in total.

        ``source`` and ``risk`` match exactly (``risk`` is the track's own level, not a maximum).
        """
        if risk is not None and risk not in RISKS:
            raise ValueError(f"risk must be one of {RISKS}, got {risk!r}")
        where, params = [], []
        for column, value in (("source", source), ("risk", risk)):
            if value is not None:
                where.append(f"{column} = ?")
                params.append(value)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        total = int(self._query(f"SELECT COUNT(*) FROM tracks{clause}", tuple(params))[0][0])
        rows = self._query(
            f"SELECT {_TRACK_COLUMNS_SQL} FROM tracks{clause} ORDER BY id LIMIT ? OFFSET ?",
            (*params, max(limit, 0), max(offset, 0)),
        )
        return [_stored_track(row) for row in rows], total

    def delete_track(self, track_id: int) -> bool:
        """Delete a track and (by cascade) its features, tags, embeddings and shortlist rows."""
        with self._write() as conn:
            cur = conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
            return cur.rowcount > 0

    # -- features --------------------------------------------------------------------------

    def set_features(self, track_id: int, features: Mapping[str, object]) -> None:
        """Upsert analysis features; accepts ``AudioFeatures.to_dict()``.

        ``duration_s`` is ignored (it belongs to the track). ``analysis_version`` is required;
        ``analyzed_at`` defaults to now.
        """
        unknown = set(features) - set(FEATURE_COLUMNS) - _IGNORED_FEATURE_KEYS - {"analyzed_at"}
        if unknown:
            raise ValueError(f"unknown feature keys: {sorted(unknown)}")
        if not features.get("analysis_version"):
            raise ValueError("features must include analysis_version")
        params: dict[str, Any] = {name: features.get(name) for name in FEATURE_COLUMNS}
        params["track_id"] = track_id
        params["analyzed_at"] = features.get("analyzed_at") or self._now()
        with self._write() as conn:
            self._require_track(conn, track_id)
            conn.execute(_UPSERT_FEATURES_SQL, params)

    def get_features(self, track_id: int) -> dict[str, Any] | None:
        rows = self._query(
            f"SELECT {', '.join(FEATURE_COLUMNS)}, analyzed_at FROM features WHERE track_id = ?",
            (track_id,),
        )
        return dict(zip(rows[0].keys(), tuple(rows[0]), strict=True)) if rows else None

    def get_features_many(self, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        """Features keyed by track id, shaped like :meth:`get_features` (missing ids absent)."""
        out: dict[int, dict[str, Any]] = {}
        cols = ", ".join(("track_id", *FEATURE_COLUMNS, "analyzed_at"))
        for chunk in _chunks(ids):
            marks = ", ".join("?" * len(chunk))
            sql = f"SELECT {cols} FROM features WHERE track_id IN ({marks})"
            for row in self._query(sql, chunk):
                values = dict(zip(row.keys(), tuple(row), strict=True))
                out[int(values.pop("track_id"))] = values
        return out

    def features_version(self, track_id: int) -> str | None:
        """The ``analysis_version`` stored for a track, or None if never analysed."""
        rows = self._query("SELECT analysis_version FROM features WHERE track_id = ?", (track_id,))
        return rows[0][0] if rows else None

    # -- tag probabilities -----------------------------------------------------------------

    def set_tag_probs(
        self,
        track_id: int,
        head: str,
        method: str,
        model_version: str | None,
        probs: Mapping[str, float],
    ) -> None:
        """Replace all rows of ``head`` for the track with ``probs`` (label -> probability)."""
        if method not in TAG_METHODS:
            raise ValueError(f"method must be one of {TAG_METHODS}, got {method!r}")
        rows = []
        for label, prob in probs.items():
            value = float(prob)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"probability for {label!r} must be in [0, 1], got {prob!r}")
            rows.append((track_id, head, label, value, method, model_version))
        with self._write() as conn:
            self._require_track(conn, track_id)
            conn.execute("DELETE FROM tag_probs WHERE track_id = ? AND head = ?", (track_id, head))
            conn.executemany(
                "INSERT INTO tag_probs (track_id, head, label, prob, method, model_version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def get_tag_probs(self, track_id: int, head: str | None = None) -> list[TagProb]:
        """Tag rows ordered by head, then probability descending, then label."""
        sql = (
            "SELECT track_id, head, label, prob, method, model_version FROM tag_probs "
            "WHERE track_id = ?"
        )
        params: tuple[Any, ...] = (track_id,)
        if head is not None:
            sql += " AND head = ?"
            params += (head,)
        rows = self._query(sql + " ORDER BY head, prob DESC, label", params)
        return [TagProb(*tuple(r)) for r in rows]

    def get_tag_probs_many(
        self, ids: Iterable[int], heads: Iterable[str] | None = None
    ) -> dict[int, list[TagProb]]:
        """Tag rows per track id (tracks without rows are absent), each list ordered as in
        :meth:`get_tag_probs`. ``heads`` limits the label sets read."""
        wanted = None if heads is None else list(heads)
        out: dict[int, list[TagProb]] = {}
        if wanted is not None and not wanted:
            return out
        for chunk in _chunks(ids):
            sql = (
                "SELECT track_id, head, label, prob, method, model_version FROM tag_probs "
                f"WHERE track_id IN ({', '.join('?' * len(chunk))})"
            )
            params: list[Any] = list(chunk)
            if wanted is not None:
                sql += f" AND head IN ({', '.join('?' * len(wanted))})"
                params += wanted
            for row in self._query(sql + " ORDER BY track_id, head, prob DESC, label", params):
                out.setdefault(int(row["track_id"]), []).append(TagProb(*tuple(row)))
        return out

    def tag_probs_signature(self, head: str) -> tuple[int, int | None, float]:
        """``(row count, latest rowid, sum of probabilities)`` of a head's rows: changes whenever
        rows are added, replaced or deleted, so callers can tell cached statistics are stale."""
        row = self._query(
            "SELECT COUNT(*), MAX(rowid), TOTAL(prob) FROM tag_probs WHERE head = ?", (head,)
        )[0]
        return int(row[0]), None if row[1] is None else int(row[1]), float(row[2])

    def tag_prob_moments(
        self, head: str, model_version: str | None = None
    ) -> tuple[int, dict[str, tuple[float, float]]]:
        """``(tracks, {label: (sum of prob, sum of prob squared)})`` over a head's rows.

        ``tracks`` counts the distinct tracks with rows; ``model_version`` limits both to the rows
        of that version (``None``: every row). Labels without rows are absent.
        """
        where, params = "head = ?", (head,)
        if model_version is not None:
            where, params = where + " AND model_version = ?", (head, model_version)
        tracks = self._query(
            f"SELECT COUNT(DISTINCT track_id) FROM tag_probs WHERE {where}", params
        )
        rows = self._query(
            "SELECT label, SUM(prob), SUM(prob * prob) FROM tag_probs "
            f"WHERE {where} GROUP BY label",
            params,
        )
        return int(tracks[0][0]), {str(r[0]): (float(r[1]), float(r[2])) for r in rows}

    # -- embeddings ------------------------------------------------------------------------

    def embedding_stats(self, model_id: str) -> tuple[int, str | None]:
        """``(count, latest created_at)`` of a model's embeddings: changes whenever one is added,
        replaced or deleted, so callers can tell when an in-memory index is stale."""
        row = self._query(
            "SELECT COUNT(*), MAX(created_at) FROM embeddings WHERE model_id = ?", (model_id,)
        )[0]
        return int(row[0]), row[1]

    def set_embedding(self, track_id: int, model_id: str, vector: object) -> None:
        """Store a 1-D finite float32 vector; its length must match the model's existing dim."""
        arr = _validate_vector(vector)
        dim = int(arr.shape[0])
        with self._write() as conn:
            self._require_track(conn, track_id)
            existing = conn.execute(
                "SELECT dim FROM embeddings WHERE model_id = ? LIMIT 1", (model_id,)
            ).fetchone()
            if existing is not None and int(existing["dim"]) != dim:
                raise ValueError(
                    f"embedding dim {dim} does not match existing dim {existing['dim']} "
                    f"for model {model_id!r}"
                )
            conn.execute(
                "INSERT INTO embeddings (track_id, model_id, dim, vector, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (track_id, model_id) DO UPDATE SET "
                "dim = excluded.dim, vector = excluded.vector, created_at = excluded.created_at",
                (track_id, model_id, dim, arr.tobytes(), self._now()),
            )

    def get_embedding(self, track_id: int, model_id: str) -> np.ndarray | None:
        rows = self._query(
            "SELECT dim, vector FROM embeddings WHERE track_id = ? AND model_id = ?",
            (track_id, model_id),
        )
        if not rows:
            return None
        return np.frombuffer(rows[0]["vector"], dtype="<f4").astype(np.float32)

    def load_embeddings(self, model_id: str) -> tuple[np.ndarray, np.ndarray]:
        """All embeddings of ``model_id`` as ``(ids int64 [n], matrix float32 [n, dim])``.

        Rows are ordered by track id. With no embeddings the result is shapes ``(0,)``/``(0, 0)``.
        """
        rows = self._query(
            "SELECT track_id, dim, vector FROM embeddings WHERE model_id = ? ORDER BY track_id",
            (model_id,),
        )
        if not rows:
            return np.empty(0, dtype=np.int64), np.empty((0, 0), dtype=np.float32)
        dim = int(rows[0]["dim"])
        ids = np.fromiter((r["track_id"] for r in rows), dtype=np.int64, count=len(rows))
        matrix = np.empty((len(rows), dim), dtype=np.float32)
        for i, row in enumerate(rows):
            matrix[i] = np.frombuffer(row["vector"], dtype="<f4")
        return ids, matrix

    # -- ingest log ------------------------------------------------------------------------

    def log_ingest(
        self,
        source: str,
        source_id: str,
        stage: str,
        status: str,
        message: str | None = None,
        track_id: int | None = None,
    ) -> None:
        """Record the outcome of a stage; ``attempts`` increments on every call.

        ``message`` must be short and must never contain secrets (it is truncated).
        """
        if status not in INGEST_STATUSES:
            raise ValueError(f"status must be one of {INGEST_STATUSES}, got {status!r}")
        if message is not None and len(message) > MAX_MESSAGE_CHARS:
            message = message[: MAX_MESSAGE_CHARS - 3] + "..."
        with self._write() as conn:
            if track_id is not None:
                self._require_track(conn, track_id)
            conn.execute(
                "INSERT INTO ingest_log "
                "(source, source_id, stage, track_id, status, message, attempts, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?) "
                "ON CONFLICT (source, source_id, stage) DO UPDATE SET "
                "track_id = COALESCE(excluded.track_id, ingest_log.track_id), "
                "status = excluded.status, message = excluded.message, "
                "attempts = ingest_log.attempts + 1, updated_at = excluded.updated_at",
                (source, source_id, stage, track_id, status, message, self._now()),
            )

    def get_ingest_status(self, source: str, source_id: str, stage: str) -> IngestEntry | None:
        rows = self._query(
            "SELECT * FROM ingest_log WHERE source = ? AND source_id = ? AND stage = ?",
            (source, source_id, stage),
        )
        return _ingest_entry(rows[0]) if rows else None

    def ingest_entries(self, source: str, source_id: str) -> list[IngestEntry]:
        """Every stage's ingest status for one source track, ordered by stage."""
        rows = self._query(
            "SELECT * FROM ingest_log WHERE source = ? AND source_id = ? ORDER BY stage",
            (source, source_id),
        )
        return [_ingest_entry(r) for r in rows]

    def failed_items(self, stage: str | None = None) -> list[IngestEntry]:
        sql = "SELECT * FROM ingest_log WHERE status = 'failed'"
        params: tuple[Any, ...] = ()
        if stage is not None:
            sql += " AND stage = ?"
            params = (stage,)
        rows = self._query(sql + " ORDER BY stage, source, source_id", params)
        return [_ingest_entry(r) for r in rows]

    # -- stats -----------------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Counts for dashboards and the CLI."""
        total = self._query("SELECT COUNT(*) FROM tracks")[0][0]
        with_features = self._query("SELECT COUNT(*) FROM features")[0][0]
        return {
            "tracks": total,
            "tracks_by_source": dict(
                tuple(r) for r in self._query("SELECT source, COUNT(*) FROM tracks GROUP BY source")
            ),
            "tracks_by_risk": dict(
                tuple(r) for r in self._query("SELECT risk, COUNT(*) FROM tracks GROUP BY risk")
            ),
            "features": {
                "tracks_with_features": with_features,
                "coverage": (with_features / total) if total else 0.0,
            },
            "embeddings_by_model": dict(
                tuple(r)
                for r in self._query("SELECT model_id, COUNT(*) FROM embeddings GROUP BY model_id")
            ),
            "ingest_failures_by_stage": dict(
                tuple(r)
                for r in self._query(
                    "SELECT stage, COUNT(*) FROM ingest_log WHERE status = 'failed' GROUP BY stage"
                )
            ),
        }

    # -- projects and shortlist --------------------------------------------------------------

    def create_project(self, name: str) -> int:
        if not name.strip():
            raise ValueError("project name must be non-empty")
        with self._write() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE name = ?", (name,)).fetchone():
                raise ValueError(f"project {name!r} already exists")
            cur = conn.execute(
                "INSERT INTO projects (name, created_at) VALUES (?, ?)", (name, self._now())
            )
            return int(cur.lastrowid)  # type: ignore[arg-type]

    def list_projects(self) -> list[Project]:
        rows = self._query("SELECT id, name, created_at FROM projects ORDER BY id")
        return [Project(*tuple(r)) for r in rows]

    def shortlist_counts(self) -> dict[int, int]:
        """Number of shortlisted tracks per project id (projects without any are absent)."""
        rows = self._query("SELECT project_id, COUNT(*) FROM shortlist_items GROUP BY project_id")
        return {int(r[0]): int(r[1]) for r in rows}

    def get_project(self, project_id: int) -> Project | None:
        rows = self._query("SELECT id, name, created_at FROM projects WHERE id = ?", (project_id,))
        return Project(*tuple(rows[0])) if rows else None

    def rename_project(self, project_id: int, name: str) -> None:
        if not name.strip():
            raise ValueError("project name must be non-empty")
        with self._write() as conn:
            if (
                conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise LookupError(f"no project with id {project_id}")
            if conn.execute(
                "SELECT 1 FROM projects WHERE name = ? AND id <> ?", (name, project_id)
            ).fetchone():
                raise ValueError(f"project {name!r} already exists")
            conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))

    def delete_project(self, project_id: int) -> bool:
        """Delete a project and (by cascade) its shortlist; the tracks stay. False if unknown."""
        with self._write() as conn:
            return conn.execute("DELETE FROM projects WHERE id = ?", (project_id,)).rowcount > 0

    def add_to_shortlist(self, project_id: int, track_id: int, note: str | None = None) -> None:
        """Add (or update the note of) a track in a project's shortlist."""
        with self._write() as conn:
            if (
                conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise LookupError(f"no project with id {project_id}")
            self._require_track(conn, track_id)
            conn.execute(
                "INSERT INTO shortlist_items (project_id, track_id, note, added_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (project_id, track_id) DO UPDATE SET note = excluded.note",
                (project_id, track_id, note, self._now()),
            )

    def remove_from_shortlist(self, project_id: int, track_id: int) -> bool:
        with self._write() as conn:
            cur = conn.execute(
                "DELETE FROM shortlist_items WHERE project_id = ? AND track_id = ?",
                (project_id, track_id),
            )
            return cur.rowcount > 0

    def shortlist(self, project_id: int) -> list[StoredTrack]:
        """Shortlisted tracks, oldest addition first."""
        cols = ", ".join(f"t.{c}" for c in ("id", *_TRACK_FIELDS, "created_at", "updated_at"))
        rows = self._query(
            f"SELECT {cols} FROM shortlist_items s JOIN tracks t ON t.id = s.track_id "
            "WHERE s.project_id = ? ORDER BY s.added_at, t.id",
            (project_id,),
        )
        return [_stored_track(r) for r in rows]

    def shortlist_entries(self, project_id: int) -> list[ShortlistEntry]:
        """Shortlisted tracks with note and add time, oldest first (ties by track id)."""
        if self.get_project(project_id) is None:
            raise LookupError(f"no project with id {project_id}")
        tracks = {t.id: t for t in self.shortlist(project_id)}
        rows = self._query(
            "SELECT track_id, note, added_at FROM shortlist_items "
            "WHERE project_id = ? ORDER BY added_at, track_id",
            (project_id,),
        )
        return [
            ShortlistEntry(tracks[r["track_id"]], r["note"], r["added_at"])
            for r in rows
            if r["track_id"] in tracks
        ]

    # -- ratings -----------------------------------------------------------------------------

    def set_rating(
        self,
        query_key: str,
        track_id: int,
        rating: int,
        *,
        query_text: str | None = None,
        filters_json: str = "{}",
    ) -> Rating:
        """Rate a track for a query; rating it again replaces the score (``created_at`` stays)."""
        if not query_key:
            raise ValueError("query_key must be non-empty")
        if isinstance(rating, bool) or rating not in RATING_VALUES:
            raise ValueError(f"rating must be one of {RATING_VALUES}, got {rating!r}")
        now = self._now()
        with self._write() as conn:
            self._require_track(conn, track_id)
            conn.execute(
                f"INSERT INTO ratings ({_RATING_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (query_key, track_id) DO UPDATE SET "
                "query_text = excluded.query_text, filters_json = excluded.filters_json, "
                "rating = excluded.rating, updated_at = excluded.updated_at",
                (query_key, query_text, filters_json, track_id, rating, now, now),
            )
            row = conn.execute(
                f"SELECT {_RATING_COLUMNS} FROM ratings WHERE query_key = ? AND track_id = ?",
                (query_key, track_id),
            ).fetchone()
        return Rating(*tuple(row))

    def delete_rating(self, query_key: str, track_id: int) -> bool:
        with self._write() as conn:
            cur = conn.execute(
                "DELETE FROM ratings WHERE query_key = ? AND track_id = ?", (query_key, track_id)
            )
            return cur.rowcount > 0

    def ratings_for(self, query_key: str, track_ids: Iterable[int]) -> dict[int, int]:
        """The ratings of a query among these tracks, keyed by track id (unrated ids absent)."""
        out: dict[int, int] = {}
        for chunk in _chunks(track_ids):
            marks = ", ".join("?" * len(chunk))
            rows = self._query(
                "SELECT track_id, rating FROM ratings "
                f"WHERE query_key = ? AND track_id IN ({marks})",
                (query_key, *chunk),
            )
            out.update((int(r["track_id"]), int(r["rating"])) for r in rows)
        return out

    def iter_ratings(self) -> list[Rating]:
        """Every rating, ordered by query key then track id."""
        rows = self._query(f"SELECT {_RATING_COLUMNS} FROM ratings ORDER BY query_key, track_id")
        return [Rating(*tuple(r)) for r in rows]

    def list_ratings(self, *, limit: int = 100, offset: int = 0) -> tuple[list[Rating], int]:
        """One page of ratings, most recently changed first, and how many ratings exist."""
        total = int(self._query("SELECT COUNT(*) FROM ratings")[0][0])
        rows = self._query(
            f"SELECT {_RATING_COLUMNS} FROM ratings "
            "ORDER BY updated_at DESC, query_key, track_id LIMIT ? OFFSET ?",
            (max(limit, 0), max(offset, 0)),
        )
        return [Rating(*tuple(r)) for r in rows], total

    def rating_queries(self) -> list[tuple[str, str | None, str, int]]:
        """``(query_key, query_text, filters_json, rating count)`` per rated query, by key.

        When the ratings of a query were stored with different text or filters (the key ignores
        the filters of a text query) the most recently changed rating's values are reported.
        """
        rows = self._query(
            "SELECT query_key, query_text, filters_json FROM ratings "
            "ORDER BY query_key, updated_at DESC, track_id"
        )
        out: dict[str, list[Any]] = {}
        for row in rows:
            entry = out.setdefault(
                row["query_key"], [row["query_key"], row["query_text"], row["filters_json"], 0]
            )
            entry[3] += 1
        return [(k, text, filters, count) for k, text, filters, count in out.values()]

    # -- scene labels and the labelling pool (M9) ---------------------------------------------

    def _put_scene_label(
        self,
        conn: sqlite3.Connection,
        track_id: int,
        fields_: tuple[str, list[str], str | None],
        status: str,
        *,
        created_at: str,
        updated_at: str,
    ) -> None:
        name, scenes, intensity = fields_
        conn.execute(
            f"INSERT INTO scene_labels ({_LABEL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (track_id, labeller) DO UPDATE SET "
            "scenes_json = excluded.scenes_json, intensity = excluded.intensity, "
            "status = excluded.status, updated_at = excluded.updated_at",
            (
                track_id,
                name,
                json.dumps(scenes, ensure_ascii=False),
                intensity,
                status,
                created_at,
                updated_at,
            ),
        )

    def set_scene_label(
        self,
        track_id: int,
        labeller: str,
        scenes: Iterable[str],
        intensity: str | None,
        status: str,
    ) -> SceneLabel:
        """Store a labeller's label of a track; labelling again replaces it (``created_at`` stays).

        The scene ids are not checked against the vocabulary here (see
        :func:`mcrar.ml.tagging.scene_labels.check_scenes`). A ``skipped`` label drops its scenes
        and intensity.
        """
        fields_ = _label_fields(labeller, scenes, intensity, status)
        now = self._now()
        with self._write() as conn:
            self._require_track(conn, track_id)
            self._put_scene_label(conn, track_id, fields_, status, created_at=now, updated_at=now)
            row = conn.execute(
                f"SELECT {_LABEL_COLUMNS} FROM scene_labels WHERE track_id = ? AND labeller = ?",
                (track_id, fields_[0]),
            ).fetchone()
        return _scene_label(row)

    def merge_scene_label(
        self,
        track_id: int,
        labeller: str,
        scenes: Iterable[str],
        intensity: str | None,
        status: str,
        updated_at: str,
    ) -> bool:
        """Store an imported label unless a newer (or equally new) one exists. True if stored.

        ``updated_at`` is the time the label was made (ISO 8601); it is kept as the row's time.
        """
        fields_ = _label_fields(labeller, scenes, intensity, status)
        stamp = _iso(_parse_time(updated_at))
        with self._write() as conn:
            self._require_track(conn, track_id)
            row = conn.execute(
                "SELECT created_at, updated_at FROM scene_labels "
                "WHERE track_id = ? AND labeller = ?",
                (track_id, fields_[0]),
            ).fetchone()
            if row is not None and _parse_time(row["updated_at"]) >= _parse_time(stamp):
                return False
            created = row["created_at"] if row is not None else stamp
            self._put_scene_label(
                conn, track_id, fields_, status, created_at=created, updated_at=stamp
            )
        return True

    def get_scene_label(self, track_id: int, labeller: str) -> SceneLabel | None:
        rows = self._query(
            f"SELECT {_LABEL_COLUMNS} FROM scene_labels WHERE track_id = ? AND labeller = ?",
            (track_id, clean_labeller(labeller)),
        )
        return _scene_label(rows[0]) if rows else None

    def delete_scene_label(self, track_id: int, labeller: str) -> bool:
        with self._write() as conn:
            cur = conn.execute(
                "DELETE FROM scene_labels WHERE track_id = ? AND labeller = ?",
                (track_id, clean_labeller(labeller)),
            )
            return cur.rowcount > 0

    def iter_scene_labels(self, labeller: str | None = None) -> list[SceneLabel]:
        """Every scene label (of one labeller when given), ordered by track id then labeller."""
        sql = f"SELECT {_LABEL_COLUMNS} FROM scene_labels"
        params: tuple[Any, ...] = ()
        if labeller is not None:
            sql, params = sql + " WHERE labeller = ?", (clean_labeller(labeller),)
        return [_scene_label(r) for r in self._query(sql + " ORDER BY track_id, labeller", params)]

    def labellers(self) -> list[str]:
        """The names that have labelled (or skipped) a track, alphabetically."""
        rows = self._query("SELECT DISTINCT labeller FROM scene_labels ORDER BY labeller")
        return [r["labeller"] for r in rows]

    def replace_label_pool(self, entries: Iterable[PoolEntry]) -> int:
        """Replace the whole pool; returns its size. Labels are per track and are not touched."""
        rows = list(entries)
        for entry in rows:
            if entry.part not in POOL_PARTS:
                raise ValueError(f"part must be one of {POOL_PARTS}, got {entry.part!r}")
            if not entry.reason:
                raise ValueError("a pool entry needs a reason")
        with self._write() as conn:
            for entry in rows:
                self._require_track(conn, entry.track_id)
            conn.execute("DELETE FROM label_pool")
            conn.executemany(
                "INSERT INTO label_pool (track_id, position, reason, part) VALUES (?, ?, ?, ?)",
                [(e.track_id, e.position, e.reason, e.part) for e in rows],
            )
        return len(rows)

    def label_pool(self, part: str | None = None) -> list[PoolEntry]:
        """The pool in order. ``part`` ``A`` or ``B`` also includes the ``both`` tracks; ``None``
        or ``all`` is the whole pool."""
        values = _part_values(part)
        rows = self._query(
            "SELECT track_id, position, reason, part FROM label_pool "
            f"WHERE part IN ({', '.join('?' * len(values))}) ORDER BY position",
            values,
        )
        return [PoolEntry(int(r[0]), int(r[1]), r[2], r[3]) for r in rows]

    def next_pool_track(
        self, labeller: str, part: str | None = None, after_position: int | None = None
    ) -> PoolEntry | None:
        """The first pool track (in order, after ``after_position`` when given) of the part that
        this labeller has not labelled or skipped yet; None when there is none."""
        values = _part_values(part)
        rows = self._query(
            "SELECT p.track_id, p.position, p.reason, p.part FROM label_pool p "
            f"WHERE p.part IN ({', '.join('?' * len(values))}) AND p.position > ? "
            "AND NOT EXISTS (SELECT 1 FROM scene_labels l "
            "WHERE l.track_id = p.track_id AND l.labeller = ?) "
            "ORDER BY p.position LIMIT 1",
            (*values, -1 if after_position is None else after_position, clean_labeller(labeller)),
        )
        return PoolEntry(int(rows[0][0]), int(rows[0][1]), rows[0][2], rows[0][3]) if rows else None

    def label_progress(self, labeller: str) -> dict[str, dict[str, int]]:
        """Per pool part (``A``, ``B``, ``both``): ``{total, labelled, skipped}`` for a labeller.

        Only labels of pool tracks count."""
        out = {p: {"total": 0, "labelled": 0, "skipped": 0} for p in POOL_PARTS}
        rows = self._query(
            "SELECT p.part, COUNT(*), "
            "COALESCE(SUM(l.status = 'labelled'), 0), COALESCE(SUM(l.status = 'skipped'), 0) "
            "FROM label_pool p LEFT JOIN scene_labels l "
            "ON l.track_id = p.track_id AND l.labeller = ? GROUP BY p.part",
            (clean_labeller(labeller),),
        )
        for part, total, labelled, skipped in rows:
            out[part] = {"total": int(total), "labelled": int(labelled), "skipped": int(skipped)}
        return out
