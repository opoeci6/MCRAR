"""Template explanations: one line built from the score breakdown and the track.

Only meaningful parts are listed: what the text match was like, how close the track sounds to
the reference song, each thing the query asked for with the track's value next to it, and always
the licence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mcrar.catalog import StoredTrack
from mcrar.recommend.query import ParsedQuery
from mcrar.recommend.rank import ScoreBreakdown

CLOSE, GOOD = 0.75, 0.4  # thresholds on the normalised semantic term
# (close, similar) thresholds on the raw cosine between a track and the reference song, per
# embedder key. Audio-audio cosines sit on a different scale per model, so they were measured on
# the owner's catalog (1,054 tracks, 2026-10-26): "close" is about a track's few nearest
# neighbours, "similar" about its nearest 50. A model without bands gets no strength word.
REFERENCE_BANDS: dict[str, tuple[float, float]] = {
    "clap": (0.80, 0.65),
    "glap": (0.93, 0.88),
    "muq-mulan": (0.80, 0.62),
}
MAX_TEXT_CHARS = 60
MAX_TAGS_SHOWN = 3
CALM_BELOW, ENERGETIC_ABOVE = 0.45, 0.55


def _number(value: float) -> str:
    return f"{value:g}"


def _text(text: str) -> str:
    return text if len(text) <= MAX_TEXT_CHARS else text[: MAX_TEXT_CHARS - 3].rstrip() + "..."


def _asked_range(low: float | None, high: float | None, unit: str = "") -> str:
    if low is not None and high is not None:
        return f"{_number(low)}-{_number(high)}{unit}"
    if high is not None:
        return f"≤ {_number(high)}{unit}"
    return f"≥ {_number(low or 0)}{unit}"


def energy_word(target: float) -> str:
    if target < CALM_BELOW:
        return "calm"
    return "energetic" if target > ENERGETIC_ABOVE else "moderate"


def explain(
    track: StoredTrack,
    features: Mapping[str, Any] | None,
    breakdown: ScoreBreakdown,
    query: ParsedQuery,
    tag_scores: Sequence[tuple[str, float]] = (),
    reference: tuple[str, float] | None = None,
    reference_bands: tuple[float, float] | None = None,
) -> str:
    """The explanation line. ``tag_scores`` are the track's ``(label, score)`` for the requested
    labels; ``reference`` is the reference song's label and the track's raw cosine to it, worded
    by the search model's ``reference_bands`` (see :data:`REFERENCE_BANDS`)."""
    f, prefs = query.filters, query.preferences
    parts: list[str] = []

    semantic = breakdown.terms["semantic"].raw
    if semantic is not None and query.semantic_text:
        tier = "Close" if semantic >= CLOSE else "Good" if semantic >= GOOD else "Loose"
        parts.append(f'{tier} match for "{_text(query.semantic_text)}"')
    elif not any(t.raw is not None for t in breakdown.terms.values()):
        parts.append("Matches your filters")

    if reference is not None:
        label, cosine = reference
        if reference_bands is None:
            lead = "Sounds like"
        elif cosine >= reference_bands[0]:
            lead = "Sounds close to"
        elif cosine >= reference_bands[1]:
            lead = "Sounds similar to"
        else:
            lead = "Loosely like"
        parts.append(f"{lead} “{_text(label)}”")

    bpm = (features or {}).get("bpm")
    has_range = f.bpm_min is not None or f.bpm_max is not None
    if bpm is not None and (has_range or prefs.bpm_target is not None):
        asked = (
            _asked_range(f.bpm_min, f.bpm_max)
            if has_range
            else f"~{_number(round(prefs.bpm_target or 0))}"
        )
        parts.append(f"{round(bpm)} BPM ({asked} asked)")

    if f.duration_min_s is not None or f.duration_max_s is not None:
        if track.duration_s is not None:
            asked = _asked_range(f.duration_min_s, f.duration_max_s, " s")
            parts.append(f"{round(track.duration_s)} s ({asked} asked)")
        else:
            parts.append("duration unknown")

    if f.vocal is not None:
        parts.append(track.vocal_instrumental or "vocals unknown")

    energy = (features or {}).get("energy")
    if energy is not None and prefs.energy_target is not None:
        parts.append(f"energy {energy:.2f} ({energy_word(prefs.energy_target)} asked)")

    if tag_scores:
        top = sorted(tag_scores, key=lambda s: (-s[1], s[0]))[:MAX_TAGS_SHOWN]
        parts.append("tags " + ", ".join(f"{label} {score:.2f}" for label, score in top))

    if track.license_code:
        parts.append(f"{track.license_code} ({track.risk})")
    else:
        parts.append(f"licence {track.risk}")
    return " · ".join(parts)
