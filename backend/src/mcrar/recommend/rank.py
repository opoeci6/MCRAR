"""Weighted ranking with a score breakdown, and artist diversity.

Each active term is in [0, 1]:

- ``semantic``: min-max of the cosine over the candidate pool (1.0 when all candidates tie).
- ``tags``: mean score of the requested genre/mood labels (scores come from a tag scorer).
- ``bpm``: ``exp(-((b - target) / 15) ** 2)``, where ``b`` is the best of the tempo, half of it
  and double of it when the tempo's confidence is low (< 0.5) because it may be off by an octave.
- ``energy``: ``1 - |energy - target|``.

A term is *active* when the query has that kind of preference or text; the weights of the active
terms are rescaled to sum to 1, so ``score = sum(weight * term)`` stays in [0, 1] and the
contributions in the breakdown add up to the score. A track that lacks the data for an active
term (no BPM, no energy) gets 0 for that term. With no active term every score is 0 and the
order is by licence risk, then track id. Ties break by risk (green first), then by the smaller
track id.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from mcrar.licensing import RISK_ORDER

if TYPE_CHECKING:
    from mcrar.config import SearchWeights

TERMS = ("semantic", "tags", "bpm", "energy")
BPM_SCALE = 15.0
BPM_LOW_CONFIDENCE = 0.5
SORT_DECIMALS = 9  # scores equal to this many decimals count as ties (float noise)


@dataclass(frozen=True)
class TermScore:
    """One term of the breakdown. ``raw`` is None for an inactive term (weight 0)."""

    raw: float | None
    weight: float
    contribution: float


@dataclass(frozen=True)
class ScoreBreakdown:
    terms: Mapping[str, TermScore]

    @property
    def score(self) -> float:
        return float(sum(t.contribution for t in self.terms.values()))

    def to_dict(self) -> dict[str, dict[str, float | None]]:
        return {
            name: {"raw": t.raw, "weight": t.weight, "contribution": t.contribution}
            for name, t in self.terms.items()
        }


@dataclass(frozen=True)
class Candidate:
    """What the ranking needs to know about one track."""

    track_id: int
    artist: str | None = None
    risk: str = "unknown"  # licence risk: breaks ties, safer first
    cosine: float | None = None  # similarity to the query text (None without a text query)
    bpm: float | None = None
    bpm_confidence: float | None = None
    energy: float | None = None
    tags: Sequence[float] = field(default_factory=tuple)  # score per requested label


@dataclass(frozen=True)
class Ranked:
    track_id: int
    score: float
    breakdown: ScoreBreakdown


def minmax(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Scale to [0, 1]; when every value is the same (or there is one) all become 1.0."""
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return arr
    low, high = float(arr.min()), float(arr.max())
    if high - low <= 1e-12:
        return np.ones_like(arr)
    return (arr - low) / (high - low)


def bpm_term(bpm: float | None, confidence: float | None, target: float) -> float:
    """How close a track's tempo is to ``target`` (1 at the target, ~0.37 at 15 BPM away)."""
    if bpm is None:
        return 0.0
    candidates = [bpm]
    if confidence is None or confidence < BPM_LOW_CONFIDENCE:
        candidates += [bpm / 2, bpm * 2]
    best = min(abs(b - target) for b in candidates)
    return math.exp(-((best / BPM_SCALE) ** 2))


def energy_term(energy: float | None, target: float) -> float:
    if energy is None:
        return 0.0
    return min(max(1.0 - abs(energy - target), 0.0), 1.0)


def effective_weights(weights: SearchWeights, active: Collection[str]) -> dict[str, float]:
    """The configured weights of the active terms rescaled to sum to 1 (0 for inactive terms).

    If the active terms all have weight 0 they share the weight equally."""
    base = {name: float(getattr(weights, name)) if name in active else 0.0 for name in TERMS}
    total = sum(base.values())
    if total <= 0:
        share = 1.0 / len(active) if active else 0.0
        return {name: (share if name in active else 0.0) for name in TERMS}
    return {name: value / total for name, value in base.items()}


def _risk_rank(risk: str) -> int:
    return RISK_ORDER.index(risk) if risk in RISK_ORDER else len(RISK_ORDER)


def _artist_key(artist: str | None) -> str | None:
    key = (artist or "").strip().casefold()
    return key or None


def rank_candidates(
    candidates: Sequence[Candidate],
    *,
    weights: SearchWeights,
    semantic: bool,
    tags: bool,
    bpm_target: float | None = None,
    energy_target: float | None = None,
    max_per_artist: int | None = None,
) -> list[Ranked]:
    """Score, order and diversify the candidates (best first).

    ``semantic`` and ``tags`` tell whether the query has text / requested labels (then every
    candidate carries ``cosine`` / ``tags``). Order: score descending, then licence risk (green
    first), then track id. With ``max_per_artist`` an artist's tracks beyond that count are
    demoted behind every in-cap track (keeping their relative order), so the next best tracks of
    other artists move up but nothing is lost. Tracks without an artist are never capped.
    """
    active = [
        name
        for name, on in (
            ("semantic", semantic),
            ("tags", tags),
            ("bpm", bpm_target is not None),
            ("energy", energy_target is not None),
        )
        if on
    ]
    weight = effective_weights(weights, active)
    cosines = minmax([c.cosine or 0.0 for c in candidates]) if semantic else None

    scored: list[Ranked] = []
    for i, cand in enumerate(candidates):
        raw: dict[str, float | None] = dict.fromkeys(TERMS)
        if cosines is not None:
            raw["semantic"] = float(cosines[i])
        if tags:
            raw["tags"] = float(np.mean(cand.tags)) if len(cand.tags) else 0.0
        if bpm_target is not None:
            raw["bpm"] = bpm_term(cand.bpm, cand.bpm_confidence, bpm_target)
        if energy_target is not None:
            raw["energy"] = energy_term(cand.energy, energy_target)
        terms = {
            name: TermScore(
                raw[name], weight[name], weight[name] * raw[name] if raw[name] is not None else 0.0
            )
            for name in TERMS
        }
        breakdown = ScoreBreakdown(terms)
        scored.append(Ranked(cand.track_id, breakdown.score, breakdown))

    risks = {c.track_id: _risk_rank(c.risk) for c in candidates}
    scored.sort(key=lambda r: (-round(r.score, SORT_DECIMALS), risks[r.track_id], r.track_id))
    if max_per_artist is None:
        return scored
    artists = {c.track_id: _artist_key(c.artist) for c in candidates}
    counts: dict[str, int] = {}
    kept: list[Ranked] = []
    demoted: list[Ranked] = []
    for ranked in scored:
        artist = artists[ranked.track_id]
        if artist is not None:
            if counts.get(artist, 0) >= max_per_artist:
                demoted.append(ranked)
                continue
            counts[artist] = counts.get(artist, 0) + 1
        kept.append(ranked)
    return kept + demoted
