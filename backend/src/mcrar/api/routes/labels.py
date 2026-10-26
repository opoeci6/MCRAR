"""Hand labels of game scenes (M9): the labelling page's endpoints under ``/api/labels``.

A labeller (a name of 1-40 characters) works through the labelling pool, a list of catalog
tracks prepared with ``mcrar scenes pool``: ``GET /next`` gives the first pool track of their
part (``all``, ``A`` or ``B``; A and B each include the shared ``both`` tracks) that they have not
labelled or skipped yet, optionally after a position. ``PUT /{track_id}`` stores the label
``{labeller, scenes, intensity, status}`` (scene ids are checked against the vocabulary: 422;
``labelled`` with no scenes means "no scene fits"; ``skipped`` keeps neither scenes nor
intensity), ``GET`` reads it back (404 when there is none) and ``DELETE`` removes it (204, or
404). ``GET /pool`` lists the pool for the labeller (their status per track) and ``GET /progress``
counts their work per part. ``GET /export`` downloads the labels file that ``mcrar scenes
import-labels`` reads (see :mod:`mcrar.ml.tagging.scene_share`).

Without a pool, ``next``, ``pool`` and ``progress`` answer 409 "No labelling pool yet: run mcrar
scenes pool". The responses never show why a track is in the pool (its reason names the scene a
model expected), so the labeller is not primed.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from mcrar.api.routes._files import safe_stem
from mcrar.api.state import AppState, StateDep
from mcrar.catalog import SceneLabel, StoredTrack
from mcrar.catalog.repository import clean_labeller
from mcrar.ml.tagging.scene_labels import check_scenes
from mcrar.ml.tagging.scene_share import NO_POOL, export_labels

router = APIRouter()

PartQuery = Annotated[Literal["all", "A", "B"], Query()]


class LabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labeller: str
    scenes: list[str] = Field(default_factory=list, max_length=100)
    intensity: Literal["low", "mid", "high"] | None = None
    status: Literal["labelled", "skipped"]


def _label_json(label: SceneLabel) -> dict[str, Any]:
    return {
        "track_id": label.track_id,
        "labeller": label.labeller,
        "scenes": list(label.scenes),
        "intensity": label.intensity,
        "status": label.status,
        "created_at": label.created_at,
        "updated_at": label.updated_at,
    }


def _player_track(track: StoredTrack) -> dict[str, Any]:
    """What the player needs (see ``PlayableTrack`` in the frontend) plus the stream path."""
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "duration_s": track.duration_s,
        "source": track.source,
        "risk": track.risk,
        "license_code": track.license_code,
        "license_url": track.license_url,
        "commercial_license_url": track.commercial_license_url,
        "attribution": track.attribution_text,
        "stream_url": f"/api/tracks/{track.id}/stream",
    }


def _require_pool(state: AppState) -> None:
    if not state.repo.label_pool():
        raise HTTPException(status_code=409, detail=NO_POOL)


# The fixed paths come before ``/{track_id}`` so that they are not read as an id.


@router.get("/api/labels/export")
def export(state: StateDep, labeller: str | None = None) -> Response:
    """The labels file (all labellers, or one) as a download."""
    name = clean_labeller(labeller) if labeller is not None else None
    body = export_labels(state.repo, name)
    stem = safe_stem(name, "all")
    return Response(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="scene-labels-{stem}.json"'},
    )


@router.get("/api/labels/next")
def next_track(
    state: StateDep,
    labeller: str,
    part: PartQuery = "all",
    after: Annotated[int | None, Query(ge=0)] = None,
) -> dict[str, Any]:
    name = clean_labeller(labeller)
    _require_pool(state)
    entry = state.repo.next_pool_track(name, part, after)
    if entry is None:
        return {"track": None}
    track = state.repo.get_track(entry.track_id)
    if track is None:  # cannot happen (pool rows cascade with their track)
        return {"track": None}
    label = state.repo.get_scene_label(entry.track_id, name)
    return {
        "track": _player_track(track),
        "position": entry.position,
        "part": entry.part,
        "label": _label_json(label) if label else None,
    }


@router.get("/api/labels/pool")
def pool(state: StateDep, labeller: str, part: PartQuery = "all") -> dict[str, Any]:
    name = clean_labeller(labeller)
    _require_pool(state)
    entries = state.repo.label_pool(part)
    tracks = state.repo.get_tracks(e.track_id for e in entries)
    status = {label.track_id: label.status for label in state.repo.iter_scene_labels(name)}
    items = [
        {
            "position": e.position,
            "part": e.part,
            "track_id": e.track_id,
            "title": tracks[e.track_id].title,
            "artist": tracks[e.track_id].artist,
            "status": status.get(e.track_id),
        }
        for e in entries
        if e.track_id in tracks
    ]
    return {"items": items, "total": len(items)}


@router.get("/api/labels/progress")
def progress(state: StateDep, labeller: str) -> dict[str, Any]:
    name = clean_labeller(labeller)
    _require_pool(state)
    parts = state.repo.label_progress(name)
    return {
        "pool_size": sum(p["total"] for p in parts.values()),
        "parts": parts,
        "labelled": sum(p["labelled"] for p in parts.values()),
        "skipped": sum(p["skipped"] for p in parts.values()),
        "labellers": state.repo.labellers(),
    }


@router.get("/api/labels/{track_id}")
def get_label(track_id: int, state: StateDep, labeller: str) -> dict[str, Any]:
    label = state.repo.get_scene_label(track_id, clean_labeller(labeller))
    if label is None:
        raise LookupError(f"track {track_id} has no label from this labeller")
    return _label_json(label)


@router.put("/api/labels/{track_id}")
def put_label(track_id: int, body: LabelBody, state: StateDep) -> dict[str, Any]:
    scenes = check_scenes(state.search.vocab, body.scenes)
    stored = state.repo.set_scene_label(
        track_id, clean_labeller(body.labeller), scenes, body.intensity, body.status
    )
    return _label_json(stored)


@router.delete("/api/labels/{track_id}", status_code=204)
def delete_label(track_id: int, state: StateDep, labeller: str) -> Response:
    if not state.repo.delete_scene_label(track_id, clean_labeller(labeller)):
        raise LookupError(f"track {track_id} has no label from this labeller")
    return Response(status_code=204)
