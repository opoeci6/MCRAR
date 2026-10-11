"""Music sources: Jamendo (remote search, metadata, audio) and local folders."""

from mcrar.sources.base import SourceTrack
from mcrar.sources.jamendo import (
    JamendoAuthError,
    JamendoClient,
    JamendoError,
    JamendoRateLimitError,
    JamendoStreamError,
    parse_track,
)
from mcrar.sources.local_folder import LocalItem, scan_local

__all__ = [
    "JamendoAuthError",
    "JamendoClient",
    "JamendoError",
    "JamendoRateLimitError",
    "JamendoStreamError",
    "LocalItem",
    "SourceTrack",
    "parse_track",
    "scan_local",
]
