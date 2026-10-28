"""Music sources: Jamendo and Freesound (remote search, metadata, audio) and local folders."""

from mcrar.sources.base import SourceTrack
from mcrar.sources.freesound import (
    FreesoundAuthError,
    FreesoundClient,
    FreesoundError,
    FreesoundRateLimitError,
    FreesoundStreamError,
    parse_sound,
)
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
    "FreesoundAuthError",
    "FreesoundClient",
    "FreesoundError",
    "FreesoundRateLimitError",
    "FreesoundStreamError",
    "JamendoAuthError",
    "JamendoClient",
    "JamendoError",
    "JamendoRateLimitError",
    "JamendoStreamError",
    "LocalItem",
    "SourceTrack",
    "parse_sound",
    "parse_track",
    "scan_local",
]
