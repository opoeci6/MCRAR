"""Build ``SearchFilters`` from user-facing arguments; shared by the CLI and the HTTP API.

Both front ends validate the same way: the licence risk, sources and intensity against fixed
choices, genre, mood and scene names against the vocabulary, and numeric ranges for order. They
differ only in how they spell an argument in an error message (``--max-risk`` vs ``max_risk``),
which the ``arg`` callable controls. All problems are raised as ``ValueError`` with a message fit
for the user.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from mcrar.recommend.query import SearchFilters
from mcrar.recommend.vocab import GENRE, MOODTHEME, SCENE, Vocabulary

SOURCES = ("jamendo", "freesound", "local")
RISKS = ("green", "amber", "red")  # "unknown" (the default) is the loosest level and is implicit
VOCALS = ("vocal", "instrumental")
INTENSITIES = ("low", "mid", "high")
BPM_SPREAD = 10.0  # a single BPM value N means N +- this
_RANGE = r"\s*(\d+(?:\.\d+)?)?\s*(-)?\s*(\d+(?:\.\d+)?)?\s*"

Range = tuple[float | None, float | None]


def plain_name(name: str) -> str:
    return name


def flag_name(name: str) -> str:
    """The CLI spelling of an argument: ``max_risk`` -> ``--max-risk``."""
    return "--" + name.replace("_", "-")


def parse_range(value: str | None, name: str, *, single_is_max: bool) -> Range:
    """Parse ``A-B``, ``A-``, ``-B`` or ``N`` (``N`` alone: max if ``single_is_max``, else N±10).

    ``name`` is the CLI option (``bpm``), shown as ``--bpm`` in the messages.
    """
    if value is None:
        return None, None
    m = re.fullmatch(_RANGE, value)
    if m is None or (m.group(1) is None and m.group(3) is None):
        raise ValueError(f"--{name} must look like 80-100 or 90, got '{value}'")
    low = float(m.group(1)) if m.group(1) else None
    high = float(m.group(3)) if m.group(3) else None
    if m.group(2) is None:  # a single number
        if single_is_max:
            return None, low
        return max((low or 0.0) - BPM_SPREAD, 0.0), (low or 0.0) + BPM_SPREAD
    if low is not None and high is not None and low > high:
        raise ValueError(f"--{name}: the first number must not exceed the second, got '{value}'")
    return low, high


def _checked_range(bounds: Range, low_name: str, high_name: str) -> Range:
    low, high = bounds
    for name, value in ((low_name, low), (high_name, high)):
        if value is not None and value < 0:
            raise ValueError(f"{name} must not be negative")
    if low is not None and high is not None and low > high:
        raise ValueError(f"{low_name} must not exceed {high_name}")
    return bounds


def build_filters(
    vocab: Vocabulary,
    *,
    genres: Sequence[str] = (),
    moods: Sequence[str] = (),
    scenes: Sequence[str] = (),
    intensity: str | None = None,
    bpm: Range = (None, None),
    duration: Range = (None, None),
    max_risk: str | None = None,
    vocal: str | None = None,
    sources: Sequence[str] | None = None,
    arg: Callable[[str], str] = plain_name,
) -> SearchFilters:
    """Validate the arguments and return the filters.

    ``genres``/``moods``/``scenes`` are names (ids, display names or synonyms) resolved to label
    ids, ``intensity`` is ``low``, ``mid`` or ``high``, ``bpm`` and ``duration`` are
    ``(min, max)`` pairs (seconds for the duration), and an empty ``sources`` means every
    source. Raises ``ValueError`` on the first problem.
    """
    if max_risk is not None and max_risk not in RISKS:
        raise ValueError(f"{arg('max_risk')} must be one of: {', '.join(RISKS)}")
    if vocal is not None and vocal not in VOCALS:
        raise ValueError(f"{arg('vocal')} must be one of: {', '.join(VOCALS)}")
    for source in sources or ():
        if source not in SOURCES:
            raise ValueError(f"{arg('source')} must be one of: {', '.join(SOURCES)}")
    resolved_genres = vocab.resolve(GENRE, genres)
    resolved_moods = vocab.resolve(MOODTHEME, moods)
    resolved_scenes = vocab.resolve(SCENE, scenes)
    if intensity is not None and intensity not in INTENSITIES:
        raise ValueError(f"{arg('intensity')} must be one of: {', '.join(INTENSITIES)}")
    bpm_min, bpm_max = _checked_range(bpm, arg("bpm_min"), arg("bpm_max"))
    dur_min, dur_max = _checked_range(duration, arg("duration_min_s"), arg("duration_max_s"))
    return SearchFilters(
        max_risk=max_risk or "unknown",  # type: ignore[arg-type]
        vocal=vocal,  # type: ignore[arg-type]
        bpm_min=bpm_min,
        bpm_max=bpm_max,
        duration_min_s=dur_min or None,
        duration_max_s=dur_max,
        sources=tuple(dict.fromkeys(sources)) if sources else None,
        genres=resolved_genres,
        moods=resolved_moods,
        scenes=resolved_scenes,
        intensity=intensity,  # type: ignore[arg-type]
    )
