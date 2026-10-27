"""What a search returns: ``SearchItem`` per track and the ``SearchResult`` around them.

Everything is plain data; ``to_dict()`` gives a JSON-serialisable structure (the API and
``mcrar search --json`` use it).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

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
    bpm_confidence: float | None  # 0-1; below BPM_LOW_CONFIDENCE the tempo may be half or double
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
    llm_rank: int | None = None  # position after an LLM re-ranking (1 = best)
    llm_explanation: str | None = None

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
class LLMUse:
    """What the LLM did for one search: ``used`` is False when it failed and the rule parser
    answered instead (``error`` then says why, in safe words); ``cached`` when its reply for this
    query was reused."""

    used: bool
    model: str
    cached: bool = False
    error: str | None = None


@dataclass(frozen=True)
class RerankInfo:
    """The LLM's verdict on a re-ranked result list (see :mod:`mcrar.recommend.llm_rerank`)."""

    model: str
    verdict: Literal["good", "partial", "poor"]
    summary: str
    search_terms: list[str]
    elapsed_ms: float


@dataclass(frozen=True)
class ReferenceInfo:
    """The reference song a search was ranked by, as echoed to the client (never its vector)."""

    kind: Literal["track", "upload"]
    track_id: int | None
    label: str
    weight: float


@dataclass(frozen=True)
class SearchResult:
    """``total_candidates`` is the number of ranked candidates (after the per-artist cap) that
    ``offset`` and ``limit`` page through. ``parsed`` is the query as understood, before any
    relaxation; ``relaxed`` says what was relaxed to find results, in order. ``notes`` carries
    messages for the user (missing embeddings, an empty result and why). ``llm`` and ``rerank``
    are None unless the LLM took part; ``reference`` is None unless a reference song was used."""

    items: list[SearchItem]
    total_candidates: int
    parsed: ParsedQuery
    relaxed: list[str]
    unembedded_count: int
    model_id: str
    elapsed_ms: float
    notes: list[str] = field(default_factory=list)
    match: MatchQuality = field(default_factory=MatchQuality)
    llm: LLMUse | None = None
    rerank: RerankInfo | None = None
    reference: ReferenceInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
