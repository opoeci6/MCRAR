"""What a search returns: ``SearchItem`` per track and the ``SearchResult`` around them.

Everything is plain data; ``to_dict()`` gives a JSON-serialisable structure (the API and
``mcrar search --json`` use it).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mcrar.recommend.query import ParsedQuery


@dataclass(frozen=True)
class TagScore:
    label_set: str
    label: str
    display: str
    score: float


@dataclass(frozen=True)
class SearchItem:
    track_id: int
    title: str | None
    artist: str | None
    source: str
    source_url: str | None
    download_url: str | None  # only when the licence/source allows downloading
    duration_s: float | None
    bpm: float | None
    key: str | None
    mode: str | None
    energy: float | None
    license_code: str | None
    risk: str
    license_url: str | None
    attribution_text: str | None
    commercial_license_url: str | None
    top_tags: list[TagScore]
    score: float
    breakdown: dict[str, dict[str, float | None]]
    explanation: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchQuality:
    """How well the catalog matched the query text. ``top_cosine`` is the highest raw cosine
    similarity (not the min-max normalised score, which is always 1.0 for the top hit) of the
    ranked candidates of the final attempt; None without text or when nothing was ranked.
    ``weak`` says the text matched poorly (or nothing was ranked), judged against the
    ``search.weak_cosine`` threshold; it is never set for a filter-only search or an embedder
    with no known threshold."""

    top_cosine: float | None = None
    weak: bool = False


@dataclass(frozen=True)
class SearchResult:
    """``total_candidates`` is the number of ranked candidates (after the per-artist cap) that
    ``offset`` and ``limit`` page through. ``parsed`` is the query as understood, before any
    relaxation; ``relaxed`` says what was relaxed to find results, in order. ``notes`` carries
    messages for the user (missing embeddings, an empty result and why)."""

    items: list[SearchItem]
    total_candidates: int
    parsed: ParsedQuery
    relaxed: list[str]
    unembedded_count: int
    model_id: str
    elapsed_ms: float
    notes: list[str] = field(default_factory=list)
    match: MatchQuality = field(default_factory=MatchQuality)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
