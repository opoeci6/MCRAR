"""The labelling pool (M9): which catalog tracks get hand-labelled, in which order, by whom.

The pool has two kinds of tracks:

- For every zero-shot scene entry in the registry and every scene, the ``per_scene`` tracks with
  the highest zero-shot probability (reason ``top:<scene>:<variant>``). These are where the
  entries disagree or agree, which is what the labels have to settle. A track keeps the reason
  it got first (entries from the lowest centering up, scenes in label order), so a track that
  tops several lists is in the pool once.
- ``random_n`` other tracks drawn at random (reason ``random``), so there are positives and
  negatives the models did not pick.

The scores are computed here from the entries' artifacts on the catalog's CLAP embeddings (numpy
only), so the pool needs ``mcrar scenes build`` and ``mcrar embed``, not ``mcrar tag``. The whole
pool is then shuffled (one seeded permutation, so no part and no start is front-loaded with one
scene) and numbered from 1. ``both_n`` tracks spread evenly over the order are ``both`` (labelled
by both people, to measure agreement); the rest alternate between parts ``A`` and ``B``. The
result is a pure function of the scores and the seed.

The reasons are kept out of the labelling page on purpose: a labeller who sees "top boss" is
biased towards agreeing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np

from mcrar.catalog import CatalogRepository, PoolEntry
from mcrar.config import Settings
from mcrar.ml.datasets.embedding import EMBEDDER
from mcrar.ml.tagging.scene_head import probability_matrix, zeroshot_entries

PER_SCENE = 10
RANDOM_N = 100
BOTH_N = 30


def build_pool(
    repo: CatalogRepository,
    settings: Settings,
    *,
    per_scene: int = PER_SCENE,
    random_n: int = RANDOM_N,
    both_n: int = BOTH_N,
    seed: int = 0,
) -> list[PoolEntry]:
    """The pool entries (not stored; see :func:`save_pool`). Raises ``ValueError`` when there is
    no scene entry or no CLAP embedding to score."""
    if per_scene < 0 or random_n < 0 or both_n < 0:
        raise ValueError("per-scene, random and both counts must not be negative")
    entries = zeroshot_entries(settings)  # raises with a pointer to mcrar scenes build
    ids, matrix = repo.load_embeddings(EMBEDDER)
    if len(ids) == 0:
        raise ValueError(f"the catalog has no {EMBEDDER} embeddings; run: mcrar embed")
    ids = ids.astype(np.int64)  # ascending (load_embeddings orders by track id)
    chosen: dict[int, str] = {}
    for entry, tagger in entries:
        probs = probability_matrix(tagger, matrix)
        for j, scene in enumerate(tagger.labels):
            order = np.lexsort((ids, -probs[:, j]))  # best first, ties by track id
            for index in order[:per_scene]:
                chosen.setdefault(int(ids[index]), f"top:{scene}:{entry['variant']}")
    others = np.array([int(t) for t in ids if int(t) not in chosen], dtype=np.int64)
    rng = np.random.default_rng(seed)
    if random_n and len(others):
        picked = rng.choice(others, size=min(random_n, len(others)), replace=False)
        for track_id in sorted(int(t) for t in picked):
            chosen[track_id] = "random"
    if not chosen:
        raise ValueError("the pool would be empty")
    order = rng.permutation(len(chosen))
    tracks = list(chosen.items())
    shuffled = [tracks[i] for i in order]
    n = len(shuffled)
    both = {int((i + 0.5) * n / both_n) for i in range(both_n)} if both_n < n else set(range(n))
    pool: list[PoolEntry] = []
    alternate = 0
    for position, (track_id, reason) in enumerate(shuffled, start=1):
        if position - 1 in both:
            part = "both"
        else:
            part = "AB"[alternate % 2]
            alternate += 1
        pool.append(PoolEntry(track_id, position, reason, part))
    return pool


def save_pool(repo: CatalogRepository, pool: list[PoolEntry], *, force: bool = False) -> int:
    """Store the pool; refuses to replace an existing one unless ``force`` (the labels are per
    track, so they survive either way)."""
    existing = repo.label_pool()
    if existing and not force:
        raise ValueError(
            f"a labelling pool of {len(existing)} tracks already exists; use --force to replace "
            "it (hand labels are kept: they belong to tracks, not to the pool)"
        )
    return repo.replace_label_pool(pool)


@dataclass(frozen=True)
class PoolSummary:
    size: int
    parts: dict[str, int]
    reasons: dict[str, int]


def summarise_pool(pool: list[PoolEntry]) -> PoolSummary:
    """Counts per part (``A``, ``B``, ``both``) and per reason, reasons sorted by name."""
    parts = Counter(e.part for e in pool)
    reasons = Counter(e.reason for e in pool)
    return PoolSummary(
        len(pool),
        {p: parts.get(p, 0) for p in ("A", "B", "both")},
        dict(sorted(reasons.items())),
    )
