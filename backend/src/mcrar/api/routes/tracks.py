"""Catalog tracks: list, detail, audio stream and credits download.

Audio is never proxied. A Jamendo track answers with a 307 redirect to a fresh stream URL (the
stored one expires, so it is looked up again and kept in memory for 30 minutes). A local track
is served from the file path stored in the catalog, with HTTP Range support (Starlette's
``FileResponse`` answers ``Range`` with 206), and no request ever supplies a path.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response

from mcrar.api.routes._files import credits_download, safe_stem
from mcrar.api.state import AppState, StateDep
from mcrar.catalog import StoredTrack
from mcrar.licensing import track_credits
from mcrar.recommend.request import SOURCES
from mcrar.secrets import SecretError
from mcrar.sources import JamendoError

router = APIRouter()


def _track(state: AppState, track_id: int) -> StoredTrack:
    track = state.repo.get_track(track_id)
    if track is None:
        raise LookupError(f"no track with id {track_id}")
    return track


def track_summary(track: StoredTrack) -> dict[str, Any]:
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "source": track.source,
        "duration_s": track.duration_s,
        "risk": track.risk,
        "license_code": track.license_code,
    }


@router.get("/api/tracks")
def list_tracks(
    state: StateDep,
    source: str | None = None,
    risk: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if source is not None and source not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(SOURCES)}")
    if risk is not None and risk not in ("green", "amber", "red", "unknown"):
        raise ValueError("risk must be one of: green, amber, red, unknown")
    tracks, total = state.repo.list_tracks(source=source, risk=risk, limit=limit, offset=offset)
    return {
        "items": [track_summary(t) for t in tracks],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/tracks/{track_id}")
def track_detail(track_id: int, state: StateDep) -> dict[str, Any]:
    track = _track(state, track_id)
    tags = [
        {
            "label_set": p.head,
            "label": p.label,
            "prob": p.prob,
            "method": p.method,
            "model_version": p.model_version,
        }
        for p in state.repo.get_tag_probs(track_id)
        if state.stored_tags.accepts(p.head, p.model_version)
    ]
    return {
        **track_summary(track),
        "source_id": track.source_id,
        "album": track.album,
        "release_date": track.release_date,
        "source_url": track.source_url,
        "image_url": track.image_url,
        "vocal_instrumental": track.vocal_instrumental,
        "local_path": track.local_path if track.source == "local" else None,
        "stream_url": f"/api/tracks/{track.id}/stream",
        "download_url": track.download_url if track.audiodownload_allowed else None,
        "features": state.repo.get_features(track_id),
        "tags": tags,
        "license": {
            "code": track.license_code,
            "url": track.license_url,
            "family": track.license_family,
            "risk": track.risk,
            "commercial_ok": track.commercial_ok,
            "derivatives_ok": track.derivatives_ok,
            "share_alike": track.share_alike,
            "attribution_required": track.attribution_required,
            "attribution_text": track.attribution_text,
            "commercial_license_url": track.commercial_license_url,
        },
    }


# -- audio -----------------------------------------------------------------------------------


def _fresh_jamendo_url(state: AppState, track: StoredTrack) -> str:
    cached = state.stream_urls.get(track.id)
    if cached is not None:
        return cached
    try:
        client = state.open_jamendo()
    except (JamendoError, SecretError):
        raise HTTPException(status_code=503, detail="Jamendo client id is not set") from None
    try:
        found = client.get_tracks([track.source_id])
    except JamendoError as exc:  # the message is already redacted by the client
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception as exc:  # never relay a message that could carry the request URL
        raise HTTPException(
            status_code=502, detail=f"could not reach Jamendo ({type(exc).__name__})"
        ) from None
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            close()
    url = found[0].stream_url if found else None
    if not url:
        raise LookupError("the track is no longer available on Jamendo")
    if urlsplit(url).scheme not in ("http", "https"):
        raise HTTPException(status_code=502, detail="Jamendo returned an unusable stream URL")
    state.stream_urls.put(track.id, url)
    return url


def _local_file(track: StoredTrack) -> FileResponse:
    path = Path(track.local_path) if track.local_path else None
    if path is None or not path.is_file():
        raise LookupError("the audio file is missing; has it moved?")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.get("/api/tracks/{track_id}/stream", response_model=None)
def stream(track_id: int, state: StateDep) -> Response:
    track = _track(state, track_id)
    if track.source == "local":
        return _local_file(track)
    if track.source == "jamendo":
        return RedirectResponse(_fresh_jamendo_url(state, track), status_code=307)
    raise LookupError("this track has no playable audio")


# -- credits ---------------------------------------------------------------------------------


@router.get("/api/tracks/{track_id}/credits")
def credits(
    track_id: int,
    state: StateDep,
    fmt: Annotated[Literal["txt", "md", "json"], Query(alias="format")] = "txt",
) -> Response:
    track = _track(state, track_id)
    stem = safe_stem(track.title, "track")
    return credits_download(track_credits(track, fmt), fmt, stem=stem, suffix="license")
