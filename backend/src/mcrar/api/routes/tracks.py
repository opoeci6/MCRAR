"""Catalog tracks: list, detail, audio stream and credits download.

Audio is never proxied. A Jamendo track answers with a 307 redirect to a fresh stream URL (the
stored one expires, so it is looked up again and kept in memory for 30 minutes). A Freesound
track answers with a 307 redirect to its stored preview URL (stable, no API call and no key), but
only when that is an https URL on freesound.org, else 404. A local track
is served from the file path stored in the catalog, with HTTP Range support (Starlette's
``FileResponse`` answers ``Range`` with 206), and no request ever supplies a path.

A track can be removed from the catalog (``DELETE /api/tracks/{id}``, 409 while a job runs). Its
ratings, labels and shortlist entries go with it. Its audio file is deleted too, but only when it
is a copy inside the library folder (``<data_dir>/library``); a file anywhere else is never
touched. ``GET /api/tracks/{id}/removal`` says what a removal would take along, and
``/api/tracks/missing`` and ``/api/tracks/remove-missing`` list and remove the local tracks whose
file is gone.
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from mcrar.api.routes._files import credits_download, safe_stem
from mcrar.api.routes.library_files import library_dir
from mcrar.api.state import AppState, StateDep
from mcrar.catalog import StoredTrack
from mcrar.licensing import attribution_text, stored_attribution_extra, track_credits
from mcrar.recommend.request import SOURCES
from mcrar.secrets import SecretError
from mcrar.sources import JamendoError
from mcrar.sources.freesound import is_freesound_https
from mcrar.sources.local_folder import parse_override

router = APIRouter()
log = logging.getLogger(__name__)

MISSING_LIST_LIMIT = 200
JOB_RUNNING_MESSAGE = "A job is running; try again when it has finished."


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


def track_links(track: StoredTrack) -> dict[str, Any]:
    """Where the track lives and what its licence asks for: the fields a result row, a track page
    and a shortlist entry share. ``download_url`` is only given when the source allows it."""
    return {
        "source_id": track.source_id,
        "source_url": track.source_url,
        "download_url": track.download_url if track.audiodownload_allowed else None,
        "license_url": track.license_url,
        "commercial_license_url": track.commercial_license_url,
        "attribution_text": track.attribution_text,
    }


@router.get("/api/tracks")
def list_tracks(
    state: StateDep,
    source: str | None = None,
    risk: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    if source is not None and source not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(SOURCES)}")
    if risk is not None and risk not in ("green", "amber", "red", "unknown"):
        raise ValueError("risk must be one of: green, amber, red, unknown")
    tracks, total = state.repo.list_tracks(
        source=source, risk=risk, limit=limit, offset=offset, q=(q or "").strip() or None
    )
    return {
        "items": [track_summary(t) for t in tracks],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# -- removing tracks ---------------------------------------------------------------------------


def _is_missing(track: StoredTrack) -> bool:
    """A local track whose audio file is gone (no path stored, or not a file). A file that cannot
    be checked is not counted as missing."""
    if track.source != "local":
        return False
    if not track.local_path:
        return True
    try:
        return not Path(track.local_path).is_file()
    except OSError:
        return False


def _library_file(state: AppState, track: StoredTrack) -> Path | None:
    """The track's file when it is a copy inside the library folder, else None."""
    if track.source != "local" or not track.local_path:
        return None
    root = library_dir(state.settings).resolve()
    try:
        path = Path(track.local_path).resolve()
    except (OSError, RuntimeError):
        return None
    return path if root in path.parents else None


def _remove_track(state: AppState, track: StoredTrack) -> None:
    """Delete the track row (and what hangs on it) and, if it is a library copy, its file."""
    file = _library_file(state, track)
    state.repo.delete_track(track.id)
    state.stream_urls.discard(track.id)
    if file is not None:
        try:
            file.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # the track is gone from the catalog: do not fail the request
            log.warning("could not delete library file of track %d: %s", track.id, exc)


def _while_idle(state: AppState, action: Callable[[], None]) -> None:
    """Run ``action`` unless a job runs (409); no job can start while it runs."""
    if not state.jobs.run_if_idle(action):
        raise HTTPException(status_code=409, detail=JOB_RUNNING_MESSAGE)


@router.get("/api/tracks/missing")
def missing_tracks(state: StateDep) -> dict[str, Any]:
    """Local tracks whose audio file is gone: the exact ``count`` and up to 200 of them."""
    missing = [t for t in state.repo.iter_tracks("local") if _is_missing(t)]
    return {
        "count": len(missing),
        "tracks": [
            {"id": t.id, "title": t.title, "local_path": t.local_path}
            for t in missing[:MISSING_LIST_LIMIT]
        ],
    }


@router.post("/api/tracks/remove-missing")
def remove_missing_tracks(state: StateDep) -> dict[str, int]:
    """Remove the local tracks whose audio file is still gone (checked again here)."""
    removed = 0

    def action() -> None:
        nonlocal removed
        for track in state.repo.iter_tracks("local"):
            if _is_missing(track):
                _remove_track(state, track)
                removed += 1

    _while_idle(state, action)
    return {"removed": removed}


@router.get("/api/tracks/{track_id}/removal")
def removal_preview(track_id: int, state: StateDep) -> dict[str, Any]:
    """What removing the track would also delete: its ratings, scene labels, the projects whose
    shortlist has it and whether its audio file is a copy that would be deleted."""
    track = _track(state, track_id)
    return {
        **state.repo.track_user_data(track_id),
        "copied_file": _library_file(state, track) is not None,
    }


@router.delete("/api/tracks/{track_id}", status_code=204, response_model=None)
def remove_track(track_id: int, state: StateDep) -> Response:
    track = _track(state, track_id)
    _while_idle(state, lambda: _remove_track(state, track))
    return Response(status_code=204)


class LicenseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    license: Annotated[str, Field(min_length=1, max_length=200)]


@router.put("/api/tracks/{track_id}/license")
def set_license(track_id: int, body: LicenseBody, state: StateDep) -> dict[str, Any]:
    """Declare the licence of a local track (a code or URL, or ``unknown``).

    The credit line is built again with the track's own title, artist and source URL; the text a
    sidecar added after it is kept. A licence set here survives adding the same file again, except
    ``unknown``, which hands the licence back to the folder (its sidecar) on the next add.
    """
    track = _track(state, track_id)
    if track.source != "local":
        raise ValueError("The licence of a Jamendo or Freesound track comes from the source.")
    info = parse_override(body.license)
    assert info is not None

    def action() -> None:
        current = _track(state, track_id)  # read again: no job can change it from here on
        text = attribution_text(
            title=current.title or "Untitled",
            artist=current.artist,
            license=info,
            source_url=current.source_url,
            extra=stored_attribution_extra(current) or None,
        )
        state.repo.set_track_license(track_id, info, text, set_by_user=info.family != "unknown")

    _while_idle(state, action)
    return track_detail(track_id, state)


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
        **track_links(track),
        "album": track.album,
        "release_date": track.release_date,
        "image_url": track.image_url,
        "vocal_instrumental": track.vocal_instrumental,
        "local_path": track.local_path if track.source == "local" else None,
        "stream_url": f"/api/tracks/{track.id}/stream",
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
            "set_by_user": track.license_set_by_user,
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
    if track.source == "freesound":
        # The preview URL on the Freesound CDN is stable and needs no key: redirect to the
        # stored one, but never to a URL that is not https on freesound.org.
        if not track.stream_url or not is_freesound_https(track.stream_url):
            raise LookupError("this track has no playable audio")
        return RedirectResponse(track.stream_url, status_code=307)
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
