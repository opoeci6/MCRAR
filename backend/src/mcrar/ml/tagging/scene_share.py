"""Sharing the labelling work between two catalogs (M9): the pool pack and the labels file.

Two people label the same pool from their own catalogs. Local track ids differ between catalogs,
so everything that is shared names a track by ``(source, source_id)``, never by id:

- A **pack** (``kind: mcrar-scene-pack``) lists the pool's tracks with their position, part and
  reason. It carries no local ids, no stream URLs and no keys. :func:`import_pack` maps it onto
  the importer's catalog: tracks the catalog lacks and that come from Jamendo are fetched by id
  with metadata only (no audio, no embeddings: labelling only needs the track to stream, which
  uses the importer's own Jamendo key), then the local pool is replaced by the pack's.
- A **labels file** (``kind: mcrar-scene-labels``) lists the labels of one or all labellers.
  :func:`import_labels` stores them by ``(source, source_id)``; when the same labeller's label
  of a track exists on both sides, the newer ``updated_at`` wins. Scenes are validated against
  the vocabulary before anything is written.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mcrar.catalog import CatalogRepository, PoolEntry
from mcrar.catalog.repository import (
    LABEL_STATUSES,
    POOL_PARTS,
    SCENE_INTENSITIES,
    clean_labeller,
    normalise_time,
)
from mcrar.recommend.vocab import SCENE, Vocabulary

PACK_KIND = "mcrar-scene-pack"
LABELS_KIND = "mcrar-scene-labels"
SCHEMA = 1
NO_POOL = "No labelling pool yet: run mcrar scenes pool"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _check_envelope(data: object, kind: str, what: str) -> dict:
    if not isinstance(data, dict) or data.get("kind") != kind or data.get("schema") != SCHEMA:
        raise ValueError(f"not a {what} file (expected kind {kind!r}, schema {SCHEMA})")
    return data


def _text(item: object, key: str, where: str) -> str:
    value = item.get(key) if isinstance(item, dict) else None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where}: {key} must be non-empty text")
    return value


# -- pack --------------------------------------------------------------------------------------


def export_pack(repo: CatalogRepository) -> dict[str, Any]:
    """The pool as a pack. ``ValueError`` when there is no pool."""
    pool = repo.label_pool()
    if not pool:
        raise ValueError(NO_POOL)
    tracks = repo.get_tracks(e.track_id for e in pool)
    return {
        "schema": SCHEMA,
        "kind": PACK_KIND,
        "created_at": _now(),
        "tracks": [
            {
                "source": tracks[e.track_id].source,
                "source_id": tracks[e.track_id].source_id,
                "title": tracks[e.track_id].title,
                "artist": tracks[e.track_id].artist,
                "position": e.position,
                "part": e.part,
                "reason": e.reason,
            }
            for e in pool
            if e.track_id in tracks
        ],
    }


def parse_pack(data: object) -> list[dict[str, Any]]:
    """The pack's track items, checked (unique positions, known parts)."""
    pack = _check_envelope(data, PACK_KIND, "scene pack")
    items = pack.get("tracks")
    if not isinstance(items, list) or not items:
        raise ValueError("the pack has no tracks")
    positions: set[int] = set()
    seen: set[tuple[str, str]] = set()
    for n, item in enumerate(items, start=1):
        where = f"pack track #{n}"
        source, source_id = _text(item, "source", where), _text(item, "source_id", where)
        _text(item, "reason", where)
        position = item.get("position")
        if isinstance(position, bool) or not isinstance(position, int) or position < 1:
            raise ValueError(f"{where}: position must be a positive integer")
        if item.get("part") not in POOL_PARTS:
            raise ValueError(f"{where}: part must be one of {POOL_PARTS}")
        if position in positions or (source, source_id) in seen:
            raise ValueError(f"{where}: duplicate position or track")
        positions.add(position)
        seen.add((source, source_id))
    return items


@dataclass
class PackImport:
    """What :func:`import_pack` did. ``missing`` lists the tracks that could not be mapped, each
    as ``{source, source_id, title, reason}``."""

    pool_size: int = 0
    present: int = 0
    fetched: int = 0
    missing: list[dict[str, Any]] = field(default_factory=list)


def import_pack(
    repo: CatalogRepository,
    data: object,
    *,
    open_client: Callable[[], Any] | None,
    force: bool = False,
    on_progress: Callable[[Any], None] | None = None,
) -> PackImport:
    """Map a pack onto this catalog and replace the local pool with it.

    ``open_client`` builds a Jamendo client (called only when a Jamendo track is missing; it may
    raise ``JamendoError`` or ``SecretError`` when there is no key); ``None`` means "do not
    fetch" (``--no-fetch``). Refuses when a pool exists and ``force`` is false, before any fetch.
    """
    from mcrar.ingest import ingest_jamendo_ids

    items = parse_pack(data)
    existing = repo.label_pool()
    if existing and not force:
        raise ValueError(
            f"a labelling pool of {len(existing)} tracks already exists; use --force to replace "
            "it (hand labels are kept: they belong to tracks, not to the pool)"
        )
    result = PackImport()
    absent = [i for i in items if repo.get_track_by_source(i["source"], i["source_id"]) is None]
    result.present = len(items) - len(absent)
    wanted = [i["source_id"] for i in absent if i["source"] == "jamendo"]
    if wanted and open_client is not None:
        with closing(open_client()) as client:
            report = ingest_jamendo_ids(client, repo, wanted, stages=[], on_progress=on_progress)
        if report.aborted:
            raise ValueError(f"fetching the tracks stopped ({report.aborted}); run it again")
        result.fetched = report.new
    entries: list[PoolEntry] = []
    for item in items:
        track = repo.get_track_by_source(item["source"], item["source_id"])
        if track is None:
            if item["source"] != "jamendo":
                why = f"a {item['source']} track cannot be fetched"
            elif open_client is None:
                why = "not in this catalog (fetching is off)"
            else:
                why = "Jamendo does not have it any more"
            result.missing.append(
                {
                    "source": item["source"],
                    "source_id": item["source_id"],
                    "title": item.get("title"),
                    "reason": why,
                }
            )
            continue
        entries.append(PoolEntry(track.id, item["position"], item["reason"], item["part"]))
    if not entries:
        raise ValueError("none of the pack's tracks could be mapped; the pool was not changed")
    result.pool_size = repo.replace_label_pool(entries)
    return result


# -- labels ------------------------------------------------------------------------------------


def export_labels(repo: CatalogRepository, labeller: str | None = None) -> dict[str, Any]:
    """The labels of one labeller (every labeller by default) as a labels file."""
    labels = repo.iter_scene_labels(labeller)
    tracks = repo.get_tracks(label.track_id for label in labels)
    rows = [
        {
            "labeller": label.labeller,
            "source": tracks[label.track_id].source,
            "source_id": tracks[label.track_id].source_id,
            "title": tracks[label.track_id].title,
            "artist": tracks[label.track_id].artist,
            "scenes": list(label.scenes),
            "intensity": label.intensity,
            "status": label.status,
            "updated_at": label.updated_at,
        }
        for label in labels
        if label.track_id in tracks
    ]
    rows.sort(key=lambda r: (r["labeller"], r["source"], r["source_id"]))
    return {"schema": SCHEMA, "kind": LABELS_KIND, "labels": rows}


@dataclass
class LabelsImport:
    """What :func:`import_labels` did: labels stored, labels kept because the local one was
    newer, and ``unknown`` tracks (``source:source_id``) that are not in this catalog."""

    stored: int = 0
    older: int = 0
    unknown: list[str] = field(default_factory=list)
    labellers: list[str] = field(default_factory=list)


def import_labels(
    repo: CatalogRepository,
    data: object,
    vocab: Vocabulary,
    *,
    as_labeller: str | None = None,
) -> LabelsImport:
    """Store the labels of a labels file by ``(source, source_id)``; the newer ``updated_at``
    wins a conflict. Everything is checked first: one bad label stores nothing."""
    file = _check_envelope(data, LABELS_KIND, "scene labels")
    rows = file.get("labels")
    if not isinstance(rows, list):
        raise ValueError("the labels file has no labels list")
    override = clean_labeller(as_labeller) if as_labeller is not None else None
    parsed: list[tuple[str, str, str, list[str], str | None, str, str]] = []
    unknown_scenes: list[str] = []
    for n, row in enumerate(rows, start=1):
        where = f"label #{n}"
        source, source_id = _text(row, "source", where), _text(row, "source_id", where)
        labeller = override or clean_labeller(row.get("labeller"))
        status, intensity = row.get("status"), row.get("intensity")
        if status not in LABEL_STATUSES:
            raise ValueError(f"{where}: status must be one of {LABEL_STATUSES}")
        if intensity is not None and intensity not in SCENE_INTENSITIES:
            raise ValueError(f"{where}: intensity must be one of {SCENE_INTENSITIES} or null")
        scenes = row.get("scenes", [])
        if not isinstance(scenes, list):
            raise ValueError(f"{where}: scenes must be a list")
        bad = [repr(s) for s in scenes if not isinstance(s, str) or not vocab.has(SCENE, s)]
        if bad:
            unknown_scenes.extend(b for b in bad if b not in unknown_scenes)
            continue
        scenes = list(dict.fromkeys(scenes))
        try:
            stamp = normalise_time(_text(row, "updated_at", where))
        except ValueError:
            raise ValueError(f"{where}: updated_at must be an ISO 8601 time") from None
        parsed.append((labeller, source, source_id, scenes, intensity, status, stamp))
    if unknown_scenes:
        valid = ", ".join(vocab.labels("scene"))
        raise ValueError(
            f"unknown scene label(s): {', '.join(unknown_scenes)}; choose from: {valid}"
        )
    result = LabelsImport()
    names: set[str] = set()
    for labeller, source, source_id, scenes, intensity, status, stamp in parsed:
        track = repo.get_track_by_source(source, source_id)
        if track is None:
            key = f"{source}:{source_id}"
            if key not in result.unknown:
                result.unknown.append(key)
            continue
        names.add(labeller)
        if repo.merge_scene_label(track.id, labeller, scenes, intensity, status, stamp):
            result.stored += 1
        else:
            result.older += 1
    result.labellers = sorted(names)
    return result
