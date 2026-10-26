"""Tag scores for the ranking: ``TagScorer`` and its implementations.

``scores(track_ids, label_set, labels)`` returns, per label, an array aligned with ``track_ids``
with values in [0, 1].

- :class:`StoredTagScorer` reads the ``tag_probs`` rows written by the tagging models (M3b),
  optionally only those of the model version the current licence mode allows. The values are
  the raw probabilities, whose scale differs a lot per label and per model (a genre head is
  peaky, a zero-shot mood head says 0.6-0.97 for nearly everything).
- :class:`StandardisedTagScorer` puts those on one scale: per label, the stored probabilities
  of the tagged tracks of the catalog give a mean and a standard deviation, and a track scores
  ``sigmoid(1.7 * (p - mean) / std)``. The statistics are cached with a cheap signature of the
  head's rows, so tagging more tracks refreshes them. It never touches the embedder.
- :class:`ZeroShotTagScorer` is the fallback until a track is tagged: the cosine between the
  track's embedding and the text embedding of ``"<display name> music"`` (``"video game music for
  <display name>"`` for the scene set), standardised over the whole catalog and squashed with a
  sigmoid, so a score does not depend on the query's pool.
- :class:`CompositeTagScorer` uses stored rows for the tracks that have them and zero-shot for
  the rest.

Standardised stored and zero-shot scores are both a catalog z-score through the same sigmoid, in
(0, 1) and stable across queries: 0.5 means "an average track for this label". So they mix
sensibly while a catalog is only partly tagged, and the labels of different sets can be averaged.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

from mcrar.recommend.vocab import Vocabulary

if TYPE_CHECKING:
    from mcrar.catalog import CatalogRepository, NumpyVectorIndex
    from mcrar.config import Settings

PROMPT = "{} music"  # text prompt per label, filled with the label's display name
PROMPTS = {"scene": "video game music for {}"}  # label sets that need a phrase of their own
SLOPE = 1.7  # sigmoid slope on the z-score of a track's cosine
MIN_STD = 1e-9  # a smaller spread counts as none: every track scores 0.5

# Cached statistics: (the head's row signature, {label: (mean, std)})
_Stats = tuple[tuple[int, int | None, float], dict[str, tuple[float, float]]]


@runtime_checkable
class TagScorer(Protocol):
    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]: ...


class CoverageScorer(Protocol):
    """A scorer that also says which tracks it knows (see :class:`StoredTagScorer`)."""

    def scores_with_coverage(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> tuple[dict[str, np.ndarray], np.ndarray]: ...


def squash(z: np.ndarray) -> np.ndarray:
    """``sigmoid(SLOPE * z)``, safe for huge |z|, in [0, 1]."""
    return np.clip(1.0 / (1.0 + np.exp(-SLOPE * np.clip(z, -50.0, 50.0))), 0.0, 1.0)


def allowed_tag_versions(settings: Settings) -> dict[str, str | None]:
    """Per label set, the model version whose stored tags may be used.

    That is the tagging registry's selected entry; ``None`` when the set has no entry. Without a
    usable registry the mapping is empty, so no stored tag is trusted (rows written by a model
    that is no longer the selected one are ignored too).
    """
    from mcrar.ml.tagging.registry import read_registry, select_entry

    try:
        registry = read_registry(settings)
    except Exception:  # missing, unreadable or inconsistent registry: trust no stored tags
        return {}
    allowed: dict[str, str | None] = {}
    for name, spec in registry["label_sets"].items():
        entry = select_entry(spec)
        allowed[name] = entry["id"] if entry else None
    return allowed


class StoredTagScorer:
    """Probabilities stored in ``tag_probs`` under ``head == label_set``.

    ``allowed_versions`` (label set -> model version, see :func:`allowed_tag_versions`) limits
    the rows used to those of the allowed version; a set that is missing from it or maps to
    ``None`` has no usable rows, so :class:`CompositeTagScorer` falls back to zero-shot. ``None``
    accepts every row (direct use and tests).
    """

    def __init__(
        self,
        repo: CatalogRepository,
        allowed_versions: Mapping[str, str | None] | None = None,
    ) -> None:
        self._repo = repo
        self.allowed_versions = allowed_versions

    @property
    def repo(self) -> CatalogRepository:
        return self._repo

    def accepts(self, label_set: str, model_version: str | None) -> bool:
        if self.allowed_versions is None:
            return True
        allowed = self.allowed_versions.get(label_set)
        return allowed is not None and model_version == allowed

    def scores_with_coverage(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """The scores (0 where unknown) and a bool array: which tracks have rows for the set."""
        out = {label: np.zeros(len(track_ids)) for label in labels}
        covered = np.zeros(len(track_ids), dtype=bool)
        if self.allowed_versions is not None and self.allowed_versions.get(label_set) is None:
            return out, covered  # no version of this set is allowed: skip the query
        rows = self._repo.get_tag_probs_many(track_ids, heads=[label_set])
        for i, track_id in enumerate(track_ids):
            probs = [
                p for p in rows.get(int(track_id), ()) if self.accepts(label_set, p.model_version)
            ]
            if not probs:
                continue
            covered[i] = True
            for row in probs:
                if row.label in out:
                    out[row.label][i] = min(max(row.prob, 0.0), 1.0)
        return out, covered

    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]:
        return self.scores_with_coverage(track_ids, label_set, labels)[0]


class StandardisedTagScorer:
    """Stored probabilities, standardised per label over the catalog's tagged tracks.

    For a label set and the model version the licence allows (every row when the stored scorer
    accepts all), the tracks with rows are the covered tracks; per label, the mean and standard
    deviation of their probabilities (a covered track without a row for the label counts as 0)
    give the score ``sigmoid(1.7 * (p - mean) / std)``. So 0.5 is an average tagged track, the
    score does not depend on which other tracks are scored, and labels from different heads are
    comparable. If every covered track has the same probability (std 0) they all score 0.5; a
    label with no rows at all scores 0 (the head says nothing about it). Tracks without rows
    score 0 and stay uncovered, so :class:`CompositeTagScorer` gives them the zero-shot score.

    The statistics are cached per (label set, version) together with the head's row signature and
    recomputed when it changes; a lock guards the cache because searches run on several threads.
    This class only reads ``tag_probs``: it never loads the text model.
    """

    def __init__(self, stored: StoredTagScorer) -> None:
        self._stored = stored
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str | None], _Stats] = {}

    def _stats(self, label_set: str, version: str | None) -> dict[str, tuple[float, float]]:
        """``{label: (mean, std)}`` of the covered tracks; labels without rows are absent."""
        repo = self._stored.repo
        signature = repo.tag_probs_signature(label_set)
        key = (label_set, version)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[0] == signature:
                return cached[1]
            tracks, moments = repo.tag_prob_moments(label_set, version)
            stats: dict[str, tuple[float, float]] = {}
            for label, (total, squares) in moments.items():
                mean = total / tracks
                stats[label] = (mean, float(np.sqrt(max(squares / tracks - mean * mean, 0.0))))
            # The signature was read before the rows: if they changed meanwhile, the next call
            # sees another signature and recomputes.
            self._cache[key] = (signature, stats)
            return stats

    def scores_with_coverage(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """Standardised scores (0 where unknown) and which tracks have stored rows for the set."""
        out, covered = self._stored.scores_with_coverage(track_ids, label_set, labels)
        allowed = self._stored.allowed_versions
        version = None if allowed is None else allowed.get(label_set)
        if (allowed is not None and version is None) or not covered.any():
            return out, covered  # nothing usable is stored: nothing to standardise
        stats = self._stats(label_set, version)
        for label in labels:
            if label not in stats:
                out[label][:] = 0.0  # no covered track has a row for it
                continue
            mean, std = stats[label]
            if std <= MIN_STD:
                out[label][covered] = 0.5
            else:
                out[label][covered] = squash((out[label][covered] - mean) / std)
        return out, covered

    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]:
        return self.scores_with_coverage(track_ids, label_set, labels)[0]


class ZeroShotTagScorer:
    """Cosine to ``"<display name> music"``, standardised over the whole catalog.

    For each label the cosine of every embedded track in the index to the label's text embedding
    gives a mean and a standard deviation (computed once and cached with the index; a new index
    drops them). A track scores ``sigmoid(1.7 * (cos - mean) / std)``: 0.5 is an average track,
    and the score does not depend on which other tracks are being scored. If every track has the
    same cosine (std 0) all tracks score 0.5. Tracks without an embedding score 0.

    ``index`` returns the current :class:`NumpyVectorIndex` of the default model; ``embed_text``
    embeds strings with the same model. Text embeddings are cached per label.
    """

    def __init__(
        self,
        index: Callable[[], NumpyVectorIndex],
        embed_text: Callable[[Sequence[str]], np.ndarray],
        vocab: Vocabulary,
    ) -> None:
        self._index = index
        self._embed_text = embed_text
        self._vocab = vocab
        self._text: dict[tuple[str, str], np.ndarray] = {}
        self._stats: dict[tuple[str, str], tuple[float, float]] = {}
        self._stats_index: NumpyVectorIndex | None = None

    def _label_vectors(self, label_set: str, labels: Sequence[str]) -> np.ndarray:
        missing = [label for label in labels if (label_set, label) not in self._text]
        if missing:
            template = PROMPTS.get(label_set, PROMPT)
            prompts = [
                template.format(self._vocab.display_name(label_set, label)) for label in missing
            ]
            embedded = np.asarray(self._embed_text(prompts), dtype=np.float32)
            norms = np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
            for label, vector in zip(missing, embedded / norms, strict=True):
                self._text[(label_set, label)] = vector
        return np.stack([self._text[(label_set, label)] for label in labels])

    def _label_stats(
        self, index: NumpyVectorIndex, label_set: str, labels: Sequence[str], vectors: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Mean and standard deviation of the catalog's cosines, per label."""
        if index is not self._stats_index:  # the catalog's embeddings changed: start over
            self._stats.clear()
            self._stats_index = index
        todo = [j for j, label in enumerate(labels) if (label_set, label) not in self._stats]
        if todo:
            sims = index.matrix @ vectors[todo].T  # (tracks in the index, labels to do)
            for k, j in enumerate(todo):
                self._stats[(label_set, labels[j])] = (
                    float(sims[:, k].mean()),
                    float(sims[:, k].std()),
                )
        pairs = [self._stats[(label_set, label)] for label in labels]
        return np.array([m for m, _ in pairs]), np.array([sd for _, sd in pairs])

    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]:
        out = {label: np.zeros(len(track_ids)) for label in labels}
        if not labels or not len(track_ids):
            return out
        index = self._index()
        found, matrix = index.vectors(track_ids)
        if not found.any():
            return out
        vectors = self._label_vectors(label_set, labels)
        mean, std = self._label_stats(index, label_set, labels, vectors)
        z = np.zeros((int(found.sum()), len(labels)))
        np.divide(matrix @ vectors.T - mean, std, out=z, where=std > MIN_STD)
        scores = squash(z)
        for j, label in enumerate(labels):
            out[label][found] = scores[:, j]
        return out


class CompositeTagScorer:
    """Stored rows where a track has them, zero-shot for the other tracks.

    ``stored`` is a :class:`StoredTagScorer` (raw probabilities) or a
    :class:`StandardisedTagScorer` (the same, on the zero-shot scale).
    """

    def __init__(self, stored: CoverageScorer, zero_shot: TagScorer | None) -> None:
        self._stored = stored
        self._zero_shot = zero_shot

    def scores(
        self, track_ids: Sequence[int], label_set: str, labels: Sequence[str]
    ) -> dict[str, np.ndarray]:
        out, covered = self._stored.scores_with_coverage(track_ids, label_set, labels)
        if self._zero_shot is None or covered.all():
            return out
        missing = np.flatnonzero(~covered)
        fallback = self._zero_shot.scores([track_ids[i] for i in missing], label_set, labels)
        for label in labels:
            out[label][missing] = fallback[label]
        return out
