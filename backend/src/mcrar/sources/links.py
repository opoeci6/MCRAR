"""Track links: the Jamendo and Freesound ids in pasted text.

Entries are separated by newlines, commas or whitespace. Accepted forms (http or https, with or
without the scheme, optional ``www.``, query string and fragment ignored, trailing slash
optional, ids digits only):

- Jamendo: ``jamendo.com/track/<id>`` (optionally ``/<slug>`` and a language segment such as
  ``/en/track/<id>``), ``licensing.jamendo.com/track/<id>``, ``jamen.do/t/<id>``
- Freesound: ``freesound.org/people/<user>/sounds/<id>/``, ``freesound.org/s/<id>/``
- bare ``jamendo:<id>`` and ``freesound:<id>``

The host is compared exactly (no substring match, no user info or port), so look-alikes such as
``jamendo.com.evil.test`` or ``freesound.org@evil.test`` are invalid. Nothing here touches the
network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_LINKS = 50  # valid ids in one request

_ID = re.compile(r"[0-9]{1,15}")
_LANGUAGE = re.compile(r"[a-z]{2}")
_BARE = re.compile(r"(jamendo|freesound):([0-9]{1,15})", re.IGNORECASE)
_JAMENDO_HOSTS = frozenset({"jamendo.com", "licensing.jamendo.com"})
_SEPARATORS = re.compile(r"[\s,]+")


@dataclass(frozen=True)
class TrackLinks:
    """The ids found, by source, in the order given and without repeats; ``invalid`` holds the
    entries that are not a track link (as written)."""

    jamendo: list[str]
    freesound: list[str]
    invalid: list[str]


def _jamendo_id(host: str, segments: list[str]) -> str | None:
    if host == "jamen.do":
        return segments[1] if len(segments) == 2 and segments[0] == "t" else None
    if host in _JAMENDO_HOSTS:
        if segments and _LANGUAGE.fullmatch(segments[0]):
            segments = segments[1:]
        if len(segments) in (2, 3) and segments[0] == "track":
            return segments[1]
    return None


def _freesound_id(host: str, segments: list[str]) -> str | None:
    if host != "freesound.org":
        return None
    if len(segments) == 2 and segments[0] == "s":
        return segments[1]
    if len(segments) == 4 and segments[0] == "people" and segments[2] == "sounds":
        return segments[3]
    return None


def _parse_entry(entry: str) -> tuple[str, str] | None:
    """``(source, id)`` for one entry, or None when it is not a track link."""
    bare = _BARE.fullmatch(entry)
    if bare:
        return bare.group(1).lower(), str(int(bare.group(2)))
    try:
        parts = urlsplit(entry if "://" in entry else f"https://{entry}")
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = parts.netloc.lower().removeprefix("www.")  # netloc: user info or a port never match
    segments = [s for s in parts.path.split("/") if s]
    for source, find in (("jamendo", _jamendo_id), ("freesound", _freesound_id)):
        found = find(host, segments)
        if found is not None:
            return (source, str(int(found))) if _ID.fullmatch(found) else None
    return None


def parse_track_links(text: str) -> TrackLinks:
    """The track ids in ``text`` (see the module docstring). More than :data:`MAX_LINKS` valid
    ids raises ``ValueError``."""
    jamendo: list[str] = []
    freesound: list[str] = []
    invalid: list[str] = []
    for entry in _SEPARATORS.split(text.strip()):
        if not entry:
            continue
        parsed = _parse_entry(entry)
        if parsed is None:
            if entry not in invalid:
                invalid.append(entry)
            continue
        source, track_id = parsed
        ids = jamendo if source == "jamendo" else freesound
        if track_id not in ids:
            ids.append(track_id)
    if len(jamendo) + len(freesound) > MAX_LINKS:
        raise ValueError(f"at most {MAX_LINKS} tracks per request")
    return TrackLinks(jamendo=jamendo, freesound=freesound, invalid=invalid)
