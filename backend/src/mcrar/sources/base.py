"""Source-neutral track record. No licensing logic and no catalog ids live here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceTrack:
    """One track as reported by a remote source, normalised across sources.

    ``stream_url`` may be a signed, expiring URL: treat stored values as refreshable
    (re-fetch the track by id to get a new one). ``license_url`` is the raw license link as
    given by the source; interpreting it is the licensing module's job.
    """

    source: str
    source_id: str
    title: str
    artist: str | None
    album: str | None = None
    duration_s: float | None = None
    release_date: str | None = None
    source_url: str | None = None  # human-facing page of the track
    stream_url: str | None = None
    download_url: str | None = None  # None when downloads are not allowed
    audiodownload_allowed: bool = False
    license_url: str | None = None
    commercial_license_url: str | None = None  # where a commercial license can be obtained
    image_url: str | None = None
    vocal_instrumental: str | None = None  # "vocal" | "instrumental" | None
    tags: Mapping[str, object] = field(default_factory=dict)
    local_path: str | None = None
