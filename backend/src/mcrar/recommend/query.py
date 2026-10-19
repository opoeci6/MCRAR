"""The query model: what the user asked (``SearchRequest``) and what the parser understood
(``ParsedQuery``).

Hard filters remove tracks. Soft preferences (and genre/mood labels) only influence the ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mcrar.licensing import Risk

Vocal = Literal["vocal", "instrumental"]


@dataclass(frozen=True)
class SearchFilters:
    """Hard constraints, from the UI or the parser. ``None``/empty means "not set".

    ``max_risk="unknown"`` is the loosest level and filters nothing. ``genres`` and ``moods``
    are label ids; despite living here they are soft: they feed the tag term of the ranking.
    """

    max_risk: Risk = "unknown"
    vocal: Vocal | None = None
    bpm_min: float | None = None
    bpm_max: float | None = None
    duration_min_s: float | None = None
    duration_max_s: float | None = None
    sources: tuple[str, ...] | None = None
    genres: tuple[str, ...] = ()
    moods: tuple[str, ...] = ()


@dataclass(frozen=True)
class Preferences:
    """Soft preferences: they shape the score, never remove tracks."""

    energy_target: float | None = None  # 0 (calm) .. 1 (intense)
    bpm_target: float | None = None
    genre_hints: tuple[str, ...] = ()
    mood_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchRequest:
    text: str | None = None
    filters: SearchFilters = field(default_factory=SearchFilters)
    limit: int = 20
    offset: int = 0
    explain: bool = True


@dataclass(frozen=True)
class ParsedQuery:
    """``semantic_text`` is the text left after the hard-constraint phrases were removed
    (None when nothing descriptive remains). ``filters`` merges the UI filters (which win) with
    the parsed ones. ``notes`` says in words what the parser understood. ``source`` says which
    parser produced it; ``search_terms`` are Jamendo keywords the LLM parser suggests (never
    used for ranking, only to import tracks)."""

    semantic_text: str | None
    filters: SearchFilters
    preferences: Preferences
    notes: list[str] = field(default_factory=list)
    source: Literal["rules", "llm"] = "rules"
    search_terms: tuple[str, ...] = ()

    def requested_labels(self) -> list[tuple[str, str]]:
        """``(label set, label)`` pairs the tag term scores: UI labels first, then the hints."""
        pairs = [("genre", g) for g in (*self.filters.genres, *self.preferences.genre_hints)]
        pairs += [("moodtheme", m) for m in (*self.filters.moods, *self.preferences.mood_hints)]
        return list(dict.fromkeys(pairs))
